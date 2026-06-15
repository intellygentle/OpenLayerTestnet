"""
Sepolia 自动 Mint 脚本
支持 USDT → USDT+ 或 USDC → USDC+，交互式配置次数与金额。

非交互模式:
  python auto_mint.py --token usdc --count 10 --amount 100 --yes
  python auto_mint.py --token usdt --count 1 --amount 58 --yes
交互模式（无参数）:
  python auto_mint.py
"""
import argparse
import random
import sys
import time

# Force UTF-8 on Windows for Unicode banner
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from contract_encoder import p32
from utils.crypto import private_key_to_address
from utils.display import (
    BOLD_CYAN, BOLD_GREEN, BOLD_WHITE, BOLD_YELLOW, BOLD_MAGENTA, RESET,
    banner, log_error, log_info, log_success, log_task, log_warn,
)
from utils.rpc import find_working_rpc, get_balance_eth, rpc_call, send_transaction

# ============================================================
# Sepolia 网络配置（按优先级自动切换）
# ============================================================
SEPOLIA_RPCS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://eth-sepolia.g.alchemy.com/v2/yvU9zBs-HghFUcRcdTikw",
    "https://sepolia.infura.io/v3/YOUR_INFURA_API_KEY",  # 替换为你的 Infura API Key
    "https://rpc.sepolia.org",
    "https://sepolia.drpc.org",
]
SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_EXPLORER = "https://sepolia.etherscan.io"

# ============================================================
# 代币与合约地址
# ============================================================
TOKENS = {
    "1": {
        "name": "USDT",
        "plus_name": "USDT+",
        "token": "0xaa8e23fb1079ea71e0a56f48a2aa51851d8433d0",
        "plus_contract": "0xe20534a32f9162488a90026f268a74fbe28d272d",
        "decimals": 6,
    },
    "2": {
        "name": "USDC",
        "plus_name": "USDC+",
        "token": "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8",
        "plus_contract": "0xE815718D44694ec4637CB775C468d87f6e15B538",
        "decimals": 6,
    },
}

# ============================================================
# Mint 参数
# ============================================================
MINT_SELECTOR = "2ef6f1ab"
PLUS_DECIMALS = 18
DELAY_MIN = 5.0
DELAY_MAX = 12.0
GAS_LIMIT = 200_000
MAX_CONSECUTIVE_FAILS = 3


def build_mint_calldata(caller, receiver, token, token_amount, eth_amount):
    """编码 mint(tuple(address,address,address,uint256,uint256))"""
    parts = [MINT_SELECTOR]
    parts.append(p32(int(caller.lower().replace("0x", ""), 16)))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    parts.append(p32(int(token.lower().replace("0x", ""), 16)))
    parts.append(p32(token_amount))
    parts.append(p32(eth_amount))
    return "0x" + "".join(parts)


def get_token_balance(address, token_addr, rpc_url):
    """查询 ERC-20 代币余额（balanceOf）"""
    balance_selector = "70a08231"
    padded_addr = p32(int(address.lower().replace("0x", ""), 16))
    call_data = "0x" + balance_selector + padded_addr
    result = rpc_call(
        rpc_url, "eth_call",
        [{"to": token_addr, "data": call_data}, "latest"],
    )
    if result and "result" in result:
        return int(result["result"], 16)
    return 0


def run(token_choice=None, mint_count=None, token_per_mint=None, skip_confirm=False):
    pk = config.load_master_key()
    if not pk:
        log_error("未找到私钥，请在 master_privatekey.txt 中填入")
        log_error("  或在 .env 中设置 FUNDING_PRIVATE_KEY=0x...")
        return False

    addr = private_key_to_address(pk)

    # 找到可用 RPC
    print(f"\n{BOLD_CYAN}{'=' * 70}{RESET}")
    log_task("正在检测可用 RPC 节点...")
    rpc_url = find_working_rpc(SEPOLIA_RPCS)
    if not rpc_url:
        log_error("所有 RPC 节点均不可用，请检查网络连接")
        return False

    # ============================================================
    # 选择代币（交互或参数）
    # ============================================================
    if token_choice is None:
        print(f"\n{BOLD_YELLOW}请选择要使用的代币：{RESET}")
        print(f"  {BOLD_WHITE}[1] USDT → USDT+{RESET}")
        print(f"  {BOLD_WHITE}[2] USDC → USDC+{RESET}")
        choice = input(f"  {BOLD_WHITE}输入 1 或 2（默认 1）: {RESET}").strip()
        if choice not in TOKENS:
            choice = "1"
    else:
        # Map string name to key
        token_map = {"usdt": "1", "usdc": "2", "1": "1", "2": "2"}
        choice = token_map.get(token_choice.lower(), "1")

    cfg = TOKENS[choice]
    token_name = cfg["name"]
    plus_name = cfg["plus_name"]
    token_addr = cfg["token"]
    plus_contract = cfg["plus_contract"]
    token_decimals = cfg["decimals"]

    # 查询余额
    token_bal_raw = get_token_balance(addr, token_addr, rpc_url)
    token_bal = token_bal_raw / 10**token_decimals
    eth_bal = get_balance_eth(rpc_url, addr)

    print(f"\n{BOLD_CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD_GREEN}  自动 Mint 脚本 — Sepolia 测试网{RESET}")
    print(f"  {BOLD_WHITE}钱包       : {addr}{RESET}")
    print(f"  {BOLD_WHITE}{token_name} 余额   : {token_bal:.6f} {token_name}{RESET}")
    print(f"  {BOLD_WHITE}ETH 余额    : {eth_bal:.8f} ETH{RESET}")
    print(f"  {BOLD_WHITE}{token_name} 合约   : {token_addr}{RESET}")
    print(f"  {BOLD_WHITE}{plus_name} 合约  : {plus_contract}{RESET}")
    print(f"{BOLD_CYAN}{'=' * 70}{RESET}")

    # ============================================================
    # 配置参数（交互或命令行）
    # ============================================================
    if mint_count is None or token_per_mint is None:
        print(f"\n{BOLD_YELLOW}请配置 Mint 参数：{RESET}")

    if mint_count is None:
        try:
            count_input = input(
                f"  {BOLD_WHITE}Mint 次数（默认 23）: {RESET}"
            ).strip()
            mint_count = int(count_input) if count_input else 23
            if mint_count <= 0:
                log_error("次数必须大于 0")
                return False
        except (ValueError, EOFError):
            log_error("输入无效，请输入整数")
            return False

    if token_per_mint is None:
        try:
            amount_input = input(
                f"  {BOLD_WHITE}每次 Mint 的 {token_name} 数量（默认 1）: {RESET}"
            ).strip()
            token_per_mint = float(amount_input) if amount_input else 1.0
            if token_per_mint <= 0:
                log_error("数量必须大于 0")
                return False
        except (ValueError, EOFError):
            log_error("输入无效，请输入数字")
            return False

    # 计算参数
    token_amount_raw = int(token_per_mint * 10**token_decimals)
    plus_amount_raw = int(token_per_mint * 10**PLUS_DECIMALS)
    needed_token = mint_count * token_per_mint
    needed_gas_eth = (GAS_LIMIT * 25 * 10**9) / 10**18 * mint_count

    print(f"\n{BOLD_MAGENTA}{'─' * 70}{RESET}")
    print(
        f"{BOLD_YELLOW}  Mint 计划: {BOLD_WHITE}"
        f"{mint_count} 次 × {token_per_mint} {token_name} = "
        f"{needed_token} {token_name}{RESET}"
    )
    print(f"{BOLD_YELLOW}  预估 Gas: ~{needed_gas_eth:.6f} ETH{RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 70}{RESET}")

    # 余额检查
    if token_bal < needed_token:
        log_error(
            f"{token_name} 余额不足！需要至少 {needed_token} {token_name}，"
            f"当前 {token_bal:.6f} {token_name}"
        )
        return False

    if eth_bal < needed_gas_eth:
        log_error(
            f"ETH 余额不足以支付 Gas！"
            f"需要 ~{needed_gas_eth:.6f} ETH，当前 {eth_bal:.8f} ETH"
        )
        return False

    # 确认执行
    if skip_confirm:
        log_info("非交互模式，自动确认执行")
    else:
        confirm = input(
            f"  {BOLD_WHITE}确认开始 Mint？(y/n): {RESET}"
        ).strip().lower()
        if confirm not in ("y", "yes"):
            log_info("已取消 Mint")
            return False

    calldata = build_mint_calldata(
        addr, addr, token_addr, token_amount_raw, plus_amount_raw
    )

    ok = 0
    consecutive_fails = 0

    for i in range(1, mint_count + 1):
        log_task(
            f"第 {i}/{mint_count} 次 Mint | "
            f"{token_per_mint} {token_name} → {token_per_mint} {plus_name}"
        )

        result = send_transaction(
            rpc_url=rpc_url,
            explorer_url=SEPOLIA_EXPLORER,
            chain_id=SEPOLIA_CHAIN_ID,
            pk=pk,
            address=addr,
            to_contract=plus_contract,
            value_wei=0,
            calldata=calldata,
            action_name=f"Mint {plus_name} #{i}",
            gas_limit_override=GAS_LIMIT,
            proxy=None,
        )

        if result and result not in ("FAILED", "INSUFFICIENT", None):
            ok += 1
            consecutive_fails = 0
            log_success(f"第 {i} 次 Mint 完成 ✓")
        else:
            consecutive_fails += 1
            status = result if result else "未知错误"
            log_error(f"第 {i} 次 Mint 失败: {status}")

            if result == "INSUFFICIENT":
                log_error("ETH 余额不足以支付 Gas 费，脚本中止")
                break

            if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
                log_error(
                    f"连续 {MAX_CONSECUTIVE_FAILS} 次失败，"
                    f"可能 {token_name} 余额不足或合约状态异常，脚本中止"
                )
                break

        if i < mint_count:
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            log_info(f"等待 {delay:.1f} 秒后继续...")
            time.sleep(delay)

    print(f"\n{BOLD_GREEN}{'=' * 70}{RESET}")
    print(f"{BOLD_GREEN}  全部完成: {ok}/{mint_count} 次 Mint 成功{RESET}")
    if ok > 0:
        print(
            f"{BOLD_GREEN}  预计获得: {ok * token_per_mint:.6f} {plus_name}{RESET}"
        )
    print(f"{BOLD_GREEN}{'=' * 70}{RESET}\n")
    return ok == mint_count


def main():
    parser = argparse.ArgumentParser(
        description="Sepolia 自动 Mint — USDT/USDC → USDT+/USDC+"
    )
    parser.add_argument("--token", choices=["usdt", "usdc", "1", "2"],
                        help="代币: usdt (USDT→USDT+) 或 usdc (USDC→USDC+)")
    parser.add_argument("--count", type=int, help="Mint 次数")
    parser.add_argument("--amount", type=float, help="每次 Mint 数量")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="跳过确认，直接执行")
    args = parser.parse_args()

    banner()
    print(
        f"  {BOLD_WHITE}网络  : Sepolia 测试网（Chain ID {SEPOLIA_CHAIN_ID}）{RESET}"
    )
    print(f"  {BOLD_WHITE}功能  : USDT/USDC → USDT+/USDC+ 自动 Mint{RESET}")
    if args.token and args.count and args.amount:
        print(f"  {BOLD_GREEN}模式  : 非交互（CLI 参数）{RESET}\n")
    else:
        print(f"  {BOLD_YELLOW}模式  : 交互式{RESET}\n")

    success = run(
        token_choice=args.token,
        mint_count=args.count,
        token_per_mint=args.amount,
        skip_confirm=args.yes,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
