"""
Daily Mission Runner - Ethereum Sepolia
=======================================
A beginner-friendly interactive script that guides you through
completing daily missions on the Sepolia Testnet.

Missions supported:
  1. Mint    - Convert USDT/USDC into USDT+/USDC+
  2. Stake   - Lock USDT+/USDC+ in staking contracts
  3. Send    - Transfer USDT+/USDC+ to your target wallet
  4. Receive - Target wallet receives tokens (auto-completed with Send)
  5. Daily TX - Ensure minimum transaction count

How to use:
  python daily_missions.py

The script will ask you questions based on today's mission format:
  "Mint at least 244 USDT+ on ETH Sep"
  "Stake at least 447 USDC+ on ETH Sep"
  "Send at least 250 USDC+ on ETH Sep"
  "Receive at least 316 USDC+ on ETH Sep"
  "Make at least 11 tx (mint, stake, or bridge) on ETH Sep"

Check your daily missions at: https://testnet.overlayer.fi/early-user
"""

import json
import math
import os
import random
import sys
import time
import webbrowser

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from contract_encoder import p32
from utils.crypto import private_key_to_address
from utils.display import (
    BOLD_CYAN, BOLD_GREEN, BOLD_WHITE, BOLD_YELLOW, BOLD_MAGENTA, BOLD_RED, DIM, RESET,
    banner, log_error, log_info, log_success, log_task, log_warn,
)
from utils.rpc import find_working_rpc, get_balance_eth, rpc_call, send_transaction

# ═══════════════════════════════════════════════════════════════════
# Network Config - Sepolia Testnet
# ═══════════════════════════════════════════════════════════════════

SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_EXPLORER = "https://sepolia.etherscan.io"

RPC_ENDPOINTS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://rpc.sepolia.org",
    "https://sepolia.drpc.org",
    "https://eth-sepolia.g.alchemy.com/v2/demo",
]

# ═══════════════════════════════════════════════════════════════════
# Token & Contract Addresses (Sepolia)
# ═══════════════════════════════════════════════════════════════════

TOKENS = {
    "usdt": {
        "name": "USDT",
        "plus_name": "USDT+",
        "token": "0xaa8e23fb1079ea71e0a56f48a2aa51851d8433d0",
        "plus": "0xe20534a32f9162488a90026F268a74fBE28d272D",
        "stake_contract": "0x079a4Bf1Cbd0E4ce15391340cB46efA6396aBc82",
        "decimals": 6,
        "plus_decimals": 18,
    },
    "usdc": {
        "name": "USDC",
        "plus_name": "USDC+",
        "token": "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8",
        "plus": "0xE815718D44694ec4637CB775C468d87f6e15B538",
        "stake_contract": "0x753937137eb92871A6f3517514d4f1ee860E3fDF",
        "decimals": 6,
        "plus_decimals": 18,
    },
}

# ═══════════════════════════════════════════════════════════════════
# Contract Function Selectors
# ═══════════════════════════════════════════════════════════════════

MINT_SELECTOR     = "2ef6f1ab"   # mint(tuple(address,address,address,uint256,uint256))
DEPOSIT_SELECTOR  = "6e553f65"   # deposit(uint256 assets, address receiver)
TRANSFER_SELECTOR = "a9059cbb"   # transfer(address to, uint256 amount)
BALANCE_SELECTOR  = "70a08231"   # balanceOf(address)

# ═══════════════════════════════════════════════════════════════════
# Default Settings
# ═══════════════════════════════════════════════════════════════════

DEFAULTS = {
    "max_mint_per_tx": 500,   # Cap per mint to avoid reverts
    "daily_tx_amount": 1.0,   # Amount per filler mint for daily TX count
    "delay_min": 4,           # Min seconds between transactions
    "delay_max": 10,          # Max seconds between transactions
    "save_config": True,      # Auto-save last config
}

CONFIG_FILE = "last_missions.json"

# ═══════════════════════════════════════════════════════════════════
# Interactive Input Helpers
# ═══════════════════════════════════════════════════════════════════

def _clear():
    """Clear terminal screen."""
    if not os.getenv("NO_CLEAR"):
        os.system("cls" if os.name == "nt" else "clear")


def _ask_number(prompt, default=None, min_val=0):
    """Ask user for a number with validation."""
    hint = f" (default: {default})" if default is not None else ""
    while True:
        try:
            raw = input(f"  {BOLD_WHITE}{prompt}{hint}: {RESET}").strip()
            if not raw and default is not None:
                return float(default)
            val = float(raw)
            if val < min_val:
                log_error(f"Value must be at least {min_val}")
                continue
            return val
        except (ValueError, EOFError):
            log_error("Please enter a valid number")


def _ask_int(prompt, default=None, min_val=1):
    """Ask user for an integer with validation."""
    hint = f" (default: {default})" if default is not None else ""
    while True:
        try:
            raw = input(f"  {BOLD_WHITE}{prompt}{hint}: {RESET}").strip()
            if not raw and default is not None:
                return int(default)
            val = int(raw)
            if val < min_val:
                log_error(f"Value must be at least {min_val}")
                continue
            return val
        except (ValueError, EOFError):
            log_error("Please enter a valid integer")


def _ask_token(prompt, default="usdc"):
    """Ask user to choose a token (USDT or USDC)."""
    print(f"  {BOLD_WHITE}{prompt}:{RESET}")
    usdt_label = "USDT / USDT+"
    usdc_label = "USDC / USDC+"
    d1 = " (default)" if default == "usdt" else ""
    d2 = " (default)" if default == "usdc" else ""
    print(f"    {BOLD_CYAN}[1]{RESET} {usdt_label}{d1}")
    print(f"    {BOLD_CYAN}[2]{RESET} {usdc_label}{d2}")
    while True:
        raw = input(f"  {BOLD_WHITE}Choose (1 or 2){RESET}: ").strip()
        if not raw:
            return default
        if raw == "1":
            return "usdt"
        if raw == "2":
            return "usdc"
        log_error("Please enter 1 (USDT) or 2 (USDC)")


def _ask_yesno(prompt, default="y"):
    """Ask a yes/no question."""
    yn = "Y/n" if default == "y" else "y/N"
    while True:
        raw = input(f"  {BOLD_WHITE}{prompt} ({yn}): {RESET}").strip().lower()
        if not raw:
            return default == "y"
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        log_error("Please enter 'y' or 'n'")





# ═══════════════════════════════════════════════════════════════════
# Blockchain Helpers
# ═══════════════════════════════════════════════════════════════════

def get_token_balance(rpc_url, address, token_addr):
    """Query ERC-20 token balance."""
    padded = p32(int(address.lower().replace("0x", ""), 16))
    cd = "0x" + BALANCE_SELECTOR + padded
    result = rpc_call(rpc_url, "eth_call", [{"to": token_addr, "data": cd}, "latest"])
    if result and "result" in result:
        return int(result["result"], 16)
    return 0


def build_mint_calldata(caller, receiver, token, token_raw, plus_raw):
    """Encode mint(address,address,address,uint256,uint256)."""
    parts = [MINT_SELECTOR]
    parts.append(p32(int(caller.lower().replace("0x", ""), 16)))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    parts.append(p32(int(token.lower().replace("0x", ""), 16)))
    parts.append(p32(token_raw))
    parts.append(p32(plus_raw))
    return "0x" + "".join(parts)


def build_stake_calldata(amount_raw, receiver):
    """Encode deposit(uint256, address)."""
    parts = [DEPOSIT_SELECTOR]
    parts.append(p32(amount_raw))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    return "0x" + "".join(parts)


def build_send_calldata(recipient, amount_raw):
    """Encode transfer(address, uint256)."""
    parts = [TRANSFER_SELECTOR]
    parts.append(p32(int(recipient.lower().replace("0x", ""), 16)))
    parts.append(p32(amount_raw))
    return "0x" + "".join(parts)


# ═══════════════════════════════════════════════════════════════════
# Config Save/Load
# ═══════════════════════════════════════════════════════════════════

def save_config(missions_dict):
    """Save mission config for next run."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(missions_dict, f, indent=2)
        log_info(f"Config saved to {CONFIG_FILE}")
    except Exception as e:
        log_warn(f"Could not save config: {e}")


def load_config():
    """Load previously saved mission config."""
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
# Mission Configuration Wizard
# ═══════════════════════════════════════════════════════════════════

def mission_wizard():
    """
    Interactive wizard that collects today's mission requirements.
    Mirrors the daily mission format from testnet.overlayer.fi/early-user.
    """
    banner("Daily Mission Setup")

    print(f"\n{BOLD_GREEN}  Welcome! Let's set up today's missions.{RESET}")
    print(f"  {BOLD_YELLOW}Check your missions at: https://testnet.overlayer.fi/early-user{RESET}")
    print()
    print(f"  {BOLD_WHITE}Today's missions look like this:{RESET}")
    print(f"  {DIM}  'Mint at least 244 USDT+ on ETH Sep'{RESET}")
    print(f"  {DIM}  'Stake at least 447 USDC+ on ETH Sep'{RESET}")
    print(f"  {DIM}  'Send at least 250 USDC+ on ETH Sep'{RESET}")
    print(f"  {DIM}  'Receive at least 316 USDC+ on ETH Sep'{RESET}")
    print(f"  {DIM}  'Make at least 11 tx (mint, stake, or bridge) on ETH Sep'{RESET}")
    print()

    # Check for saved config
    saved = load_config()
    use_saved = False
    if saved:
        print(f"  {BOLD_YELLOW}Found saved config from last run!{RESET}")
        for m in saved.get("missions", []):
            print(f"    - {m.get('label', str(m))}")
        use_saved = _ask_yesno("Use this saved config?", "y")

    if use_saved and saved:
        missions = saved.get("missions", [])
        settings = {**DEFAULTS, **saved.get("settings", {})}
        return missions, settings

    missions = []
    settings = dict(DEFAULTS)

    # ── Step 1: Mint Mission ──
    print(f"\n{BOLD_MAGENTA}{'─' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}Step 1/5: MINT Mission{RESET}")
    print(f"  {BOLD_WHITE}(Example: 'Mint at least 244 USDT+ on ETH Sep'){RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 60}{RESET}")

    if _ask_yesno("Do you have a MINT mission today?", "y"):
        token = _ask_token("Which token to mint")
        cfg = TOKENS[token]
        amount = _ask_number(f"Minimum {cfg['plus_name']} to mint", min_val=0.01)
        missions.append({
            "type": "mint",
            "token": token,
            "amount": amount,
            "label": f"Mint >= {amount} {cfg['plus_name']}",
        })
        print(f"  {BOLD_GREEN}  + Added: Mint {amount} {cfg['plus_name']}{RESET}")
    else:
        log_info("Skipped Mint mission")

    # ── Step 2: Stake Mission ──
    print(f"\n{BOLD_MAGENTA}{'─' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}Step 2/5: STAKE Mission{RESET}")
    print(f"  {BOLD_WHITE}(Example: 'Stake at least 447 USDC+ on ETH Sep'){RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 60}{RESET}")

    if _ask_yesno("Do you have a STAKE mission today?", "y"):
        token = _ask_token("Which token to stake")
        cfg = TOKENS[token]
        amount = _ask_number(f"Minimum {cfg['plus_name']} to stake", min_val=0.01)
        missions.append({
            "type": "stake",
            "token": token,
            "amount": amount,
            "label": f"Stake >= {amount} {cfg['plus_name']}",
        })
        print(f"  {BOLD_GREEN}  + Added: Stake {amount} {cfg['plus_name']}{RESET}")
    else:
        log_info("Skipped Stake mission")

    # ── Step 3: Send Mission ──
    print(f"\n{BOLD_MAGENTA}{'─' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}Step 3/5: SEND Mission{RESET}")
    print(f"  {BOLD_WHITE}(Example: 'Send at least 250 USDC+ on ETH Sep'){RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 60}{RESET}")

    if _ask_yesno("Do you have a SEND mission today?", "y"):
        token = _ask_token("Which token to send")
        cfg = TOKENS[token]
        amount = _ask_number(f"Minimum {cfg['plus_name']} to send", min_val=0.01)
        missions.append({
            "type": "send",
            "token": token,
            "amount": amount,
            "label": f"Send >= {amount} {cfg['plus_name']}",
        })
        print(f"  {BOLD_GREEN}  + Added: Send {amount} {cfg['plus_name']}{RESET}")
    else:
        log_info("Skipped Send mission")

    # ── Step 4: Receive Mission ──
    print(f"\n{BOLD_MAGENTA}{'─' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}Step 4/5: RECEIVE Mission{RESET}")
    print(f"  {BOLD_WHITE}(Example: 'Receive at least 316 USDC+ on ETH Sep'){RESET}")
    print(f"  {DIM}Note: Receive is auto-completed by sending to your target wallet.{RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 60}{RESET}")

    if _ask_yesno("Do you have a RECEIVE mission today?", "n"):
        token = _ask_token("Which token to receive")
        cfg = TOKENS[token]
        amount = _ask_number(f"Minimum {cfg['plus_name']} to receive", min_val=0.01)
        missions.append({
            "type": "receive",
            "token": token,
            "amount": amount,
            "label": f"Receive >= {amount} {cfg['plus_name']}",
        })
        print(f"  {BOLD_GREEN}  + Added: Receive {amount} {cfg['plus_name']}{RESET}")
    else:
        log_info("Skipped Receive mission")

    # ── Step 5: Daily TX Mission ──
    print(f"\n{BOLD_MAGENTA}{'─' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}Step 5/5: DAILY TRANSACTIONS Mission{RESET}")
    print(f"  {BOLD_WHITE}(Example: 'Make at least 11 tx on ETH Sep'){RESET}")
    print(f"  {DIM}Note: If needed, small filler mint txs will be added to reach the count.{RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 60}{RESET}")

    if _ask_yesno("Do you have a DAILY TX mission today?", "y"):
        min_tx = _ask_int("Minimum transaction count", default=11)
        settings["daily_tx_amount"] = _ask_number(
            "Amount per filler mint (small: 1.0 USDT/USDC)",
            default=DEFAULTS["daily_tx_amount"], min_val=0.01
        )
        missions.append({
            "type": "daily_tx",
            "min_count": min_tx,
            "label": f">= {min_tx} daily transactions",
        })
        print(f"  {BOLD_GREEN}  + Added: >= {min_tx} daily transactions (filler: {settings['daily_tx_amount']}/tx){RESET}")
    else:
        log_info("Skipped Daily TX mission")

    # ── Advanced Settings ──
    print(f"\n{BOLD_MAGENTA}{'─' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}Advanced Settings (press Enter for defaults){RESET}")
    print(f"{BOLD_MAGENTA}{'─' * 60}{RESET}")

    settings["delay_min"] = _ask_number(
        "Min delay between transactions (seconds)", default=DEFAULTS["delay_min"], min_val=1
    )
    settings["delay_max"] = _ask_number(
        "Max delay between transactions (seconds)", default=DEFAULTS["delay_max"], min_val=1
    )
    if settings["delay_max"] < settings["delay_min"]:
        settings["delay_max"] = settings["delay_min"] + 1

    # ── Summary ──
    print(f"\n{BOLD_GREEN}{'=' * 60}{RESET}")
    print(f"  {BOLD_GREEN}Mission Summary:{RESET}")
    for i, m in enumerate(missions, 1):
        print(f"    {i}. {m['label']}")
    print(f"{BOLD_GREEN}{'=' * 60}{RESET}\n")

    if settings.get("save_config", True):
        save_config({"missions": missions, "settings": settings})

    return missions, settings


# ═══════════════════════════════════════════════════════════════════
# Mission Analysis & Planning
# ═══════════════════════════════════════════════════════════════════

def analyze_and_plan(missions, settings, balances):
    """
    Analyze missions and create an optimal execution plan.

    Smart features:
      - Send + Receive are merged (sending X satisfies both)
      - Mint missions run as a single transaction (or split if > max_mint_per_tx)
      - Small filler mints (separate from mint missions) added for daily TX count
    """
    # Group missions by type
    mint_targets  = {}
    stake_needs   = {}
    send_needs    = {}
    receive_needs = {}
    min_tx_count  = 0

    for m in missions:
        mtype = m["type"]
        token = m.get("token", "usdc")
        if mtype == "mint":
            mint_targets[token] = mint_targets.get(token, 0) + m.get("amount", 0)
        elif mtype == "stake":
            stake_needs[token] = stake_needs.get(token, 0) + m.get("amount", 0)
        elif mtype == "send":
            send_needs[token] = send_needs.get(token, 0) + m.get("amount", 0)
        elif mtype == "receive":
            receive_needs[token] = receive_needs.get(token, 0) + m.get("amount", 0)
        elif mtype == "daily_tx":
            min_tx_count = max(min_tx_count, m.get("min_count", 0))

    # Merge Send + Receive: sending X satisfies both
    effective_send = {}
    all_tokens = set(list(send_needs.keys()) + list(receive_needs.keys()))
    for token in all_tokens:
        effective_send[token] = max(send_needs.get(token, 0), receive_needs.get(token, 0))

    # Calculate mint requirements (mint ONLY the mint_target — not inflated by stake/send)
    max_mint = DEFAULTS["max_mint_per_tx"]
    plan_mints = {}

    for token in ["usdt", "usdc"]:
        plus_key = f"{token}_plus"
        existing = balances.get(plus_key, 0)
        target = mint_targets.get(token, 0)

        # Always mint the full target — the mint mission requires actually
        # performing the mint transaction, not just having the balance.
        mint_amount = target

        if mint_amount > 0:
            if mint_amount > max_mint:
                tx_needed = max(1, math.ceil(mint_amount / max_mint))
                per_tx = mint_amount / tx_needed
            else:
                tx_needed = 1
                per_tx = mint_amount
            plan_mints[token] = {
                "total": mint_amount,
                "tx_count": tx_needed,
                "per_tx": round(per_tx, 6),
                "target": target,
                "already_had": existing,
            }
        else:
            plan_mints[token] = {"total": 0, "tx_count": 0, "per_tx": 0, "target": target, "already_had": existing}

    # Build stake list
    plan_stakes = []
    for token, amount in stake_needs.items():
        if amount > 0:
            plan_stakes.append({"token": token, "amount": amount})

    # Build send list (tagged with origin: send, receive, or both)
    plan_sends = []
    for token, amount in effective_send.items():
        if amount > 0:
            has_send = send_needs.get(token, 0) > 0
            has_recv = receive_needs.get(token, 0) > 0
            if has_send and has_recv:
                origin = "both"
            elif has_send:
                origin = "send"
            else:
                origin = "receive"
            plan_sends.append({"token": token, "amount": amount, "origin": origin})

    # Count total transactions
    total_txs = (
        sum(m["tx_count"] for m in plan_mints.values())
        + len(plan_stakes)
        + len(plan_sends)
    )

    # Filler mints for daily TX minimum (separate from mint missions!)
    daily_tx_amount = float(settings.get("daily_tx_amount", DEFAULTS["daily_tx_amount"]))
    filler_mints = {"usdt": {"tx_count": 0, "per_tx": 0}, "usdc": {"tx_count": 0, "per_tx": 0}}
    extra_added = 0

    if min_tx_count > 0:
        shortfall = min_tx_count
        extra_added = min_tx_count

        # Pick ONE token for filler mints (not both)
        # Priority: token used in mint missions > stake > send > default usdc
        filler_token = "usdc"
        for t in ["usdt", "usdc"]:
            if mint_targets.get(t, 0) > 0:
                filler_token = t
                break
        if filler_token == "usdc":
            for s in plan_stakes:
                filler_token = s["token"]
                break
        if filler_token == "usdc":
            for s in plan_sends:
                filler_token = s["token"]
                break

        filler_mints[filler_token] = {"tx_count": shortfall, "per_tx": daily_tx_amount}
        total_txs += min_tx_count

    return {
        "mints": plan_mints,
        "filler_mints": filler_mints,
        "stakes": plan_stakes,
        "sends": plan_sends,
        "total_txs": total_txs,
        "extra_added": extra_added,
        "min_tx_count": min_tx_count,
    }


def show_plan(plan, balances, dest_addr):
    """Display the execution plan beautifully."""
    mints  = plan["mints"]
    filler = plan.get("filler_mints", {})
    stakes = plan["stakes"]
    sends  = plan["sends"]

    print(f"\n{BOLD_GREEN}  PLAN OVERVIEW{RESET}")
    print(f"  {'─' * 58}")

    has_any = False

    # Regular mint missions (show even if already satisfied)
    for token in ["usdt", "usdc"]:
        m = mints[token]
        cfg = TOKENS[token]
        target = m.get("target", 0)
        if m["tx_count"] > 0:
            has_any = True
            print(
                f"  {BOLD_CYAN}Mint{RESET}  {cfg['plus_name']:6s}: "
                f"{m['tx_count']} tx x {m['per_tx']:.2f} = {m['total']:.2f} (mission)"
            )
        elif target > 0:
            has_any = True
            print(
                f"  {BOLD_CYAN}Mint{RESET}  {cfg['plus_name']:6s}: "
                f"{DIM}0 tx (already have >= {target:.2f} — satisfied){RESET}"
            )

    # Daily TX filler mints (separate!)
    for token in ["usdt", "usdc"]:
        f = filler.get(token, {})
        if f.get("tx_count", 0) > 0:
            has_any = True
            cfg = TOKENS[token]
            print(
                f"  {BOLD_CYAN}Daily{RESET} {cfg['plus_name']:6s}: "
                f"{f['tx_count']} tx x {f['per_tx']:.2f} (filler for daily tx count)"
            )

    if stakes:
        for s in stakes:
            cfg = TOKENS[s["token"]]
            print(f"  {BOLD_CYAN}Stake{RESET} {cfg['plus_name']:6s}: 1 tx x {s['amount']:.2f}")

    if sends:
        for s in sends:
            cfg = TOKENS[s["token"]]
            origin = s.get("origin", "send")
            if origin == "both":
                label = "Send/Recv"
            elif origin == "receive":
                label = "Send (for Receive)"
            else:
                label = "Send"
            print(f"  {BOLD_CYAN}{label}{RESET} {cfg['plus_name']:6s}: 1 tx x {s['amount']:.2f} -> {dest_addr[:10]}...")

    if not has_any and not stakes and not sends:
        print(f"  {BOLD_YELLOW}No transactions needed! All missions already satisfied.{RESET}")

    print(f"  {'─' * 58}")
    print(f"  {BOLD_GREEN}Total Transactions: {plan['total_txs']}{RESET}")

    if plan["extra_added"] > 0:
        print(f"  {BOLD_YELLOW}+ {plan['extra_added']} filler mints for daily TX minimum{RESET}")

    # Gas estimate (using module-level constants)
    filler_tx = sum(f.get("tx_count", 0) for f in filler.values())
    total_gas = (
        sum(m["tx_count"] for m in mints.values()) * GAS_MINT
        + filler_tx * GAS_MINT
        + len(stakes) * GAS_STAKE
        + len(sends) * GAS_SEND
    )
    est_eth = total_gas * 30e9 / 1e18
    print(f"  {BOLD_YELLOW}Est. Gas: ~{est_eth:.6f} ETH ({total_gas:,} gas @ ~30 gwei){RESET}")

    # Current balances
    print(f"\n  {BOLD_CYAN}CURRENT BALANCES:{RESET}")
    print(f"  ETH  : {balances.get('eth', 0):.8f}")
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        base = balances.get(token, 0)
        plus = balances.get(f"{token}_plus", 0)
        print(f"  {cfg['name']:5s}: {base:12.6f}  |  {cfg['plus_name']:6s}: {plus:12.6f}")
    print()


# ═══════════════════════════════════════════════════════════════════
# Execution Engine
# ═══════════════════════════════════════════════════════════════════

GAS_MINT   = 200_000
GAS_STAKE  = 250_000
GAS_SEND   = 100_000
MAX_RETRIES = 2
RETRY_DELAY = 30  # seconds


def _send_with_retry(max_retries=MAX_RETRIES, retry_delay=RETRY_DELAY, **tx_kwargs):
    """Send a transaction with automatic retry on transient failures.

    Retries up to max_retries times, waiting retry_delay seconds between attempts.
    Does NOT retry on insufficient-funds errors - those return immediately.
    """
    action_name = tx_kwargs.get("action_name", "Transaction")

    for attempt in range(max_retries + 1):
        result = send_transaction(**tx_kwargs)

        # Success
        if result and result not in ("FAILED", "INSUFFICIENT", None):
            return result

        # Never retry if insufficient funds
        if result == "INSUFFICIENT":
            return result

        # Retry on transient failures
        if attempt < max_retries:
            log_warn(
                f"  {action_name} failed (attempt {attempt + 1}/{max_retries + 1}). "
                f"Retrying in {retry_delay}s..."
            )
            time.sleep(retry_delay)
        else:
            log_error(f"  {action_name} failed after {max_retries + 1} attempts.")

    return "FAILED"


def execute_mints(plan, pk, addr, rpc_url, settings, total_txs):
    """Execute all mint transactions (both mission mints and filler mints)."""
    delay_min = settings.get("delay_min", DEFAULTS["delay_min"])
    delay_max = settings.get("delay_max", DEFAULTS["delay_max"])
    tx_done = 0
    ok = 0
    consecutive_fails = 0
    filler = plan.get("filler_mints", {})

    for token in ["usdt", "usdc"]:
        m = plan["mints"][token]
        if m["tx_count"] == 0:
            continue

        cfg = TOKENS[token]

        for i in range(1, m["tx_count"] + 1):
            tx_done += 1

            # Recheck base token balance before each transaction
            base_raw = get_token_balance(rpc_url, addr, cfg["token"])
            base_bal = base_raw / 10 ** cfg["decimals"]

            per_tx = m["per_tx"]
            remaining_txs = m["tx_count"] - i + 1

            if base_bal <= 0:
                log_error(
                    f"No {cfg['name']} balance left. "
                    f"Skipping remaining {remaining_txs} mint(s)."
                )
                return ok, tx_done, True

            # Adjust per_tx downward if balance is insufficient
            max_per_tx = base_bal / remaining_txs
            if per_tx > max_per_tx:
                per_tx = max_per_tx
                log_warn(
                    f"{cfg['name']} balance ({base_bal:.2f}) is low. "
                    f"Adjusting this mint to {per_tx:.2f} {cfg['name']}."
                )

            # Guard against zero-value mints
            if per_tx < 0.000001:
                log_error(
                    f"{cfg['name']} balance too low ({base_bal:.8f}). "
                    f"Skipping remaining {remaining_txs} mint(s)."
                )
                return ok, tx_done, True

            # Build calldata with current per_tx
            token_raw = int(per_tx * 10 ** cfg["decimals"])
            plus_raw  = int(per_tx * 10 ** cfg["plus_decimals"])
            mint_cd   = build_mint_calldata(addr, addr, cfg["token"], token_raw, plus_raw)

            log_task(
                f"[{tx_done}/{total_txs}] Mint {cfg['plus_name']} "
                f"({i}/{m['tx_count']}) | {per_tx:.2f} {cfg['name']} -> {cfg['plus_name']}"
            )

            result = _send_with_retry(
                rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
                chain_id=SEPOLIA_CHAIN_ID, pk=pk, address=addr,
                to_contract=cfg["plus"], value_wei=0,
                calldata=mint_cd,
                action_name=f"Mint {cfg['plus_name']} #{i}/{m['tx_count']}",
                gas_limit_override=GAS_MINT, proxy=None,
            )

            if result and result not in ("FAILED", "INSUFFICIENT", None):
                ok += 1
                consecutive_fails = 0
                log_success(f"  Mint #{i} complete")
            else:
                consecutive_fails += 1
                log_error(f"  Mint #{i} failed: {result}")
                if result == "INSUFFICIENT":
                    log_error("Not enough ETH for gas. Stopping mints.")
                    return ok, tx_done, True
                if consecutive_fails >= 3:
                    log_error("3 consecutive failures. Stopping mints.")
                    return ok, tx_done, True

            if i < m["tx_count"]:
                delay = random.uniform(delay_min, delay_max)
                log_info(f"Waiting {delay:.1f}s...")
                time.sleep(delay)

    # ── Daily TX filler mints (separate small transactions) ──
    has_filler = any(filler.get(token, {}).get("tx_count", 0) > 0 for token in ["usdt", "usdc"])
    if has_filler:
        print(f"\n  {BOLD_CYAN}── Daily TX filler mints ──{RESET}")
        consecutive_fails = 0  # reset for filler phase

        for token in ["usdt", "usdc"]:
            f = filler.get(token, {})
            if f.get("tx_count", 0) == 0:
                continue

            cfg = TOKENS[token]
            count = f["tx_count"]
            per_tx = f["per_tx"]

            for i in range(1, count + 1):
                tx_done += 1

                # Recheck balance
                base_raw = get_token_balance(rpc_url, addr, cfg["token"])
                base_bal = base_raw / 10 ** cfg["decimals"]

                actual = min(per_tx, base_bal)
                if actual <= 0:
                    log_error(f"No {cfg['name']} balance for filler mint. Skipping.")
                    continue

                if actual < per_tx:
                    log_warn(f"Filler mint adjusted to {actual:.2f} {cfg['name']}")

                token_raw = int(actual * 10 ** cfg["decimals"])
                plus_raw = int(actual * 10 ** cfg["plus_decimals"])
                mint_cd = build_mint_calldata(addr, addr, cfg["token"], token_raw, plus_raw)

                log_task(
                    f"[{tx_done}/{total_txs}] Daily {cfg['plus_name']} "
                    f"({i}/{count}) | {actual:.2f} {cfg['name']} -> {cfg['plus_name']}"
                )

                result = _send_with_retry(
                    rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
                    chain_id=SEPOLIA_CHAIN_ID, pk=pk, address=addr,
                    to_contract=cfg["plus"], value_wei=0,
                    calldata=mint_cd,
                    action_name=f"Daily {cfg['plus_name']} #{i}/{count}",
                    gas_limit_override=GAS_MINT, proxy=None,
                )

                if result and result not in ("FAILED", "INSUFFICIENT", None):
                    ok += 1
                    consecutive_fails = 0
                    log_success(f"  Daily mint #{i} complete")
                else:
                    consecutive_fails += 1
                    log_error(f"  Daily mint #{i} failed: {result}")
                    if result == "INSUFFICIENT":
                        log_error("Not enough ETH. Stopping filler mints.")
                        return ok, tx_done, True
                    if consecutive_fails >= 3:
                        log_error("3 consecutive failures. Stopping filler mints.")
                        return ok, tx_done, True

                if i < count:
                    delay = random.uniform(delay_min, delay_max)
                    log_info(f"Waiting {delay:.1f}s...")
                    time.sleep(delay)

    return ok, tx_done, False


def execute_stakes(plan, pk, addr, rpc_url, settings, total_txs):
    """Execute all stake transactions. Returns (ok, tx_done) counts."""
    delay_min = settings.get("delay_min", DEFAULTS["delay_min"])
    delay_max = settings.get("delay_max", DEFAULTS["delay_max"])
    tx_done = 0
    ok = 0

    for idx, s in enumerate(plan["stakes"]):
        token  = s["token"]
        amount = s["amount"]
        cfg    = TOKENS[token]

        # Check current balance
        bal_raw = get_token_balance(rpc_url, addr, cfg["plus"])
        bal     = bal_raw / 10 ** cfg["plus_decimals"]

        actual = min(amount, bal)
        if actual <= 0:
            log_error(f"No {cfg['plus_name']} to stake. Skipping.")
            continue

        if actual < amount:
            log_warn(
                f"Stake shortfall: need {amount:.2f}, have {bal:.2f}. "
                f"Staking {actual:.2f}."
            )

        amount_raw = int(actual * 10 ** cfg["plus_decimals"])
        stake_cd   = build_stake_calldata(amount_raw, addr)

        tx_done += 1
        log_task(
            f"[{tx_done}/{total_txs}] Stake {actual:.2f} {cfg['plus_name']}"
        )

        result = _send_with_retry(
            rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
            chain_id=SEPOLIA_CHAIN_ID, pk=pk, address=addr,
            to_contract=cfg["stake_contract"], value_wei=0,
            calldata=stake_cd,
            action_name=f"Stake {actual:.2f} {cfg['plus_name']}",
            gas_limit_override=GAS_STAKE, proxy=None,
        )

        if result and result not in ("FAILED", "INSUFFICIENT", None):
            ok += 1
            log_success(f"  Stake complete")
        else:
            log_error(f"  Stake failed: {result}")
            if result == "INSUFFICIENT":
                log_error("Not enough ETH. Stopping.")
                return ok, tx_done

        if idx < len(plan["stakes"]) - 1:
            delay = random.uniform(delay_min, delay_max)
            log_info(f"Waiting {delay:.1f}s...")
            time.sleep(delay)

    return ok, tx_done


def execute_sends(plan, pk, addr, dest_addr, rpc_url, settings, total_txs):
    """Execute all send transactions. Returns (ok, tx_done) counts."""
    delay_min = settings.get("delay_min", DEFAULTS["delay_min"])
    delay_max = settings.get("delay_max", DEFAULTS["delay_max"])
    tx_done = 0
    ok = 0

    for idx, s in enumerate(plan["sends"]):
        token  = s["token"]
        amount = s["amount"]
        cfg    = TOKENS[token]

        # Check current balance
        bal_raw = get_token_balance(rpc_url, addr, cfg["plus"])
        bal     = bal_raw / 10 ** cfg["plus_decimals"]

        actual = min(amount, bal)
        if actual <= 0:
            log_error(f"No {cfg['plus_name']} to send. Skipping.")
            continue

        if actual < amount:
            log_warn(
                f"Send shortfall: need {amount:.2f}, have {bal:.2f}. "
                f"Sending {actual:.2f}."
            )

        amount_raw = int(actual * 10 ** cfg["plus_decimals"])
        send_cd    = build_send_calldata(dest_addr, amount_raw)

        tx_done += 1
        log_task(
            f"[{tx_done}/{total_txs}] Send {actual:.2f} "
            f"{cfg['plus_name']} -> {dest_addr[:10]}..."
        )

        result = _send_with_retry(
            rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
            chain_id=SEPOLIA_CHAIN_ID, pk=pk, address=addr,
            to_contract=cfg["plus"], value_wei=0,
            calldata=send_cd,
            action_name=f"Send {actual:.2f} {cfg['plus_name']}",
            gas_limit_override=GAS_SEND, proxy=None,
        )

        if result and result not in ("FAILED", "INSUFFICIENT", None):
            ok += 1
            log_success(f"  Send complete")
        else:
            log_error(f"  Send failed: {result}")
            if result == "INSUFFICIENT":
                log_error("Not enough ETH. Stopping.")
                return ok, tx_done

        if idx < len(plan["sends"]) - 1:
            delay = random.uniform(delay_min, delay_max)
            log_info(f"Waiting {delay:.1f}s...")
            time.sleep(delay)

    return ok, tx_done


def execute_return_transfer(dest_pk, dest_addr, main_addr, rpc_url, settings, plan_sends=None):
    """
    Interactive return transfer: lets you choose which token and how much
    to send back from the target wallet to your main wallet.
    This completes the Receive mission by having the main wallet receive tokens.
    Returns (ok, tx_done) counts.
    """
    tx_done = 0
    ok = 0

    print(f"\n{BOLD_MAGENTA}{'═' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}[Phase 4/4] Return Transfer - Target -> Main (Receive mission){RESET}")
    print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")

    # Only offer tokens that were actually sent (not both unconditionally)
    sent_tokens = sorted(set(s["token"] for s in (plan_sends or [])))
    if not sent_tokens:
        log_info("No tokens were sent — nothing to return.")
        return ok, tx_done

    # Query target wallet balances for each sent token
    print(f"\n  {BOLD_CYAN}Target wallet balances ({dest_addr[:10]}...):{RESET}")
    available = []
    for token in sent_tokens:
        cfg = TOKENS[token]
        bal_raw = get_token_balance(rpc_url, dest_addr, cfg["plus"])
        bal = bal_raw / 10 ** cfg["plus_decimals"]
        marker = f"  {BOLD_GREEN}{cfg['plus_name']:6s}: {bal:.6f}{RESET}"
        if bal > 0:
            print(marker)
            available.append((token, bal, cfg))
        else:
            print(f"  {DIM}{cfg['plus_name']:6s}: {bal:.6f}{RESET}")

    if not available:
        log_info("Target wallet has no tokens to return.")
        return ok, tx_done

    # ── Ask user which token & how much to return ──
    print()
    if not _ask_yesno("Do you want to return tokens from the target wallet?", "y"):
        log_info("Return skipped.")
        return ok, tx_done

    token = None
    bal = 0.0
    cfg = None

    if len(available) == 1:
        # Only one token available — use it directly
        token, bal, cfg = available[0]
    else:
        # Let user pick which token to return
        print(f"  {BOLD_WHITE}Which token do you want to return?{RESET}")
        for i, (t, b, c) in enumerate(available, 1):
            print(f"    {BOLD_CYAN}[{i}]{RESET} {c['plus_name']}: {b:.6f}")

        while True:
            raw = input(f"  {BOLD_WHITE}Choose (1-{len(available)}): {RESET}").strip()
            if not raw:
                log_info("Return skipped.")
                return ok, tx_done
            try:
                choice = int(raw)
                if 1 <= choice <= len(available):
                    token, bal, cfg = available[choice - 1]
                    break
                log_error(f"Please enter 1-{len(available)}")
            except ValueError:
                log_error("Please enter a number")

    # Ask how much to return (default: all)
    print()
    return_amount = _ask_number(
        f"Amount of {cfg['plus_name']} to return (available: {bal:.6f})",
        default=bal, min_val=0.000001
    )

    actual_return = min(return_amount, bal)
    if actual_return <= 0:
        log_info("Return amount is zero. Skipping.")
        return ok, tx_done

    if actual_return < return_amount:
        log_warn(f"Clamped to available balance: {actual_return:.6f} {cfg['plus_name']}")

    # ── Execute the return ──
    tx_done += 1
    amount_raw = int(actual_return * 10 ** cfg["plus_decimals"])
    send_cd = build_send_calldata(main_addr, amount_raw)

    log_task(
        f"Return {actual_return:.2f} "
        f"{cfg['plus_name']} from {dest_addr[:10]}... -> {main_addr[:10]}..."
    )

    result = _send_with_retry(
        rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
        chain_id=SEPOLIA_CHAIN_ID, pk=dest_pk, address=dest_addr,
        to_contract=cfg["plus"], value_wei=0,
        calldata=send_cd,
        action_name=f"Return {actual_return:.2f} {cfg['plus_name']}",
        gas_limit_override=GAS_SEND, proxy=None,
    )

    if result and result not in ("FAILED", "INSUFFICIENT", None):
        ok += 1
        log_success(f"  Return complete: {actual_return:.2f} {cfg['plus_name']}")
    else:
        log_error(f"  Return failed: {result}")
        if result == "INSUFFICIENT":
            log_error("  Target wallet needs ETH for gas. Add ETH to the target wallet.")

    return ok, tx_done


def execute_plan(plan, pk, addr, dest_addr, rpc_url, settings, dest_pk=None):
    """Execute the full plan. Returns (total_ok, total_tx)."""
    total_ok = 0
    total_tx = 0

    # Phase 1: Mints (mission + filler)
    has_mints = (
        any(m["tx_count"] > 0 for m in plan["mints"].values())
        or any(plan.get("filler_mints", {}).get(t, {}).get("tx_count", 0) > 0 for t in ["usdt", "usdc"])
    )
    if has_mints:
        print(f"\n{BOLD_MAGENTA}{'═' * 60}{RESET}")
        print(f"  {BOLD_YELLOW}[Phase 1/3] Mint - Converting tokens{RESET}")
        print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")
        ok, tx, _ = execute_mints(plan, pk, addr, rpc_url, settings, plan["total_txs"])
        total_ok += ok
        total_tx += tx

    # Phase 2: Stakes
    if plan["stakes"]:
        print(f"\n{BOLD_MAGENTA}{'═' * 60}{RESET}")
        print(f"  {BOLD_YELLOW}[Phase 2/3] Stake - Locking tokens{RESET}")
        print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")
        ok, tx = execute_stakes(plan, pk, addr, rpc_url, settings, plan["total_txs"])
        total_ok += ok
        total_tx += tx

    # Phase 3: Sends
    if plan["sends"]:
        print(f"\n{BOLD_MAGENTA}{'═' * 60}{RESET}")
        print(f"  {BOLD_YELLOW}[Phase 3/3] Send - Transferring tokens{RESET}")
        print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")
        ok, tx = execute_sends(plan, pk, addr, dest_addr, rpc_url, settings, plan["total_txs"])
        total_ok += ok
        total_tx += tx

    # Phase 4: Return Transfer (if target private key is available)
    if dest_pk and plan["sends"]:
        print(f"\n{BOLD_MAGENTA}{'═' * 60}{RESET}")
        print(f"  {BOLD_YELLOW}[Phase 4/4] Return Transfer - Completing Receive mission{RESET}")
        print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")
        ok, tx = execute_return_transfer(dest_pk, dest_addr, addr, rpc_url, settings, plan["sends"])
        total_ok += ok
        total_tx += tx

    return total_ok, total_tx


# ═══════════════════════════════════════════════════════════════════
# Final Report
# ═══════════════════════════════════════════════════════════════════

def final_report(rpc_url, addr, dest_addr, total_ok, total_tx, missions, plan, start_balances):
    """Print a comprehensive final report with actual on-chain balances."""
    # Re-query actual on-chain balances
    eth = get_balance_eth(rpc_url, addr)
    end_balances = {"eth": eth}
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        end_balances[token] = get_token_balance(rpc_url, addr, cfg["token"]) / 10 ** cfg["decimals"]
        end_balances[f"{token}_plus"] = get_token_balance(rpc_url, addr, cfg["plus"]) / 10 ** cfg["plus_decimals"]
        end_balances[f"{token}_plus_dest"] = get_token_balance(rpc_url, dest_addr, cfg["plus"]) / 10 ** cfg["plus_decimals"]

    print(f"\n{BOLD_GREEN}{'=' * 60}{RESET}")
    print(f"{BOLD_GREEN}  ALL DONE!{RESET}")
    print(f"{BOLD_GREEN}{'=' * 60}{RESET}")
    print(f"  Transactions attempted : {total_tx}")
    print(f"  {BOLD_GREEN}Successful            : {total_ok}{RESET}")
    fail = total_tx - total_ok
    if fail > 0:
        print(f"  {BOLD_RED}Failed                : {fail}{RESET}")

    # Mission status (using actual final balances)
    print(f"\n  {BOLD_CYAN}MISSION STATUS (based on actual balances):{RESET}")
    for m in missions:
        mtype  = m["type"]
        label  = m.get("label", str(m))
        token  = m.get("token", "")
        amount = m.get("amount", 0)

        if mtype == "daily_tx":
            target = plan["min_tx_count"]
            status = "COMPLETE" if total_ok >= target else "PARTIAL"
            color = BOLD_GREEN if total_ok >= target else BOLD_YELLOW
            print(f"  {color}[{status}]{RESET} {label} ({total_ok}/{target} tx)")
        elif mtype == "mint":
            cfg = TOKENS.get(token, {})
            plus_name = cfg.get("plus_name", f"{token.upper()}+")
            mint_info = plan["mints"].get(token, {})
            planned_mint = mint_info.get("total", 0)
            if planned_mint >= amount:
                status = "COMPLETE"
                color = BOLD_GREEN
                print(f"  {color}[{status}]{RESET} {label} (minted {planned_mint:.2f}/{amount} {plus_name})")
            else:
                status = "PARTIAL"
                color = BOLD_YELLOW
                print(f"  {color}[{status}]{RESET} {label} (minted {planned_mint:.2f}/{amount} {plus_name})")
        elif mtype == "stake":
            cfg = TOKENS.get(token, {})
            plus_name = cfg.get("plus_name", f"{token.upper()}+")
            # Staking reduces plus balance, so we check if it dropped by the needed amount
            starting = start_balances.get(f"{token}_plus", 0)
            actual = end_balances.get(f"{token}_plus", 0)
            staked_est = max(0, starting - actual)
            status = "COMPLETE" if staked_est >= amount else "PARTIAL"
            color = BOLD_GREEN if staked_est >= amount else BOLD_YELLOW
            print(f"  {color}[{status}]{RESET} {label} (~{staked_est:.2f}/{amount} {plus_name} staked)")
        elif mtype in ("send", "receive"):
            cfg = TOKENS.get(token, {})
            plus_name = cfg.get("plus_name", f"{token.upper()}+")
            dest_bal = end_balances.get(f"{token}_plus_dest", 0)
            status = "COMPLETE" if dest_bal >= amount else "PARTIAL"
            color = BOLD_GREEN if dest_bal >= amount else BOLD_YELLOW
            print(f"  {color}[{status}]{RESET} {label} ({dest_bal:.2f}/{amount} {plus_name} at target)")

    # Final balances
    print(f"\n  {BOLD_CYAN}FINAL BALANCES:{RESET}")
    print(f"  ETH  : {eth:.8f}")
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        base = end_balances[token]
        plus = end_balances[f"{token}_plus"]
        dest = end_balances.get(f"{token}_plus_dest", 0)
        print(f"  {cfg['name']:5s}: {base:.6f} | {cfg['plus_name']:6s}: {plus:.6f} | Target {cfg['plus_name']}: {dest:.6f}")

    # Website check reminder
    print(f"\n  {BOLD_YELLOW}VERIFY ONLINE:{RESET}")
    print(f"  Check your missions at: {BOLD_CYAN}https://testnet.overlayer.fi/early-user{RESET}")
    print(f"  View transactions at:  {BOLD_CYAN}{SEPOLIA_EXPLORER}/address/{addr}{RESET}")

    print(f"{BOLD_GREEN}{'=' * 60}{RESET}\n")


# ═══════════════════════════════════════════════════════════════════
# Wallet Setup
# ═══════════════════════════════════════════════════════════════════

def setup_wallet():
    """
    Load or prompt for main wallet private key & target wallet.
    Shows all available wallet pairs from wallets.txt for the user to pick.
    Returns (main_pk, main_addr, dest_addr, dest_pk_or_none).
    dest_pk is None if the target wallet's private key isn't known.
    """
    import config

    # ── Main wallet ──
    pk = config.load_master_key()
    if pk:
        addr = private_key_to_address(pk)
        log_success(f"Main wallet loaded: {addr}")
    else:
        print(f"\n  {BOLD_YELLOW}No main wallet found. Let's set one up.{RESET}")
        log_info("You need a Sepolia wallet with ETH, USDT, and USDC.")
        log_info("Get testnet tokens from: https://testnet.overlayer.fi/early-user")
        print()
        pk_input = input(f"  {BOLD_WHITE}Paste your private key: {RESET}").strip()
        if not pk_input:
            log_error("No private key provided. Exiting.")
            sys.exit(1)
        if not pk_input.startswith("0x"):
            pk_input = "0x" + pk_input
        pk = pk_input
        addr = private_key_to_address(pk)
        log_success(f"Main wallet address: {addr}")

        save = _ask_yesno("Save this key to master_privatekey.txt?", "y")
        if save:
            with open("master_privatekey.txt", "w", encoding="utf-8") as f:
                f.write(pk + "\n")
            log_info("Saved to master_privatekey.txt")

    # ── Target wallet ──
    dest_addr = None
    dest_pk = None

    # Try loading full wallet pairs (address + private key) from wallets.txt
    pairs = config.load_wallet_pairs()
    addresses_only = []

    if pairs:
        print(f"\n  {BOLD_GREEN}Found {len(pairs)} wallet(s) in wallets.txt:{RESET}")
        for i, (w_addr, w_pk) in enumerate(pairs, 1):
            is_main = " (MAIN)" if w_addr.lower() == addr.lower() else ""
            print(f"    {BOLD_CYAN}[{i}]{RESET} {w_addr}{is_main}")
        print(f"    {BOLD_CYAN}[0]{RESET} Enter a new address manually")
        print()

        while True:
            raw = input(f"  {BOLD_WHITE}Select target wallet (1-{len(pairs)}, or 0): {RESET}").strip()
            if not raw:
                # Use first non-main wallet by default
                for w_addr, w_pk in pairs:
                    if w_addr.lower() != addr.lower():
                        dest_addr = w_addr
                        dest_pk = w_pk
                        break
                if dest_addr:
                    break
                raw = "0"
            try:
                choice = int(raw)
                if choice == 0:
                    break
                if 1 <= choice <= len(pairs):
                    dest_addr, dest_pk = pairs[choice - 1]
                    break
                log_error(f"Please enter 0-{len(pairs)}")
            except ValueError:
                log_error("Please enter a number")

    else:
        # Fallback: try loading address-only wallets
        addresses_only = config.load_wallets()
        if addresses_only:
            print(f"\n  {BOLD_GREEN}Found {len(addresses_only)} address(es) in wallets.txt:{RESET}")
            for i, w_addr in enumerate(addresses_only, 1):
                is_main = " (MAIN)" if w_addr.lower() == addr.lower() else ""
                print(f"    {BOLD_CYAN}[{i}]{RESET} {w_addr}{is_main}")
            print(f"    {BOLD_CYAN}[0]{RESET} Enter a new address manually")
            print()

            while True:
                raw = input(f"  {BOLD_WHITE}Select target wallet (1-{len(addresses_only)}, or 0): {RESET}").strip()
                if not raw:
                    for w_addr in addresses_only:
                        if w_addr.lower() != addr.lower():
                            dest_addr = w_addr
                            break
                    if dest_addr:
                        break
                    raw = "0"
                try:
                    choice = int(raw)
                    if choice == 0:
                        break
                    if 1 <= choice <= len(addresses_only):
                        dest_addr = addresses_only[choice - 1]
                        dest_pk = None  # no private key available
                        break
                    log_error(f"Please enter 0-{len(addresses_only)}")
                except ValueError:
                    log_error("Please enter a number")

    # If no target selected, prompt manually
    if not dest_addr:
        print()
        log_info("This is the wallet that will RECEIVE tokens (for Send/Receive missions).")
        dest_input = input(f"  {BOLD_WHITE}Paste target wallet address: {RESET}").strip()
        if not dest_input:
            log_error("No target address provided. Exiting.")
            sys.exit(1)
        if not dest_input.startswith("0x"):
            dest_input = "0x" + dest_input
        dest_addr = dest_input

        # Ask for target private key too (optional, for return transfer)
        print(f"  {DIM}(Optional) If you have the target wallet's private key, you can enable{RESET}")
        print(f"  {DIM}automatic return transfers to complete the Receive mission.{RESET}")
        pk_input = input(f"  {BOLD_WHITE}Paste target private key (or Enter to skip): {RESET}").strip()
        if pk_input:
            if not pk_input.startswith("0x"):
                pk_input = "0x" + pk_input
            dest_pk = pk_input

        # Save
        save = _ask_yesno("Save this to wallets.txt?", "y")
        if save:
            with open("wallets.txt", "a", encoding="utf-8") as f:
                if dest_pk:
                    f.write(f"{dest_addr}:{dest_pk}\n")
                else:
                    f.write(f"{dest_addr}\n")
            log_info("Appended to wallets.txt")

    if dest_pk:
        log_info(f"Target wallet: {dest_addr} (private key available)")
    else:
        log_info(f"Target wallet: {dest_addr} (no private key - return transfer disabled)")

    return pk, addr, dest_addr, dest_pk


# ═══════════════════════════════════════════════════════════════════
# Website Verification - Check mission completion online
# ═══════════════════════════════════════════════════════════════════

VERIFY_URL = "https://testnet.overlayer.fi/early-user"


def verify_website(missions):
    """
    Guide the user through verifying mission completion on the Overlayer website.

    Opens the website and walks the user through checking each mission's
    status, collecting their confirmation.
    """
    print(f"\n{BOLD_MAGENTA}{'═' * 60}{RESET}")
    print(f"  {BOLD_GREEN}WEBSITE VERIFICATION{RESET}")
    print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")
    print(f"\n  {BOLD_WHITE}Let's check if your tasks are verified on the website.{RESET}")
    print(f"  {BOLD_YELLOW}Opening: {VERIFY_URL}{RESET}")
    print()

    # Open the website
    try:
        webbrowser.open(VERIFY_URL)
        log_success("Website opened in your browser.")
    except Exception:
        log_warn(f"Could not open browser. Please visit: {VERIFY_URL}")

    print(f"\n  {BOLD_WHITE}On the website, look for today's missions.{RESET}")
    print(f"  Each mission should show '{BOLD_GREEN}Verified{RESET}' if completed.")
    print(f"  {DIM}Note: It may take a few minutes for the blockchain to confirm.{RESET}")
    print()

    all_verified = True
    partial_any = False

    for i, m in enumerate(missions, 1):
        mtype = m["type"]
        label = m.get("label", str(m))
        print(f"  {BOLD_WHITE}Mission {i}:{RESET} {label}")

        verified = _ask_yesno("  Does it show 'Verified' on the website?", "n")

        if verified:
            log_success(f"  Mission '{label}' - Verified!")
        else:
            all_verified = False
            log_warn(f"  Mission '{label}' - Not yet verified.")
            if mtype != "daily_tx":
                log_info("  -> Wait a few minutes and refresh. Transactions may still be confirming.")
            else:
                log_info("  -> Daily TX checks all transactions. Wait 5-10 min and refresh.")
            partial_any = True

    print()
    if all_verified:
        print(f"  {BOLD_GREEN}  All missions verified! Great job!{RESET}")
    elif partial_any:
        print(f"  {BOLD_YELLOW}  Some missions not yet verified. Check back in a few minutes.{RESET}")
        print(f"  {BOLD_YELLOW}  You can re-run this script later: python daily_missions.py{RESET}")

    print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")

    return all_verified


# ═══════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════

def main():
    _clear()
    banner("Ethereum Sepolia - Daily Mission Runner")
    print(f"  {BOLD_WHITE}Network : Sepolia Testnet (Chain ID: {SEPOLIA_CHAIN_ID}){RESET}")
    print(f"  {BOLD_WHITE}Website : https://testnet.overlayer.fi/early-user{RESET}")
    print(f"  {BOLD_WHITE}Explorer: {SEPOLIA_EXPLORER}{RESET}")
    print()

    # ── Wallet Setup ──
    print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")
    print(f"  {BOLD_YELLOW}WALLET SETUP{RESET}")
    print(f"{BOLD_MAGENTA}{'═' * 60}{RESET}")
    pk, addr, dest_addr, dest_pk = setup_wallet()
    print()

    # ── Find RPC ──
    log_task("Scanning for available RPC nodes...")
    rpc_url = find_working_rpc(RPC_ENDPOINTS)
    if not rpc_url:
        log_error("No RPC nodes available. Check your internet connection.")
        sys.exit(1)

    # ── Query Balances ──
    log_task("Loading token balances...")
    balances = {}
    balances["eth"] = get_balance_eth(rpc_url, addr)
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        balances[token] = get_token_balance(rpc_url, addr, cfg["token"]) / 10 ** cfg["decimals"]
        balances[f"{token}_plus"] = get_token_balance(rpc_url, addr, cfg["plus"]) / 10 ** cfg["plus_decimals"]

    # ── Show Wallet Info ──
    print(f"\n{BOLD_CYAN}{'═' * 60}{RESET}")
    print(f"  {BOLD_GREEN}WALLET INFO{RESET}")
    print(f"  Main   : {addr}")
    print(f"  Target : {dest_addr}")
    if dest_pk:
        print(f"  Return : ENABLED (target has private key)")
    else:
        print(f"  Return : DISABLED (no target private key)")
    print(f"  ETH    : {balances['eth']:.8f}")
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        print(f"  {cfg['name']:5s} : {balances[token]:.6f}  |  {cfg['plus_name']:6s} : {balances[f'{token}_plus']:.6f}")
    print(f"{BOLD_CYAN}{'═' * 60}{RESET}")

    # ── Check minimum requirements ──
    if balances["eth"] < 0.001:
        log_warn("ETH balance is very low. You may not have enough for gas.")
        log_info("Get testnet ETH from a Sepolia faucet.")
        if not _ask_yesno("Continue anyway?", "n"):
            sys.exit(0)

    # ── Mission Configuration ──
    missions, settings = mission_wizard()

    if not missions:
        log_info("No missions configured. Goodbye!")
        sys.exit(0)

    # ── Analyze & Plan ──
    plan = analyze_and_plan(missions, settings, balances)

    if plan["total_txs"] == 0:
        print(f"\n{BOLD_GREEN}  All missions already completed! No transactions needed.{RESET}")
        print(f"  Check online: {BOLD_CYAN}https://testnet.overlayer.fi/early-user{RESET}")
        sys.exit(0)

    show_plan(plan, balances, dest_addr)

    # ── Confirm ──
    if not _ask_yesno("Execute this plan now?"):
        log_info("Execution cancelled. Config saved for next run.")
        sys.exit(0)

    # ── Execute ──
    total_ok, total_tx = execute_plan(plan, pk, addr, dest_addr, rpc_url, settings, dest_pk)

    # ── Final Report ──
    final_report(rpc_url, addr, dest_addr, total_ok, total_tx, missions, plan, balances)

    # ── Website Verification ──
    all_verified = True
    if _ask_yesno("Verify on the Overlayer website now?", "y"):
        all_verified = verify_website(missions)

    sys.exit(0 if (total_ok >= total_tx and all_verified) else 1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{BOLD_YELLOW}  Cancelled by user. Goodbye!{RESET}\n")
        sys.exit(0)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        log_info("Please report this issue with the error details above.")
        sys.exit(1)
