"""
Quick non-interactive USDC+ transfer — takes amount as command-line arg.
Usage: python quick_transfer_usdc.py <amount> [--dest <address>]
       python quick_transfer_usdc.py --amount 413 --dest 0x...
"""
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from contract_encoder import p32
from utils.crypto import private_key_to_address
from utils.display import (
    BOLD_CYAN, BOLD_GREEN, BOLD_WHITE, BOLD_YELLOW, RESET,
    banner, log_error, log_info, log_success, log_task,
)
from utils.rpc import find_working_rpc, get_balance_eth, rpc_call, send_transaction

USDC_PLUS = "0xE815718D44694ec4637CB775C468d87f6e15B538"
DECIMALS = 18  # USDC+ has 18 decimals (same as USDT+, auto-detected by transfer_usdc_plus.py)
SEPOLIA_RPCS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://eth-sepolia.g.alchemy.com/v2/yvU9zBs-HghFUcRcdTikw",
]
CHAIN_ID = 11155111
EXPLORER = "https://sepolia.etherscan.io"


def main():
    parser = argparse.ArgumentParser(description="Quick USDC+ transfer on Sepolia")
    parser.add_argument("amount", nargs="?", type=float, default=None,
                        help="Amount of USDC+ to transfer")
    parser.add_argument("--amount", "-a", dest="amount_flag", type=float,
                        help="Amount of USDC+ to transfer (named arg)")
    parser.add_argument("--dest", "-d", type=str, default=None,
                        help="Destination address (default: first wallet in wallets.txt)")
    args = parser.parse_args()

    # Resolve amount
    amount = args.amount_flag or args.amount
    if amount is None:
        amount = 1.0
        log_info(f"未指定数量，默认使用 {amount} USDC+")

    pk = config.load_master_key()
    if not pk:
        log_error("未找到私钥")
        sys.exit(1)

    addr = private_key_to_address(pk)

    # Resolve destination
    if args.dest:
        dest = args.dest
    else:
        wallets = config.load_wallets()
        if not wallets:
            log_error("未找到目标钱包，请在 wallets.txt 中填入地址")
            sys.exit(1)
        dest = wallets[0]

    banner()
    print(f"  {BOLD_WHITE}转账 {amount} USDC+ → {dest[:10]}...{RESET}\n")

    log_task("检测 RPC...")
    rpc = find_working_rpc(SEPOLIA_RPCS)
    if not rpc:
        log_error("无可用 RPC")
        sys.exit(1)

    # Balances
    bal_sel = "70a08231"
    cd = "0x" + bal_sel + p32(int(addr[2:], 16))
    res = rpc_call(rpc, "eth_call", [{"to": USDC_PLUS, "data": cd}, "latest"])
    if res and "result" in res:
        bal = int(res["result"], 16) / 10**DECIMALS
    else:
        bal = 0.0

    eth = get_balance_eth(rpc, addr)

    print(f"  {BOLD_WHITE}USDC+ 余额: {bal:.6f}{RESET}")
    print(f"  {BOLD_WHITE}ETH 余额 : {eth:.8f}{RESET}")

    if bal < amount:
        log_error(f"USDC+ 余额不足！需要 {amount:.6f}，当前 {bal:.6f}")
        sys.exit(1)

    amount_raw = int(amount * 10**DECIMALS)
    calldata = "0x" + "a9059cbb" + p32(int(dest[2:], 16)) + p32(amount_raw)

    log_task(f"发送 {amount} USDC+ ...")
    result = send_transaction(
        rpc_url=rpc, explorer_url=EXPLORER, chain_id=CHAIN_ID,
        pk=pk, address=addr, to_contract=USDC_PLUS,
        value_wei=0, calldata=calldata,
        action_name=f"Transfer {amount} USDC+",
        gas_limit_override=100000, proxy=None,
    )

    if result and result not in ("FAILED", "INSUFFICIENT", None):
        log_success(f"成功! TX: {result}")
        print(f"  {BOLD_WHITE}浏览器: {BOLD_CYAN}{EXPLORER}/tx/{result}{RESET}")
    else:
        log_error(f"失败: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()
