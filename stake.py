"""
Sepolia Staking Script
Stakes USDT+ or USDC+ tokens into their respective staking contracts.

Non-interactive mode:
  python stake.py --amount 444 --token usdt --yes
  python stake.py --amount 444 --token usdc --yes
Interactive mode (no args):
  python stake.py
"""
import argparse
import sys

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
# Sepolia Network Config (auto-switch by priority)
# ============================================================
SEPOLIA_RPCS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://eth-sepolia.g.alchemy.com/v2/yvU9zBs-HghFUcRcdTikw",
    "https://sepolia.infura.io/v3/YOUR_INFURA_API_KEY",
    "https://rpc.sepolia.org",
    "https://sepolia.drpc.org",
]
SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_EXPLORER = "https://sepolia.etherscan.io"

# ============================================================
# Staking Token Configs (each has its own staking contract!)
# ============================================================
STAKABLE_TOKENS = {
    "usdt": {
        "name": "USDT+",
        "token": "0xe20534a32f9162488a90026F268a74fBE28d272D",
        "stake_contract": "0x079a4Bf1Cbd0E4ce15391340cB46efA6396aBc82",
        "decimals": 18,
    },
    "usdc": {
        "name": "USDC+",
        "token": "0xE815718D44694ec4637CB775C468d87f6e15B538",
        "stake_contract": "0x753937137eb92871A6f3517514d4f1ee860E3fDF",
        "decimals": 18,
    },
    "1": {
        "name": "USDT+",
        "token": "0xe20534a32f9162488a90026F268a74fBE28d272D",
        "stake_contract": "0x079a4Bf1Cbd0E4ce15391340cB46efA6396aBc82",
        "decimals": 18,
    },
    "2": {
        "name": "USDC+",
        "token": "0xE815718D44694ec4637CB775C468d87f6e15B538",
        "stake_contract": "0x753937137eb92871A6f3517514d4f1ee860E3fDF",
        "decimals": 18,
    },
}

# ============================================================
# Function Selectors
# ============================================================
DEPOSIT_SELECTOR = "6e553f65"  # deposit(uint256 assets, address receiver)
BALANCE_SELECTOR = "70a08231"  # balanceOf(address)


def build_deposit_calldata(assets_raw, receiver):
    """Encode deposit(uint256 assets, address receiver)"""
    parts = [DEPOSIT_SELECTOR]
    parts.append(p32(assets_raw))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    return "0x" + "".join(parts)


def get_token_balance(address, token_addr, rpc_url):
    """Query ERC-20 token balance"""
    padded_addr = p32(int(address.lower().replace("0x", ""), 16))
    call_data = "0x" + BALANCE_SELECTOR + padded_addr
    result = rpc_call(
        rpc_url, "eth_call",
        [{"to": token_addr, "data": call_data}, "latest"],
    )
    if result and "result" in result:
        return int(result["result"], 16)
    return 0


def run(stake_amount=None, token_choice=None, skip_confirm=False):
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

    # ── Choose staking token ──
    if token_choice is None:
        print(f"\n{BOLD_YELLOW}Select staking token:{RESET}")
        print(f"  {BOLD_WHITE}[1] USDT+ (0xe205...){RESET}")
        print(f"  {BOLD_WHITE}[2] USDC+ (0xE815...){RESET}")
        choice = input(f"  {BOLD_WHITE}Enter 1 or 2 (default 1): {RESET}").strip()
        if choice not in STAKABLE_TOKENS:
            choice = "usdt"
    else:
        token_map = {"usdt": "usdt", "usdc": "usdc", "1": "usdt", "2": "usdc"}
        choice = token_map.get(token_choice.lower(), "usdt")

    cfg = STAKABLE_TOKENS[choice]
    stake_token = cfg["token"]
    stake_contract = cfg["stake_contract"]
    token_name = cfg["name"]
    decimals = cfg["decimals"]

    # Query balances
    token_bal_raw = get_token_balance(addr, stake_token, rpc_url)
    token_bal = token_bal_raw / 10**decimals
    eth_bal = get_balance_eth(rpc_url, addr)

    print(f"\n{BOLD_CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD_GREEN}  {token_name} Staking — Sepolia Testnet{RESET}")
    print(f"  {BOLD_WHITE}Wallet        : {addr}{RESET}")
    print(f"  {BOLD_WHITE}{token_name} Balance : {token_bal:.6f} {token_name}{RESET}")
    print(f"  {BOLD_WHITE}ETH Balance   : {eth_bal:.8f} ETH{RESET}")
    print(f"  {BOLD_WHITE}{token_name} Contract: {stake_token}{RESET}")
    print(f"  {BOLD_WHITE}Stake Contract: {stake_contract}{RESET}")
    print(f"{BOLD_CYAN}{'=' * 70}{RESET}")

    # ============================================================
    # Interactive input or use CLI args
    # ============================================================
    if stake_amount is None:
        print(f"\n{BOLD_YELLOW}Configure staking parameters:{RESET}")
        try:
            amount_input = input(
                f"  {BOLD_WHITE}Amount of {token_name} to stake (e.g. 10, 0.5): {RESET}"
            ).strip()
            stake_amount = float(amount_input)
            if stake_amount <= 0:
                log_error("Amount must be greater than 0")
                return False
        except (ValueError, EOFError):
            log_error("Invalid input. Please enter a number.")
            return False

    amount_raw = int(stake_amount * 10**decimals)

    if token_bal_raw < amount_raw:
        log_error(
            f"Insufficient {token_name} balance! "
            f"Need {stake_amount:.6f} {token_name}, "
            f"current balance: {token_bal:.6f} {token_name}"
        )
        return False

    # Gas estimate (deposit typically uses 150k-250k gas)
    gas_limit = 250_000
    needed_gas_eth = (gas_limit * 30 * 10**9) / 10**18
    if eth_bal < needed_gas_eth:
        log_error(
            f"Insufficient ETH for gas! Need ~{needed_gas_eth:.8f} ETH, "
            f"current balance: {eth_bal:.8f} ETH"
        )
        return False

    # Confirm
    print(f"\n{BOLD_MAGENTA}{'─' * 70}{RESET}")
    print(f"{BOLD_YELLOW}  About to stake: {BOLD_WHITE}{stake_amount:.6f} {token_name}{RESET}")
    print(f"{BOLD_YELLOW}  To contract   : {BOLD_WHITE}{stake_contract}{RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 70}{RESET}")

    if skip_confirm:
        log_info("Non-interactive mode, auto-confirming...")
    else:
        confirm = input(f"  {BOLD_WHITE}Confirm stake? (y/n): {RESET}").strip().lower()
        if confirm not in ("y", "yes"):
            log_info("Staking cancelled")
            return False

    # Build calldata
    calldata = build_deposit_calldata(amount_raw, addr)

    log_task(f"Staking {stake_amount:.6f} {token_name}...")

    result = send_transaction(
        rpc_url=rpc_url,
        explorer_url=SEPOLIA_EXPLORER,
        chain_id=SEPOLIA_CHAIN_ID,
        pk=pk,
        address=addr,
        to_contract=stake_contract,  # <-- correct contract per token!
        value_wei=0,
        calldata=calldata,
        action_name=f"Stake {stake_amount:.6f} {token_name}",
        gas_limit_override=gas_limit,
        proxy=None,
    )

    if result and result not in ("FAILED", "INSUFFICIENT", None):
        log_success(f"Staked successfully! {stake_amount:.6f} {token_name} deposited")
        print(f"  {BOLD_WHITE}TX Hash: {BOLD_CYAN}{result}{RESET}")
        print(
            f"  {BOLD_WHITE}Explorer: "
            f"{BOLD_CYAN}{SEPOLIA_EXPLORER}/tx/{result}{RESET}"
        )
        return True
    else:
        log_error(f"Stake failed: {result}")
        if result == "INSUFFICIENT":
            log_error("Insufficient ETH for gas")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Sepolia Staking — USDT+ / USDC+ → Staking Contract"
    )
    parser.add_argument("--amount", type=float, help="Amount to stake")
    parser.add_argument("--token", choices=["usdt", "usdc", "1", "2"],
                        help="Token: usdt (USDT+) or usdc (USDC+)")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Skip confirmation, execute immediately")
    args = parser.parse_args()

    banner()
    print(
        f"  {BOLD_WHITE}Network : Sepolia Testnet (Chain ID {SEPOLIA_CHAIN_ID}){RESET}"
    )
    print(f"  {BOLD_WHITE}Tokens  : USDT+ / USDC+ → Staking Contracts{RESET}")
    print(f"  {BOLD_WHITE}Function: deposit(uint256, address){RESET}")
    if args.amount and args.token:
        print(f"  {BOLD_GREEN}Mode    : Non-interactive (CLI args){RESET}\n")
    else:
        print(f"  {BOLD_YELLOW}Mode    : Interactive{RESET}\n")

    success = run(
        stake_amount=args.amount,
        token_choice=args.token,
        skip_confirm=args.yes,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
