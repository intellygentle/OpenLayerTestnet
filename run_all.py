"""
Sepolia All-in-One Task Runner

Execution order (mints run first to provide tokens for stake/send):
  1. Mint USDC+ (if configured)
  2. Mint USDT+ (if configured)
  3. Stake (USDT+ or USDC+)
  4. Send (USDC+ or USDT+ to target wallet)

Interactive mode (default):
  python run_all.py
   # Prompts for token choice, amount, and count at each step

Auto mode (uses .env params, single confirmation):
  python run_all.py --auto
  python run_all.py --yes

Override via .env:
  MINT_TARGET=58       # Minimum USDT+ mint amount
  STAKE_TARGET=444     # Minimum stake amount
  SEND_TARGET=413      # Minimum USDC+ send amount
  MIN_TX=16            # Minimum transaction count
  STAKE_TOKEN=usdc     # Stake token: usdt (USDT+) or usdc (USDC+)
  MINT_PER_TX=100      # Amount per mint tx
  DELAY_MIN=5          # Min delay between txs (seconds)
  DELAY_MAX=12         # Max delay between txs (seconds)
"""

import argparse
import os
import random
import sys
import time

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
from contract_encoder import p32
from utils.crypto import private_key_to_address
from utils.display import (
    BOLD_CYAN, BOLD_GREEN, BOLD_WHITE, BOLD_YELLOW, BOLD_MAGENTA, BOLD_RED, RESET,
    banner, log_error, log_info, log_success, log_task, log_warn,
)
from utils.rpc import find_working_rpc, get_balance_eth, rpc_call, send_transaction

# ============================================================
# Network Config
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
# Token Addresses
# ============================================================
USDT = {
    "name": "USDT", "plus_name": "USDT+",
    "token": "0xaa8e23fb1079ea71e0a56f48a2aa51851d8433d0",
    "plus": "0xe20534a32f9162488a90026F268a74fBE28d272D",
    "stake_contract": "0x079a4Bf1Cbd0E4ce15391340cB46efA6396aBc82",
    "decimals": 6, "plus_decimals": 18,
}
USDC = {
    "name": "USDC", "plus_name": "USDC+",
    "token": "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8",
    "plus": "0xE815718D44694ec4637CB775C468d87f6e15B538",
    "stake_contract": "0x753937137eb92871A6f3517514d4f1ee860E3fDF",
    "decimals": 6, "plus_decimals": 18,
}

# Selectors
MINT_SELECTOR = "2ef6f1ab"        # mint(tuple(address,address,address,uint256,uint256))
DEPOSIT_SELECTOR = "6e553f65"     # deposit(uint256 assets, address receiver)
TRANSFER_SELECTOR = "a9059cbb"    # transfer(address to, uint256 amount)
BALANCE_SELECTOR = "70a08231"     # balanceOf(address)

# ============================================================
# Configurable Parameters (.env override)
# ============================================================
def _env_int(key, default):
    try: return int(os.getenv(key, str(default)))
    except: return default

def _env_float(key, default):
    try: return float(os.getenv(key, str(default)))
    except: return default

MINT_TARGET = _env_float("MINT_TARGET", 58)         # Minimum USDT+ mint amount
STAKE_TARGET = _env_float("STAKE_TARGET", 444)      # Minimum stake amount
SEND_TARGET = _env_float("SEND_TARGET", 413)        # Minimum send amount (covers ≥347 Send + ≥413 Receive)
MIN_TX = _env_int("MIN_TX", 16)                     # Minimum transaction count
STAKE_TOKEN_CHOICE = os.getenv("STAKE_TOKEN", "usdc").strip().lower()  # usdt or usdc
MINT_PER_TX = _env_float("MINT_PER_TX", 100)        # Amount per mint tx
DELAY_MIN = _env_float("DELAY_MIN", 5)
DELAY_MAX = _env_float("DELAY_MAX", 12)
GAS_LIMIT_MINT = 200_000
GAS_LIMIT_STAKE = 250_000
GAS_LIMIT_SEND = 100_000

# ============================================================
# Helper Functions
# ============================================================
def get_token_balance(rpc_url, address, token_addr):
    """Query ERC-20 token balance"""
    padded = p32(int(address.lower().replace("0x", ""), 16))
    cd = "0x" + BALANCE_SELECTOR + padded
    result = rpc_call(rpc_url, "eth_call", [{"to": token_addr, "data": cd}, "latest"])
    if result and "result" in result:
        return int(result["result"], 16)
    return 0


def build_mint_calldata(caller, receiver, token_addr, token_amount_raw, plus_amount_raw):
    """Encode mint(tuple(address,address,address,uint256,uint256))"""
    parts = [MINT_SELECTOR]
    parts.append(p32(int(caller.lower().replace("0x", ""), 16)))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    parts.append(p32(int(token_addr.lower().replace("0x", ""), 16)))
    parts.append(p32(token_amount_raw))
    parts.append(p32(plus_amount_raw))
    return "0x" + "".join(parts)


def build_stake_calldata(amount_raw, receiver):
    """Encode deposit(uint256 assets, address receiver)"""
    parts = [DEPOSIT_SELECTOR]
    parts.append(p32(amount_raw))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    return "0x" + "".join(parts)


def build_send_calldata(recipient, amount_raw):
    """Encode transfer(address to, uint256 amount)"""
    parts = [TRANSFER_SELECTOR]
    parts.append(p32(int(recipient.lower().replace("0x", ""), 16)))
    parts.append(p32(amount_raw))
    return "0x" + "".join(parts)


def print_separator(char="="):
    print(f"\n{BOLD_CYAN}{char * 70}{RESET}")


def print_header(title):
    print(f"\n{BOLD_MAGENTA}{'━' * 70}{RESET}")
    print(f"{BOLD_YELLOW}  [Phase] {title}{RESET}")
    print(f"{BOLD_MAGENTA}{'━' * 70}{RESET}")


# ============================================================
# Interactive Input Helpers
# ============================================================
def _input_float(prompt_text, default=None):
    """Interactive number input with default value"""
    hint = f" (default {default})" if default is not None else ""
    while True:
        try:
            raw = input(f"  {BOLD_WHITE}{prompt_text}{hint}: {RESET}").strip()
            if not raw and default is not None:
                return float(default)
            val = float(raw)
            if val <= 0:
                log_error("Amount must be greater than 0")
                continue
            return val
        except (ValueError, EOFError):
            log_error("Invalid input, please enter a number")


def _input_int(prompt_text, default=None):
    """Interactive integer input with default value"""
    hint = f" (default {default})" if default is not None else ""
    while True:
        try:
            raw = input(f"  {BOLD_WHITE}{prompt_text}{hint}: {RESET}").strip()
            if not raw and default is not None:
                return int(default)
            val = int(raw)
            if val <= 0:
                log_error("Count must be greater than 0")
                continue
            return val
        except (ValueError, EOFError):
            log_error("Invalid input, please enter an integer")


def _input_choice(prompt_text, options, default=None):
    """Interactive choice selection, options = [(key, label), ...]"""
    for key, label in options:
        marker = " ← default" if key == default else ""
        print(f"    {BOLD_WHITE}[{key}] {label}{marker}{RESET}")
    hint = f" (default {default})" if default else ""
    while True:
        raw = input(f"  {BOLD_WHITE}{prompt_text}{hint}: {RESET}").strip().lower()
        if not raw and default:
            return default
        if raw in [k.lower() for k, _ in options]:
            return raw
        log_error(f"Invalid option, please enter {'/'.join(k for k, _ in options)}")


def _input_yn(prompt_text, default="y"):
    """Interactive yes/no confirmation"""
    yn = "Y/n" if default == "y" else "y/N"
    hint = f" ({yn})"
    while True:
        raw = input(f"  {BOLD_WHITE}{prompt_text}{hint}: {RESET}").strip().lower()
        if not raw:
            return default == "y"
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        log_error("Please enter y or n")


# ============================================================
# Interactive Parameter Configuration
# ============================================================
def interactive_configure(usdt_bal, usdc_bal, usdt_plus_bal, usdc_plus_bal, dest_addr):
    """
    Interactively configure all operation parameters.
    Returns: (usdc_mint_count, usdc_per_tx, usdt_mint_count, usdt_per_tx,
              do_stake, stake_token_choice, stake_amount,
              do_send, send_amount, send_token_choice)
    """
    print(f"\n{BOLD_YELLOW}  ⚙️ Configure the following operation parameters:{RESET}")
    print(f"{BOLD_YELLOW}{'─' * 70}{RESET}")

    # ── 1. Mint Config ──
    print(f"\n{BOLD_MAGENTA}  📌 Step 1/3: Mint (Token Conversion){RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 70}{RESET}")
    do_mint = _input_yn("Execute Mint operations?")

    usdt_mint_count = 0
    usdt_per_tx = 0.0
    usdc_mint_count = 0
    usdc_per_tx = 0.0

    if do_mint:
        mint_token = _input_choice(
            "Select token to mint",
            [("1", "USDT → USDT+"), ("2", "USDC → USDC+"), ("3", "Mint both")],
            default="2",
        )

        if mint_token in ("1", "3"):
            print(f"\n  {BOLD_YELLOW}--- USDT → USDT+ ---{RESET}")
            print(f"  {BOLD_WHITE}Current balance: USDT {usdt_bal:.6f} | USDT+ {usdt_plus_bal:.6f}{RESET}")
            usdt_per_tx = _input_float("USDT amount per mint", default=MINT_PER_TX)
            usdt_mint_count = _input_int("Mint count", default=max(1, int(MINT_TARGET / usdt_per_tx)))
            needed = usdt_mint_count * usdt_per_tx
            if usdt_bal < needed:
                log_warn(f"USDT balance may be insufficient! Need {needed:.2f}, currently {usdt_bal:.6f}")

        if mint_token in ("2", "3"):
            print(f"\n  {BOLD_YELLOW}--- USDC → USDC+ ---{RESET}")
            print(f"  {BOLD_WHITE}Current balance: USDC {usdc_bal:.6f} | USDC+ {usdc_plus_bal:.6f}{RESET}")
            usdc_per_tx = _input_float("USDC amount per mint", default=MINT_PER_TX)
            usdc_mint_count = _input_int("Mint count", default=max(1, int(SEND_TARGET / MINT_PER_TX)))
            needed = usdc_mint_count * usdc_per_tx
            if usdc_bal < needed:
                log_warn(f"USDC balance may be insufficient! Need {needed:.2f}, currently {usdc_bal:.6f}")
    else:
        log_info("Skipping Mint operations")

    # ── 2. Stake Config ──
    print(f"\n{BOLD_MAGENTA}  📌 Step 2/3: Stake{RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 70}{RESET}")
    do_stake = _input_yn("Execute Stake operation?")

    stake_token_choice = STAKE_TOKEN_CHOICE
    stake_amount = STAKE_TARGET

    if do_stake:
        stake_token_choice = _input_choice(
            "Select token to stake",
            [("usdc", "USDC+ Stake"), ("usdt", "USDT+ Stake")],
            default=STAKE_TOKEN_CHOICE,
        )
        if stake_token_choice == "usdc":
            print(f"  {BOLD_WHITE}Current USDC+ balance: {usdc_plus_bal:.6f}{RESET}")
        else:
            print(f"  {BOLD_WHITE}Current USDT+ balance: {usdt_plus_bal:.6f}{RESET}")
        stake_amount = _input_float("Stake amount", default=STAKE_TARGET)
    else:
        log_info("Skipping Stake operation")

    # ── 3. Send Config ──
    print(f"\n{BOLD_MAGENTA}  📌 Step 3/3: Send (Transfer Tokens){RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 70}{RESET}")
    do_send = _input_yn("Execute Send operation?")

    send_token_choice = "usdc"
    send_amount = SEND_TARGET

    if do_send:
        print(f"  {BOLD_WHITE}Target wallet: {dest_addr}{RESET}")
        print(f"  {BOLD_WHITE}Current USDC+ balance: {usdc_plus_bal:.6f}{RESET}")
        print(f"  {BOLD_WHITE}Current USDT+ balance: {usdt_plus_bal:.6f}{RESET}")
        send_token_choice = _input_choice(
            "Select token to send",
            [("usdc", "USDC+"), ("usdt", "USDT+")],
            default="usdc",
        )
        send_amount = _input_float("Send amount", default=SEND_TARGET)
        if send_token_choice == "usdc":
            if usdc_plus_bal < send_amount:
                log_warn(f"USDC+ balance may be insufficient! Need {send_amount:.2f}, currently {usdc_plus_bal:.6f}")
        else:
            if usdt_plus_bal < send_amount:
                log_warn(f"USDT+ balance may be insufficient! Need {send_amount:.2f}, currently {usdt_plus_bal:.6f}")
    else:
        log_info("Skipping Send operation")

    return (usdc_mint_count, usdc_per_tx, usdt_mint_count, usdt_per_tx,
            do_stake, stake_token_choice, stake_amount,
            do_send, send_amount, send_token_choice)


# ============================================================
# Main Logic
# ============================================================
def run(auto_mode=False):
    # ── Load wallet ──
    pk = config.load_master_key()
    if not pk:
        log_error("No private key found. Add it to master_privatekey.txt")
        log_error("  or set FUNDING_PRIVATE_KEY=0x... in .env")
        return False

    addr = private_key_to_address(pk)
    wallets = config.load_wallets()
    dest_addr = wallets[0] if wallets else None

    if not dest_addr:
        log_error("No target wallet address found. Add one to wallets.txt")
        return False

    # ── Find working RPC ──
    print_separator()
    log_task("Scanning for available RPC nodes...")
    rpc_url = find_working_rpc(SEPOLIA_RPCS)
    if not rpc_url:
        log_error("All RPC nodes are unavailable. Check your network connection.")
        return False

    # ── Query balances ──
    eth_bal = get_balance_eth(rpc_url, addr)
    usdt_bal_raw = get_token_balance(rpc_url, addr, USDT["token"])
    usdc_bal_raw = get_token_balance(rpc_url, addr, USDC["token"])
    usdt_plus_raw = get_token_balance(rpc_url, addr, USDT["plus"])
    usdc_plus_raw = get_token_balance(rpc_url, addr, USDC["plus"])
    dest_usdc_plus_raw = get_token_balance(rpc_url, dest_addr, USDC["plus"])
    dest_usdt_plus_raw = get_token_balance(rpc_url, dest_addr, USDT["plus"])

    usdt_bal = usdt_bal_raw / 10**USDT["decimals"]
    usdc_bal = usdc_bal_raw / 10**USDC["decimals"]
    usdt_plus_bal = usdt_plus_raw / 10**USDT["plus_decimals"]
    usdc_plus_bal = usdc_plus_raw / 10**USDC["plus_decimals"]

    # ── Print status ──
    print_separator()
    print(f"{BOLD_GREEN}  🔥 Sepolia All-in-One Task Runner{RESET}")
    print(f"  {BOLD_WHITE}Wallet    : {addr}{RESET}")
    print(f"  {BOLD_WHITE}ETH       : {eth_bal:.8f}{RESET}")
    print(f"  {BOLD_WHITE}USDT      : {usdt_bal:.6f}{RESET}")
    print(f"  {BOLD_WHITE}USDC      : {usdc_bal:.6f}{RESET}")
    print(f"  {BOLD_WHITE}USDT+     : {usdt_plus_bal:.6f}{RESET}")
    print(f"  {BOLD_WHITE}USDC+     : {usdc_plus_bal:.6f}{RESET}")
    print(f"  {BOLD_WHITE}Target    : {dest_addr}{RESET}")
    print(f"  {BOLD_WHITE}Target C+ : {dest_usdc_plus_raw / 10**USDC['plus_decimals']:.6f}{RESET}")
    print(f"  {BOLD_WHITE}Target T+ : {dest_usdt_plus_raw / 10**USDT['plus_decimals']:.6f}{RESET}")
    print_separator()

    # ── Configure parameters ──
    if auto_mode:
        log_info("Auto mode: using .env parameters")
        # Original auto-mode calculation logic
        if STAKE_TOKEN_CHOICE == "usdc":
            stake_cfg = USDC
            stake_token_raw = usdc_plus_raw
        else:
            stake_cfg = USDT
            stake_token_raw = usdt_plus_raw

        need_stake = max(0, STAKE_TARGET - stake_token_raw / 10**stake_cfg["plus_decimals"])
        if STAKE_TOKEN_CHOICE == "usdt":
            need_usdt_plus = max(0, MINT_TARGET + need_stake - usdt_plus_raw / 10**USDT["plus_decimals"])
        else:
            need_usdt_plus = max(0, MINT_TARGET - usdt_plus_raw / 10**USDT["plus_decimals"])
        need_usdc_plus = max(0, SEND_TARGET - usdc_plus_raw / 10**USDC["plus_decimals"])
        total_usdc_needed = need_usdc_plus + (need_stake if STAKE_TOKEN_CHOICE == "usdc" else 0)

        print(f"\n{BOLD_YELLOW}  📋 Task requirement analysis:{RESET}")
        print(f"  {BOLD_WHITE}Mint target (USDT+)  : ≥{MINT_TARGET}, need {need_usdt_plus:.2f}{RESET}")
        print(f"  {BOLD_WHITE}Stake target ({stake_cfg['plus_name']}): ≥{STAKE_TARGET}, need {need_stake:.2f}{RESET}")
        print(f"  {BOLD_WHITE}Send target (USDC+)  : ≥{SEND_TARGET}, need {need_usdc_plus:.2f}{RESET}")
        print(f"  {BOLD_WHITE}Min transaction count: {MIN_TX}{RESET}")

        stake_tx_count = 1 if need_stake > 0 else 0
        send_tx_count = 1 if SEND_TARGET > 0 else 0
        usdc_mint_per_tx = min(MINT_PER_TX, total_usdc_needed) if total_usdc_needed > 0 else MINT_PER_TX
        usdc_mint_tx = max(1, int(total_usdc_needed / usdc_mint_per_tx) + (1 if total_usdc_needed % usdc_mint_per_tx > 0 else 0)) if total_usdc_needed > 0 else 0
        usdt_mint_per_tx = min(MINT_PER_TX, need_usdt_plus) if need_usdt_plus > 0 else MINT_PER_TX
        usdt_mint_tx = max(1, int(need_usdt_plus / usdt_mint_per_tx) + (1 if need_usdt_plus % usdt_mint_per_tx > 0 else 0)) if need_usdt_plus > 0 else 0
        mint_tx_total = usdc_mint_tx + usdt_mint_tx
        tx_total = mint_tx_total + stake_tx_count + send_tx_count
        extra_tx_needed = max(0, MIN_TX - tx_total)
        if extra_tx_needed > 0:
            usdc_mint_tx += extra_tx_needed
            mint_tx_total += extra_tx_needed
            tx_total = MIN_TX

        usdc_actual_per_tx = max(usdc_mint_per_tx, total_usdc_needed / usdc_mint_tx) if usdc_mint_tx > 0 else usdc_mint_per_tx
        usdt_actual_per_tx = max(usdt_mint_per_tx, need_usdt_plus / usdt_mint_tx) if usdt_mint_tx > 0 else usdt_mint_per_tx
        usdc_actual_per_tx = round(usdc_actual_per_tx * 1.01, 6)
        usdt_actual_per_tx = round(usdt_actual_per_tx * 1.01, 6)

        do_stake = stake_tx_count > 0
        do_send = send_tx_count > 0
        stake_amount = STAKE_TARGET
        send_amount = SEND_TARGET
        send_token_choice = "usdc"
        stake_token_choice = STAKE_TOKEN_CHOICE

    else:
        # Interactive mode
        (usdc_mint_tx, usdc_actual_per_tx, usdt_mint_tx, usdt_actual_per_tx,
         do_stake, stake_token_choice, stake_amount,
         do_send, send_amount, send_token_choice) = interactive_configure(
            usdt_bal, usdc_bal, usdt_plus_bal, usdc_plus_bal, dest_addr)

        # Determine stake token config
        if stake_token_choice == "usdc":
            stake_cfg = USDC
            stake_tx_count = 1 if do_stake and stake_amount > 0 else 0
        else:
            stake_cfg = USDT
            stake_tx_count = 1 if do_stake and stake_amount > 0 else 0

        send_tx_count = 1 if do_send and send_amount > 0 else 0
        tx_total = usdc_mint_tx + usdt_mint_tx + stake_tx_count + send_tx_count

    # ── Show plan ──
    print(f"\n{BOLD_GREEN}  📊 Transaction plan:{RESET}")
    if usdc_mint_tx > 0:
        print(f"  {BOLD_WHITE}Mint USDC+ : {usdc_mint_tx} tx × ~{usdc_actual_per_tx:.2f} = ~{usdc_mint_tx * usdc_actual_per_tx:.2f} USDC+{RESET}")
    if usdt_mint_tx > 0:
        print(f"  {BOLD_WHITE}Mint USDT+ : {usdt_mint_tx} tx × ~{usdt_actual_per_tx:.2f} = ~{usdt_mint_tx * usdt_actual_per_tx:.2f} USDT+{RESET}")
    if stake_tx_count:
        print(f"  {BOLD_WHITE}Stake      : 1 tx ({stake_amount} {stake_cfg['plus_name']}){RESET}")
    if send_tx_count:
        print(f"  {BOLD_WHITE}Send {send_token_choice.upper()}+ : 1 tx ({send_amount}) → {dest_addr[:10]}...{RESET}")
    print(f"  {BOLD_GREEN}Total txs  : {tx_total}{RESET}")

    # ── Gas estimate ──
    total_gas_est = (
        usdc_mint_tx * GAS_LIMIT_MINT +
        usdt_mint_tx * GAS_LIMIT_MINT +
        stake_tx_count * GAS_LIMIT_STAKE +
        send_tx_count * GAS_LIMIT_SEND
    )
    gas_price_est = 30 * 10**9
    eth_needed = total_gas_est * gas_price_est / 10**18
    print(f"\n{BOLD_YELLOW}  ⛽ Gas estimate: ~{eth_needed:.6f} ETH ({total_gas_est:,} gas × ~30 gwei){RESET}")
    if eth_bal < eth_needed:
        log_warn(f"ETH balance may be insufficient! Need ~{eth_needed:.6f} ETH, currently {eth_bal:.8f} ETH")

    # Balance check
    if usdt_mint_tx > 0 and usdt_bal_raw < usdt_mint_tx * usdt_actual_per_tx * 10**USDT["decimals"]:
        log_error(f"Insufficient USDT balance! Need {usdt_mint_tx * usdt_actual_per_tx:.2f} USDT")
        return False
    if usdc_mint_tx > 0 and usdc_bal_raw < usdc_mint_tx * usdc_actual_per_tx * 10**USDC["decimals"]:
        log_error(f"Insufficient USDC balance! Need {usdc_mint_tx * usdc_actual_per_tx:.2f} USDC")
        return False

    # ── Pre-flight balance check (accounts for mint production) ──
    # Compute post-mint balances (mints run first in execution)
    post_mint_usdc_plus = usdc_plus_bal + (usdc_mint_tx * usdc_actual_per_tx)
    post_mint_usdt_plus = usdt_plus_bal + (usdt_mint_tx * usdt_actual_per_tx)

    balance_issues = []
    resolved_by_mint = []

    if stake_tx_count:
        stake_current_bal = usdt_plus_bal if stake_token_choice == "usdt" else usdc_plus_bal
        stake_check_bal = post_mint_usdt_plus if stake_token_choice == "usdt" else post_mint_usdc_plus
        if stake_amount > stake_check_bal:
            shortfall = stake_amount - stake_check_bal
            balance_issues.append(
                f"Stake: requested {stake_amount} {stake_cfg['plus_name']} but will only have {stake_check_bal:.6f} after mint (short by {shortfall:.6f})"
            )
        elif stake_amount > stake_current_bal:
            resolved_by_mint.append(
                f"Stake: needs {stake_amount} {stake_cfg['plus_name']} — will be covered by mint (current: {stake_current_bal:.6f} → after mint: {stake_check_bal:.6f})"
            )

    if send_tx_count:
        send_current_bal = usdt_plus_bal if send_token_choice == "usdt" else usdc_plus_bal
        send_check_bal = post_mint_usdt_plus if send_token_choice == "usdt" else post_mint_usdc_plus
        if send_amount > send_check_bal:
            shortfall = send_amount - send_check_bal
            balance_issues.append(
                f"Send: requested {send_amount} {send_token_choice.upper()}+ but will only have {send_check_bal:.6f} after mint (short by {shortfall:.6f})"
            )
        elif send_amount > send_current_bal:
            resolved_by_mint.append(
                f"Send: needs {send_amount} {send_token_choice.upper()}+ — will be covered by mint (current: {send_current_bal:.6f} → after mint: {send_check_bal:.6f})"
            )

    if resolved_by_mint:
        print(f"\n{BOLD_GREEN}  ✓ BALANCE RESOLVED — mint will provide needed tokens:{RESET}")
        for item in resolved_by_mint:
            print(f"  {BOLD_GREEN}    • {item}{RESET}")

    if balance_issues:
        print(f"\n{BOLD_RED}  ⚠️  BALANCE WARNING — even after mint, amounts still exceed balance:{RESET}")
        for issue in balance_issues:
            print(f"  {BOLD_RED}    • {issue}{RESET}")
        print(f"  {BOLD_YELLOW}    You'll be asked whether to use all available when that step is reached.{RESET}")

    # ── Confirm ──
    if tx_total == 0:
        log_info("No tasks to execute, exiting")
        return True

    print()
    if auto_mode:
        confirm = input(f"  {BOLD_WHITE}Confirm execution of all tasks? (y/n): {RESET}").strip().lower()
        if confirm not in ("y", "yes"):
            log_info("Execution cancelled")
            return False
    else:
        if not _input_yn("Confirm execution of all tasks above?"):
            log_info("Execution cancelled")
            return False

    # ============================================================
    # Execution Phase (mints first → stake → send)
    # ============================================================
    tx_count = 0
    ok_count = 0
    fail_count = 0

    # ── Mint USDC+ ──
    if usdc_mint_tx > 0:
        print_header(f"Mint USDC → USDC+ ({usdc_mint_tx} tx)")

        usdc_mint_cd = build_mint_calldata(
            addr, addr,
            USDC["token"],
            int(usdc_actual_per_tx * 10**USDC["decimals"]),
            int(usdc_actual_per_tx * 10**USDC["decimals"]) * 10**(USDC["plus_decimals"] - USDC["decimals"]),
        )

        for i in range(1, usdc_mint_tx + 1):
            log_task(f"[{tx_count + 1}/{tx_total}] Mint USDC+ {i}/{usdc_mint_tx} | {usdc_actual_per_tx:.2f} USDC → USDC+")

            result = send_transaction(
                rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER, chain_id=SEPOLIA_CHAIN_ID,
                pk=pk, address=addr, to_contract=USDC["plus"], value_wei=0,
                calldata=usdc_mint_cd, action_name=f"Mint USDC+ #{i}/{usdc_mint_tx}",
                gas_limit_override=GAS_LIMIT_MINT, proxy=None,
            )

            tx_count += 1
            if result and result not in ("FAILED", "INSUFFICIENT", None):
                ok_count += 1
                log_success(f"✓ Mint USDC+ #{i} complete")
            else:
                fail_count += 1
                log_error(f"✗ Mint USDC+ #{i} failed: {result}")
                if result == "INSUFFICIENT":
                    log_error("Insufficient ETH for gas, stopping")
                    break

            if i < usdc_mint_tx:
                delay = random.uniform(DELAY_MIN, DELAY_MAX)
                log_info(f"Waiting {delay:.1f}s...")
                time.sleep(delay)

    # ── Mint USDT+ ──
    if usdt_mint_tx > 0:
        print_header(f"Mint USDT → USDT+ ({usdt_mint_tx} tx)")

        usdt_mint_cd = build_mint_calldata(
            addr, addr,
            USDT["token"],
            int(usdt_actual_per_tx * 10**USDT["decimals"]),
            int(usdt_actual_per_tx * 10**USDT["decimals"]) * 10**(USDT["plus_decimals"] - USDT["decimals"]),
        )

        for i in range(1, usdt_mint_tx + 1):
            log_task(f"[{tx_count + 1}/{tx_total}] Mint USDT+ {i}/{usdt_mint_tx} | {usdt_actual_per_tx:.2f} USDT → USDT+")

            result = send_transaction(
                rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER, chain_id=SEPOLIA_CHAIN_ID,
                pk=pk, address=addr, to_contract=USDT["plus"], value_wei=0,
                calldata=usdt_mint_cd, action_name=f"Mint USDT+ #{i}/{usdt_mint_tx}",
                gas_limit_override=GAS_LIMIT_MINT, proxy=None,
            )

            tx_count += 1
            if result and result not in ("FAILED", "INSUFFICIENT", None):
                ok_count += 1
                log_success(f"✓ Mint USDT+ #{i} complete")
            else:
                fail_count += 1
                log_error(f"✗ Mint USDT+ #{i} failed: {result}")
                if result == "INSUFFICIENT":
                    log_error("Insufficient ETH for gas, stopping")
                    break

            if i < usdt_mint_tx:
                delay = random.uniform(DELAY_MIN, DELAY_MAX)
                log_info(f"Waiting {delay:.1f}s...")
                time.sleep(delay)

    # ── Stake ──
    if stake_tx_count > 0:
        print_header(f"Stake {stake_cfg['plus_name']}")

        stake_now_raw = get_token_balance(rpc_url, addr, stake_cfg["plus"])
        stake_now = stake_now_raw / 10**stake_cfg["plus_decimals"]
        actual_stake = stake_amount

        if stake_now < stake_amount:
            shortfall = stake_amount - stake_now
            log_warn(f"Stake token balance insufficient! Requested {stake_amount}, only have {stake_now:.6f} (short by {shortfall:.6f})")

            # Check if we can auto-mint to cover the shortfall
            base_cfg = USDT if stake_token_choice == "usdt" else USDC
            base_raw = get_token_balance(rpc_url, addr, base_cfg["token"])
            base_bal = base_raw / 10**base_cfg["decimals"]
            can_mint = base_bal >= shortfall

            if not auto_mode and can_mint:
                print(f"\n  {BOLD_YELLOW}Options:{RESET}")
                print(f"    {BOLD_WHITE}[1] Stake all available ({stake_now:.6f} {stake_cfg['plus_name']}){RESET}")
                print(f"    {BOLD_WHITE}[2] Auto-mint {shortfall:.6f} {stake_cfg['plus_name']} to cover → then stake full {stake_amount:.6f}{RESET}")
                print(f"    {BOLD_WHITE}[3] Skip stake{RESET}")
                choice = input(f"  {BOLD_WHITE}Choose (1/2/3) [default 2]: {RESET}").strip()
                if choice == "1":
                    actual_stake = stake_now
                elif choice == "3":
                    log_info("Stake skipped by user")
                    actual_stake = 0
                else:
                    # Auto-mint to cover shortfall
                    mint_count = max(1, int(shortfall / MINT_PER_TX) + (1 if shortfall % MINT_PER_TX > 0 else 0))
                    per_tx = shortfall / mint_count
                    log_task(f"Auto-minting {shortfall:.6f} {base_cfg['name']} → {stake_cfg['plus_name']} ({mint_count} tx)")
                    tx_total += mint_count
                    for mi in range(1, mint_count + 1):
                        tk_raw = int(per_tx * 10**base_cfg["decimals"])
                        pl_raw = tk_raw * 10**(base_cfg["plus_decimals"] - base_cfg["decimals"])
                        mint_cd = build_mint_calldata(addr, addr, base_cfg["token"], tk_raw, pl_raw)
                        log_task(f"  Auto-mint {mi}/{mint_count} | {per_tx:.2f} {base_cfg['name']} → {stake_cfg['plus_name']}")
                        result = send_transaction(
                            rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER, chain_id=SEPOLIA_CHAIN_ID,
                            pk=pk, address=addr, to_contract=base_cfg["plus"], value_wei=0,
                            calldata=mint_cd, action_name=f"Auto-mint #{mi} ({per_tx:.2f} {base_cfg['name']})",
                            gas_limit_override=GAS_LIMIT_MINT, proxy=None)
                        tx_count += 1
                        if result and result not in ("FAILED", "INSUFFICIENT", None):
                            ok_count += 1
                            log_success(f"  ✓ Auto-mint #{mi} complete")
                        else:
                            fail_count += 1
                            log_error(f"  ✗ Auto-mint #{mi} failed: {result}")
                            if result == "INSUFFICIENT":
                                log_error("Insufficient ETH for gas, stopping")
                                break
                        if mi < mint_count:
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                    # Re-check balance after auto-mint (in case it partially failed)
                    stake_now_raw = get_token_balance(rpc_url, addr, stake_cfg["plus"])
                    stake_now = stake_now_raw / 10**stake_cfg["plus_decimals"]
                    actual_stake = min(stake_amount, stake_now)
                    if actual_stake < stake_amount:
                        log_warn(f"After auto-mint, balance is {stake_now:.6f} (short by {stake_amount - stake_now:.6f}), will stake {actual_stake:.6f}")
            elif not auto_mode:
                if not _input_yn(f"Stake all available ({stake_now:.6f} {stake_cfg['plus_name']}) instead?", default="y"):
                    log_info("Stake skipped by user")
                    actual_stake = 0
                else:
                    actual_stake = stake_now
            else:
                log_warn(f"Auto mode: staking all available ({stake_now:.6f})")
                actual_stake = stake_now

        if actual_stake <= 0:
            log_error("Stake token balance is 0, skipping stake")
        else:
            stake_amount_raw = int(actual_stake * 10**stake_cfg["plus_decimals"])
            stake_cd = build_stake_calldata(stake_amount_raw, addr)

            log_task(f"[{tx_count + 1}/{tx_total}] Stake {actual_stake:.6f} {stake_cfg['plus_name']}")

            result = send_transaction(
                rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER, chain_id=SEPOLIA_CHAIN_ID,
                pk=pk, address=addr, to_contract=stake_cfg["stake_contract"], value_wei=0,
                calldata=stake_cd, action_name=f"Stake {actual_stake:.6f} {stake_cfg['plus_name']}",
                gas_limit_override=GAS_LIMIT_STAKE, proxy=None,
            )

            tx_count += 1
            if result and result not in ("FAILED", "INSUFFICIENT", None):
                ok_count += 1
                log_success(f"✓ Stake complete")
            else:
                fail_count += 1
                log_error(f"✗ Stake failed: {result}")
                if result == "INSUFFICIENT":
                    log_error("Insufficient ETH for gas, stopping")

    # ── Send ──
    if send_tx_count > 0:
        print_header(f"Send {send_token_choice.upper()}+ → {dest_addr[:10]}...")

        if send_token_choice == "usdc":
            send_cfg = USDC
        else:
            send_cfg = USDT

        send_now_raw = get_token_balance(rpc_url, addr, send_cfg["plus"])
        send_now = send_now_raw / 10**send_cfg["plus_decimals"]
        actual_send = send_amount

        if send_now < send_amount:
            shortfall = send_amount - send_now
            log_warn(f"{send_cfg['plus_name']} balance insufficient! Requested {send_amount}, only have {send_now:.6f} (short by {shortfall:.6f})")

            # Check if we can auto-mint to cover the shortfall
            base_cfg = USDT if send_token_choice == "usdt" else USDC
            base_raw = get_token_balance(rpc_url, addr, base_cfg["token"])
            base_bal = base_raw / 10**base_cfg["decimals"]
            can_mint = base_bal >= shortfall

            if not auto_mode and can_mint:
                print(f"\n  {BOLD_YELLOW}Options:{RESET}")
                print(f"    {BOLD_WHITE}[1] Send all available ({send_now:.6f} {send_cfg['plus_name']}){RESET}")
                print(f"    {BOLD_WHITE}[2] Auto-mint {shortfall:.6f} {send_cfg['plus_name']} to cover → then send full {send_amount:.6f}{RESET}")
                print(f"    {BOLD_WHITE}[3] Skip send{RESET}")
                choice = input(f"  {BOLD_WHITE}Choose (1/2/3) [default 2]: {RESET}").strip()
                if choice == "1":
                    actual_send = send_now
                elif choice == "3":
                    log_info("Send skipped by user")
                    actual_send = 0
                else:
                    # Auto-mint to cover shortfall
                    mint_count = max(1, int(shortfall / MINT_PER_TX) + (1 if shortfall % MINT_PER_TX > 0 else 0))
                    per_tx = shortfall / mint_count
                    log_task(f"Auto-minting {shortfall:.6f} {base_cfg['name']} → {send_cfg['plus_name']} ({mint_count} tx)")
                    tx_total += mint_count
                    for mi in range(1, mint_count + 1):
                        tk_raw = int(per_tx * 10**base_cfg["decimals"])
                        pl_raw = tk_raw * 10**(base_cfg["plus_decimals"] - base_cfg["decimals"])
                        mint_cd = build_mint_calldata(addr, addr, base_cfg["token"], tk_raw, pl_raw)
                        log_task(f"  Auto-mint {mi}/{mint_count} | {per_tx:.2f} {base_cfg['name']} → {send_cfg['plus_name']}")
                        result = send_transaction(
                            rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER, chain_id=SEPOLIA_CHAIN_ID,
                            pk=pk, address=addr, to_contract=base_cfg["plus"], value_wei=0,
                            calldata=mint_cd, action_name=f"Auto-mint #{mi} ({per_tx:.2f} {base_cfg['name']})",
                            gas_limit_override=GAS_LIMIT_MINT, proxy=None)
                        tx_count += 1
                        if result and result not in ("FAILED", "INSUFFICIENT", None):
                            ok_count += 1
                            log_success(f"  ✓ Auto-mint #{mi} complete")
                        else:
                            fail_count += 1
                            log_error(f"  ✗ Auto-mint #{mi} failed: {result}")
                            if result == "INSUFFICIENT":
                                log_error("Insufficient ETH for gas, stopping")
                                break
                        if mi < mint_count:
                            time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
                    # Re-check balance after auto-mint (in case it partially failed)
                    send_now_raw = get_token_balance(rpc_url, addr, send_cfg["plus"])
                    send_now = send_now_raw / 10**send_cfg["plus_decimals"]
                    actual_send = min(send_amount, send_now)
                    if actual_send < send_amount:
                        log_warn(f"After auto-mint, balance is {send_now:.6f} (short by {send_amount - send_now:.6f}), will send {actual_send:.6f}")
            elif not auto_mode:
                if not _input_yn(f"Send all available ({send_now:.6f} {send_cfg['plus_name']}) instead?", default="y"):
                    log_info("Send skipped by user")
                    actual_send = 0
                else:
                    actual_send = send_now
            else:
                log_warn(f"Auto mode: sending all available ({send_now:.6f})")
                actual_send = send_now

        if actual_send <= 0:
            log_error(f"{send_cfg['plus_name']} balance is 0, skipping send")
        else:
            send_amount_raw = int(actual_send * 10**send_cfg["plus_decimals"])
            send_cd = build_send_calldata(dest_addr, send_amount_raw)

            log_task(f"[{tx_count + 1}/{tx_total}] Send {actual_send:.6f} {send_cfg['plus_name']} → {dest_addr[:10]}...")

            result = send_transaction(
                rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER, chain_id=SEPOLIA_CHAIN_ID,
                pk=pk, address=addr, to_contract=send_cfg["plus"], value_wei=0,
                calldata=send_cd, action_name=f"Send {actual_send:.6f} {send_cfg['plus_name']}",
                gas_limit_override=GAS_LIMIT_SEND, proxy=None,
            )

            tx_count += 1
            if result and result not in ("FAILED", "INSUFFICIENT", None):
                ok_count += 1
                log_success(f"✓ Send {send_cfg['plus_name']} complete")
            else:
                fail_count += 1
                log_error(f"✗ Send {send_cfg['plus_name']} failed: {result}")
                if result == "INSUFFICIENT":
                    log_error("Insufficient ETH for gas, stopping")

    # ── Final report ──
    print_separator("=")
    print(f"{BOLD_GREEN}  🎉 All tasks complete!{RESET}")
    print(f"  {BOLD_WHITE}Total txs : {tx_count}{RESET}")
    print(f"  {BOLD_GREEN}Success   : {ok_count}{RESET}")
    if fail_count:
        print(f"  {BOLD_RED}Failed    : {fail_count}{RESET}")
    print()

    final_eth = get_balance_eth(rpc_url, addr)
    final_usdt = get_token_balance(rpc_url, addr, USDT["token"]) / 10**USDT["decimals"]
    final_usdc = get_token_balance(rpc_url, addr, USDC["token"]) / 10**USDC["decimals"]
    final_usdt_plus = get_token_balance(rpc_url, addr, USDT["plus"]) / 10**USDT["plus_decimals"]
    final_usdc_plus = get_token_balance(rpc_url, addr, USDC["plus"]) / 10**USDC["plus_decimals"]
    final_dest_c = get_token_balance(rpc_url, dest_addr, USDC["plus"]) / 10**USDC["plus_decimals"]
    final_dest_t = get_token_balance(rpc_url, dest_addr, USDT["plus"]) / 10**USDT["plus_decimals"]

    print(f"{BOLD_CYAN}  📊 Final balances:{RESET}")
    print(f"  {BOLD_WHITE}ETH     : {final_eth:.8f}{RESET}")
    print(f"  {BOLD_WHITE}USDT    : {final_usdt:.6f}{RESET}")
    print(f"  {BOLD_WHITE}USDC    : {final_usdc:.6f}{RESET}")
    print(f"  {BOLD_WHITE}USDT+   : {final_usdt_plus:.6f}{RESET}")
    print(f"  {BOLD_WHITE}USDC+   : {final_usdc_plus:.6f}{RESET}")
    print(f"  {BOLD_WHITE}Target C+: {final_dest_c:.6f}{RESET}")
    print(f"  {BOLD_WHITE}Target T+: {final_dest_t:.6f}{RESET}")
    print_separator("=")

    return fail_count == 0


def main():
    parser = argparse.ArgumentParser(
        description="Sepolia All-in-One Task Runner — Mint + Stake + Send"
    )
    parser.add_argument("--auto", action="store_true",
                        help="Auto mode: use .env params, no interactive prompts")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Same as --auto")
    args = parser.parse_args()

    auto_mode = args.auto or args.yes

    banner()
    print(f"  {BOLD_WHITE}Network : Sepolia Testnet (Chain ID {SEPOLIA_CHAIN_ID}){RESET}")
    print(f"  {BOLD_WHITE}Features: All-in-One (Mint + Stake + Send){RESET}")
    if auto_mode:
        print(f"  {BOLD_GREEN}Mode    : Auto (.env params){RESET}\n")
    else:
        print(f"  {BOLD_YELLOW}Mode    : Interactive (prompts at each step){RESET}")
        print(f"  {BOLD_YELLOW}Tip     : Use --auto / -y to skip prompts{RESET}\n")

    success = run(auto_mode=auto_mode)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
