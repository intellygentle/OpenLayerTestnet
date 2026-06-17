"""
Sepolia Provide sC+ Liquidity Script
Deposits sC+ (staked USDC+) into a MasterChef-style liquidity pool.

Non-interactive mode:
  python provide_sc_liquidity.py --amount 1000 --yes
  python provide_sc_liquidity.py -a 1000 -y
Interactive mode (no args):
  python provide_sc_liquidity.py
"""
import argparse
import sys

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
# Sepolia Network Config
# ============================================================
SEPOLIA_RPCS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://eth-sepolia.g.alchemy.com/v2/yvU9zBs-HghFUcRcdTikw",
    "https://rpc.sepolia.org",
    "https://sepolia.drpc.org",
]
SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_EXPLORER = "https://sepolia.etherscan.io"

# ============================================================
# sC+ Liquidity Pool Config
# ============================================================
SC_TOKEN = {
    "name": "sC+",
    "full_name": "Staked USDC+",
    "token": "0x753937137eb92871a6f3517514d4f1ee860e3fdf",  # sC+ = staked USDC+ receipt token
    "liquidity_contract": "0x88Fe18C721c9380f80592Cb1496C50C7Ea97ABeB",
    "pool_id": 0,
    "decimals": 18,
}

# ============================================================
# Function Selectors
# ============================================================
DEPOSIT_SELECTOR   = "e2bbb158"   # deposit(uint256 _pid, uint256 _amount)
APPROVE_SELECTOR   = "095ea7b3"   # approve(address spender, uint256 amount)
ALLOWANCE_SELECTOR = "dd62ed3e"   # allowance(address owner, address spender)
BALANCE_SELECTOR   = "70a08231"   # balanceOf(address)

# ============================================================
# Gas Limits
# ============================================================
GAS_APPROVE = 60_000
GAS_DEPOSIT = 300_000


def build_deposit_calldata(pid, amount_raw):
    """Encode deposit(uint256 _pid, uint256 _amount) - MasterChef style."""
    parts = [DEPOSIT_SELECTOR]
    parts.append(p32(pid))
    parts.append(p32(amount_raw))
    return "0x" + "".join(parts)


def build_approve_calldata(spender, amount_raw):
    """Encode approve(address spender, uint256 amount)."""
    parts = [APPROVE_SELECTOR]
    parts.append(p32(int(spender.lower().replace("0x", ""), 16)))
    parts.append(p32(amount_raw))
    return "0x" + "".join(parts)


def get_token_balance(address, token_addr, rpc_url):
    """Query ERC-20 token balanceOf."""
    padded = p32(int(address.lower().replace("0x", ""), 16))
    cd = "0x" + BALANCE_SELECTOR + padded
    result = rpc_call(rpc_url, "eth_call", [{"to": token_addr, "data": cd}, "latest"])
    if result and "result" in result:
        return int(result["result"], 16)
    return 0


def get_allowance(owner, spender, token_addr, rpc_url):
    """Query ERC-20 allowance."""
    data = "0x" + ALLOWANCE_SELECTOR
    data += p32(int(owner.lower().replace("0x", ""), 16))
    data += p32(int(spender.lower().replace("0x", ""), 16))
    result = rpc_call(rpc_url, "eth_call", [{"to": token_addr, "data": data}, "latest"])
    if result and "result" in result:
        return int(result["result"], 16)
    return 0


def run(amount=None, skip_confirm=False):
    pk = config.load_master_key()
    if not pk:
        log_error("No private key found. Please add it to master_privatekey.txt")
        log_error("  or set FUNDING_PRIVATE_KEY=0x... in .env")
        return False

    addr = private_key_to_address(pk)

    # Find working RPC
    print(f"\n{BOLD_CYAN}{'=' * 70}{RESET}")
    log_task("Scanning for available RPC nodes...")
    rpc_url = find_working_rpc(SEPOLIA_RPCS)
    if not rpc_url:
        log_error("All RPC nodes are unavailable. Check your network connection.")
        return False

    cfg = SC_TOKEN
    token_name = cfg["name"]
    token_addr = cfg["token"]
    pool_contract = cfg["liquidity_contract"]
    pool_id = cfg["pool_id"]
    decimals = cfg["decimals"]

    # Query balances
    token_bal_raw = get_token_balance(addr, token_addr, rpc_url)
    token_bal = token_bal_raw / 10**decimals
    eth_bal = get_balance_eth(rpc_url, addr)

    print(f"\n{BOLD_CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD_GREEN}  Provide sC+ Liquidity — Sepolia Testnet{RESET}")
    print(f"  {BOLD_WHITE}Wallet                    : {addr}{RESET}")
    print(f"  {BOLD_WHITE}{token_name} ({cfg['full_name']}) Balance : {token_bal:.6f} {token_name}{RESET}")
    print(f"  {BOLD_WHITE}ETH Balance               : {eth_bal:.8f} ETH{RESET}")
    print(f"  {BOLD_WHITE}sC+ Token Contract        : {token_addr}{RESET}")
    print(f"  {BOLD_WHITE}Liquidity Pool            : {pool_contract}{RESET}")
    print(f"  {BOLD_WHITE}Pool ID                   : {pool_id}{RESET}")
    print(f"  {BOLD_WHITE}Function                  : deposit({pool_id}, amount){RESET}")
    print(f"{BOLD_CYAN}{'=' * 70}{RESET}")

    # ============================================================
    # Interactive input or use CLI args
    # ============================================================
    if amount is None:
        print(f"\n{BOLD_YELLOW}Configure sC+ liquidity parameters:{RESET}")
        try:
            amount_input = input(
                f"  {BOLD_WHITE}Amount of {token_name} to deposit (e.g. 1000): {RESET}"
            ).strip()
            amount = float(amount_input)
            if amount <= 0:
                log_error("Amount must be greater than 0")
                return False
        except (ValueError, EOFError):
            log_error("Invalid input. Please enter a number.")
            return False

    amount_raw = int(amount * 10**decimals)

    # ── Balance check ──
    if token_bal_raw < amount_raw:
        log_error(
            f"Insufficient {token_name} balance! "
            f"Need {amount:.6f} {token_name}, "
            f"current balance: {token_bal:.6f} {token_name}"
        )
        print(f"\n  {BOLD_YELLOW}Tip: You need sC+ (staked USDC+) tokens to provide as liquidity.{RESET}")
        print(f"  {BOLD_YELLOW}     First stake USDC+ via stake.py to get sC+ tokens.{RESET}")
        return False

    # Gas estimate
    needed_gas_eth = ((GAS_APPROVE + GAS_DEPOSIT) * 30 * 10**9) / 10**18
    if eth_bal < needed_gas_eth:
        log_error(
            f"Insufficient ETH for gas! Need ~{needed_gas_eth:.8f} ETH, "
            f"current balance: {eth_bal:.8f} ETH"
        )
        return False

    # ── Check current allowance ──
    log_info("Checking current allowance...")
    current_allowance = get_allowance(addr, pool_contract, token_addr, rpc_url)
    need_approval = current_allowance < amount_raw
    if need_approval:
        log_info(f"Current allowance: {current_allowance / 10**decimals:.6f} {token_name}")
        log_info(f"Need to approve {pool_contract[:10]}... to spend {amount:.6f} {token_name}")
    else:
        log_success(f"Allowance sufficient: {current_allowance / 10**decimals:.6f} {token_name}")

    # ── Summary & Confirm ──
    print(f"\n{BOLD_MAGENTA}{'─' * 70}{RESET}")
    print(f"{BOLD_YELLOW}  About to deposit:{RESET}")
    print(f"  {BOLD_WHITE}  Amount   : {amount:.6f} {token_name} ({cfg['full_name']}){RESET}")
    print(f"  {BOLD_WHITE}  Pool ID  : {pool_id}{RESET}")
    print(f"  {BOLD_WHITE}  Pool     : {pool_contract}{RESET}")
    if need_approval:
        print(f"  {BOLD_YELLOW}  + 1 approve tx will be sent first{RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 70}{RESET}")

    if skip_confirm:
        log_info("Non-interactive mode, auto-confirming...")
    else:
        confirm = input(f"  {BOLD_WHITE}Confirm deposit? (y/n): {RESET}").strip().lower()
        if confirm not in ("y", "yes"):
            log_info("Deposit cancelled")
            return False

    # ═══════════════════════════════════════════════════════════════
    # Step 1: Approve (if needed)
    # ═══════════════════════════════════════════════════════════════
    if need_approval:
        approve_cd = build_approve_calldata(pool_contract, amount_raw)

        log_task(f"Approving {pool_contract[:10]}... to spend {amount:.6f} {token_name}...")

        result = send_transaction(
            rpc_url=rpc_url,
            explorer_url=SEPOLIA_EXPLORER,
            chain_id=SEPOLIA_CHAIN_ID,
            pk=pk,
            address=addr,
            to_contract=token_addr,
            value_wei=0,
            calldata=approve_cd,
            action_name=f"Approve {token_name} for Liquidity",
            gas_limit_override=GAS_APPROVE,
            proxy=None,
        )

        if not result or result in ("FAILED", "INSUFFICIENT", None):
            log_error(f"Approval failed: {result}")
            if result == "INSUFFICIENT":
                log_error("Insufficient ETH for gas")
            return False

        log_success(f"Approval complete for {amount:.6f} {token_name}")

    # ═══════════════════════════════════════════════════════════════
    # Step 2: Deposit
    # ═══════════════════════════════════════════════════════════════
    deposit_cd = build_deposit_calldata(pool_id, amount_raw)

    log_task(f"Depositing {amount:.6f} {token_name} into pool #{pool_id}...")

    result = send_transaction(
        rpc_url=rpc_url,
        explorer_url=SEPOLIA_EXPLORER,
        chain_id=SEPOLIA_CHAIN_ID,
        pk=pk,
        address=addr,
        to_contract=pool_contract,
        value_wei=0,
        calldata=deposit_cd,
        action_name=f"Provide {amount:.6f} {token_name} Liquidity",
        gas_limit_override=GAS_DEPOSIT,
        proxy=None,
    )

    if result and result not in ("FAILED", "INSUFFICIENT", None):
        log_success(f"Liquidity provided successfully! {amount:.6f} {token_name} deposited into pool #{pool_id}")
        print(f"  {BOLD_WHITE}TX Hash: {BOLD_CYAN}{result}{RESET}")
        print(
            f"  {BOLD_WHITE}Explorer: "
            f"{BOLD_CYAN}{SEPOLIA_EXPLORER}/tx/{result}{RESET}"
        )
        return True
    else:
        log_error(f"Deposit failed: {result}")
        if result == "INSUFFICIENT":
            log_error("Insufficient ETH for gas")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Sepolia Provide sC+ Liquidity — sC+ → MasterChef Pool"
    )
    parser.add_argument("--amount", "-a", type=float, help="Amount of sC+ to deposit")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation, execute immediately")
    args = parser.parse_args()

    banner()
    print(
        f"  {BOLD_WHITE}Network : Sepolia Testnet (Chain ID {SEPOLIA_CHAIN_ID}){RESET}"
    )
    print(f"  {BOLD_WHITE}Token   : sC+ (Staked USDC+) — {SC_TOKEN['token']}{RESET}")
    print(f"  {BOLD_WHITE}Pool    : {SC_TOKEN['liquidity_contract']}{RESET}")
    print(f"  {BOLD_WHITE}Pool ID : {SC_TOKEN['pool_id']}{RESET}")
    print(f"  {BOLD_WHITE}Function: deposit(uint256 _pid, uint256 _amount){RESET}")
    if args.amount:
        print(f"  {BOLD_GREEN}Mode    : Non-interactive (CLI args){RESET}\n")
    else:
        print(f"  {BOLD_YELLOW}Mode    : Interactive{RESET}\n")

    success = run(
        amount=args.amount,
        skip_confirm=args.yes,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
