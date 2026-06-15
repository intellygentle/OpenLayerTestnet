"""
Smart Mission Runner
====================
Reads missions.json and executes all missions optimally.

Supported mission types:
  - mint:       Convert base token (USDT/USDC) -> plus token (USDT+/USDC+)
  - stake:      Lock plus tokens in staking contracts
  - send:       Transfer plus tokens to target wallet
  - receive:    Target wallet receives tokens (auto-completed by send)
  - daily_tx:   Ensure minimum transaction count

Execution order:
  1. Mint all needed plus tokens (base -> plus conversion)
  2. Stake (lock tokens in staking contracts)
  3. Send (transfer tokens to target wallet)

Usage:
  python mission_runner.py              # Interactive mode (confirm before exec)
  python mission_runner.py --auto       # Auto mode (skip prompts)
  python mission_runner.py --dry-run    # Show plan without executing
  python mission_runner.py --config missions_v2.json  # Custom config

Config: missions.json
"""

import argparse
import json
import math
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
    banner, log_error, log_info, log_success, log_task, log_warn, log_process,
)
from utils.rpc import find_working_rpc, get_balance_eth, rpc_call, send_transaction


# ═══════════════════════════════════════════════════════════════════════
# Network & Token Config
# ═══════════════════════════════════════════════════════════════════════

SEPOLIA_CHAIN_ID = 11155111
SEPOLIA_EXPLORER = "https://sepolia.etherscan.io"

TOKENS = {
    "usdt": {
        "name": "USDT", "plus_name": "USDT+",
        "token": "0xaa8e23fb1079ea71e0a56f48a2aa51851d8433d0",
        "plus": "0xe20534a32f9162488a90026F268a74fBE28d272D",
        "stake_contract": "0x079a4Bf1Cbd0E4ce15391340cB46efA6396aBc82",
        "decimals": 6, "plus_decimals": 18,
    },
    "usdc": {
        "name": "USDC", "plus_name": "USDC+",
        "token": "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8",
        "plus": "0xE815718D44694ec4637CB775C468d87f6e15B538",
        "stake_contract": "0x753937137eb92871A6f3517514d4f1ee860E3fDF",
        "decimals": 6, "plus_decimals": 18,
    },
}

# Function selectors
MINT_SELECTOR    = "2ef6f1ab"  # mint(tuple(address,address,address,uint256,uint256))
DEPOSIT_SELECTOR = "6e553f65"  # deposit(uint256 assets, address receiver)
TRANSFER_SELECTOR= "a9059cbb"  # transfer(address to, uint256 amount)
BALANCE_SELECTOR = "70a08231"  # balanceOf(address)

# Gas limits per operation
GAS_MINT  = 200_000
GAS_STAKE = 250_000
GAS_SEND  = 100_000

DEFAULT_RPC_ENDPOINTS = [
    "https://ethereum-sepolia-rpc.publicnode.com",
    "https://eth-sepolia.g.alchemy.com/v2/yvU9zBs-HghFUcRcdTikw",
    "https://rpc.sepolia.org",
    "https://sepolia.drpc.org",
]

DEFAULTS = {
    "mint_per_tx": 100,
    "delay_min": 5,
    "delay_max": 12,
    "target_wallet_index": 0,
    "auto_confirm": False,
}


# ═══════════════════════════════════════════════════════════════════════
# Interactive Input Helpers
# ═══════════════════════════════════════════════════════════════════════

def _input_float(prompt_text, default=None):
    """Interactive float input with default value."""
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
    """Interactive integer input with default value."""
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
        marker = " <- default" if key == default else ""
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
    """Interactive yes/no confirmation."""
    yn = "Y/n" if default == "y" else "y/N"
    while True:
        raw = input(f"  {BOLD_WHITE}{prompt_text} ({yn}): {RESET}").strip().lower()
        if not raw:
            return default == "y"
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        log_error("Please enter y or n")


def interactive_configure(balances):
    """
    Interactively ask user for mission parameters.
    Returns (missions_list, settings_dict).
    """
    missions = []
    settings = dict(DEFAULTS)

    print(f"\n{BOLD_MAGENTA}{'━' * 70}{RESET}")
    print(f"{BOLD_YELLOW}  Configure today's missions:{RESET}")
    print(f"{BOLD_MAGENTA}{'━' * 70}{RESET}")

    # ── Mint missions (supports multiple) ──
    print(f"\n{BOLD_CYAN}  [1/5] Mint Mission(s){RESET}")
    while _input_yn("Add a Mint mission?", "y"):
        token = _input_choice(
            "Token to mint",
            [("usdc", "USDC -> USDC+"), ("usdt", "USDT -> USDT+")],
            default="usdc",
        )
        cfg = TOKENS[token]
        plus_bal = balances.get(f"{token}_plus", 0)
        print(f"  {BOLD_WHITE}Current {cfg['plus_name']} balance: {plus_bal:.6f}{RESET}")
        amount = _input_float(f"Target {cfg['plus_name']} amount to mint")
        missions.append({"type": "mint", "token": token, "amount": amount})
        print(f"  {BOLD_GREEN}+ Added: mint {amount} {cfg['plus_name']}{RESET}")

    # ── Stake missions (supports multiple) ──
    print(f"\n{BOLD_CYAN}  [2/5] Stake Mission(s){RESET}")
    while _input_yn("Add a Stake mission?", "y"):
        token = _input_choice(
            "Token to stake",
            [("usdt", "USDT+ stake"), ("usdc", "USDC+ stake")],
            default="usdt",
        )
        cfg = TOKENS[token]
        plus_bal = balances.get(f"{token}_plus", 0)
        print(f"  {BOLD_WHITE}Current {cfg['plus_name']} balance: {plus_bal:.6f}{RESET}")
        amount = _input_float(f"Amount of {cfg['plus_name']} to stake")
        missions.append({"type": "stake", "token": token, "amount": amount})
        print(f"  {BOLD_GREEN}+ Added: stake {amount} {cfg['plus_name']}{RESET}")

    # ── Send missions (supports multiple) ──
    print(f"\n{BOLD_CYAN}  [3/5] Send Mission(s){RESET}")
    while _input_yn("Add a Send mission?", "y"):
        token = _input_choice(
            "Token to send",
            [("usdt", "USDT+ send"), ("usdc", "USDC+ send")],
            default="usdt",
        )
        cfg = TOKENS[token]
        plus_bal = balances.get(f"{token}_plus", 0)
        print(f"  {BOLD_WHITE}Current {cfg['plus_name']} balance: {plus_bal:.6f}{RESET}")
        amount = _input_float(f"Amount of {cfg['plus_name']} to send")
        missions.append({"type": "send", "token": token, "amount": amount})
        print(f"  {BOLD_GREEN}+ Added: send {amount} {cfg['plus_name']}{RESET}")

    # ── Receive missions (supports multiple) ──
    print(f"\n{BOLD_CYAN}  [4/5] Receive Mission(s){RESET}")
    while _input_yn("Add a Receive mission?", "n"):
        token = _input_choice(
            "Token to receive",
            [("usdt", "USDT+ receive"), ("usdc", "USDC+ receive")],
            default="usdt",
        )
        cfg = TOKENS[token]
        amount = _input_float(f"Amount of {cfg['plus_name']} to receive")
        missions.append({"type": "receive", "token": token, "amount": amount})
        print(f"  {BOLD_GREEN}+ Added: receive {amount} {cfg['plus_name']}{RESET}")

    # ── Daily TX mission ──
    print(f"\n{BOLD_CYAN}  [5/5] Daily Transaction Mission{RESET}")
    if _input_yn("Add a Daily TX mission?", "y"):
        min_count = _input_int("Minimum transaction count", default=13)
        missions.append({"type": "daily_tx", "min_count": min_count})

    if not missions:
        log_error("No missions configured")
        return None, None

    # ── Summary of configured missions ──
    print(f"\n{BOLD_GREEN}  Configured {len(missions)} mission(s):{RESET}")
    for i, m in enumerate(missions, 1):
        token = m.get("token", "")
        amount = m.get("amount", m.get("min_count", ""))
        if m["type"] == "daily_tx":
            print(f"    {i}. Daily TX: >= {amount} transactions")
        else:
            cfg = TOKENS.get(token, {})
            plus_name = cfg.get("plus_name", f"{token.upper()}+")
            print(f"    {i}. {m['type'].title()} {amount} {plus_name}")

    # ── Settings ──
    has_mints = any(m["type"] == "mint" for m in missions)
    has_actions = any(m["type"] in ("stake", "send", "receive", "mint") for m in missions)

    if has_actions:
        print(f"\n{BOLD_CYAN}  Settings{RESET}")
        if has_mints:
            mint_per_tx = _input_float("Mint amount per transaction", default=100)
            if mint_per_tx < 10:
                log_warn(f"Mint per tx = {mint_per_tx} is very small — this will create many transactions!")
                mint_per_tx = _input_float("  Use a larger amount (recommended: 50-200)", default=100)
            settings["mint_per_tx"] = mint_per_tx
        settings["delay_min"] = _input_float("Min delay between txs (seconds)", default=5)
        settings["delay_max"] = _input_float("Max delay between txs (seconds)", default=12)

        # Estimate total transactions
        mint_per_tx_val = settings.get("mint_per_tx", 100)
        total_mint_needed = sum(m.get("amount", 0) for m in missions if m["type"] == "mint")
        est_mint_txs = max(1, math.ceil(total_mint_needed / mint_per_tx_val)) if total_mint_needed > 0 else 0
        est_other_txs = sum(1 for m in missions if m["type"] in ("stake", "send", "receive"))
        est_total = est_mint_txs + est_other_txs
        if est_total > 30:
            log_warn(f"Estimated ~{est_total} transactions — this will take a long time!")
            if not _input_yn("  Continue anyway?", "n"):
                return None, None

    return missions, settings


def load_missions(path="missions.json"):
    """Load missions config from JSON file. Returns (missions, settings) or None."""
    if not os.path.exists(path):
        log_error(f"Mission config not found: {path}")
        log_error("  Create missions.json with your mission requirements.")
        log_error("  See README or run with --help for format details.")
        return None

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    missions = data.get("missions", [])
    settings = {**DEFAULTS, **data.get("settings", {})}

    if not missions:
        log_error("No missions defined in config file")
        return None

    # Validate missions
    valid_types = {"mint", "stake", "send", "receive", "daily_tx"}
    clean_missions = []
    for i, m in enumerate(missions):
        if m.get("type") not in valid_types:
            log_warn(f"Mission #{i+1} has unknown type '{m.get('type')}', skipping")
            continue
        if m["type"] != "daily_tx":
            if m.get("token", "").lower() not in TOKENS:
                log_warn(f"Mission #{i+1} has unknown token '{m.get('token')}', skipping")
                continue
            if m.get("amount", 0) <= 0:
                log_warn(f"Mission #{i+1} has zero/negative amount, skipping")
                continue
            m["token"] = m["token"].lower()
        if m["type"] == "daily_tx" and m.get("min_count", 0) <= 0:
            log_warn(f"Mission #{i+1} daily_tx has zero/negative min_count, skipping")
            continue
        clean_missions.append(m)

    # Validate settings
    if settings.get("mint_per_tx", 100) <= 0:
        log_warn(f"mint_per_tx={settings['mint_per_tx']} is invalid, resetting to 100")
        settings["mint_per_tx"] = 100

    return clean_missions, settings


# ═══════════════════════════════════════════════════════════════════════
# Blockchain Helpers
# ═══════════════════════════════════════════════════════════════════════

def get_token_balance(rpc_url, address, token_addr):
    """Query ERC-20 token balance (balanceOf)."""
    padded = p32(int(address.lower().replace("0x", ""), 16))
    cd = "0x" + BALANCE_SELECTOR + padded
    result = rpc_call(rpc_url, "eth_call", [{"to": token_addr, "data": cd}, "latest"])
    if result and "result" in result:
        return int(result["result"], 16)
    return 0


def build_mint_calldata(caller, receiver, token_addr, token_amount, plus_amount):
    """Encode mint(tuple(address,address,address,uint256,uint256))."""
    parts = [MINT_SELECTOR]
    parts.append(p32(int(caller.lower().replace("0x", ""), 16)))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    parts.append(p32(int(token_addr.lower().replace("0x", ""), 16)))
    parts.append(p32(token_amount))
    parts.append(p32(plus_amount))
    return "0x" + "".join(parts)


def build_stake_calldata(amount_raw, receiver):
    """Encode deposit(uint256 assets, address receiver)."""
    parts = [DEPOSIT_SELECTOR]
    parts.append(p32(amount_raw))
    parts.append(p32(int(receiver.lower().replace("0x", ""), 16)))
    return "0x" + "".join(parts)


def build_send_calldata(recipient, amount_raw):
    """Encode transfer(address to, uint256 amount)."""
    parts = [TRANSFER_SELECTOR]
    parts.append(p32(int(recipient.lower().replace("0x", ""), 16)))
    parts.append(p32(amount_raw))
    return "0x" + "".join(parts)


# ═══════════════════════════════════════════════════════════════════════
# Mission Analysis
# ═══════════════════════════════════════════════════════════════════════

def analyze_missions(missions, settings, balances):
    """
    Analyze all missions and create an optimal execution plan.

    Merges send + receive per token (sending X to target satisfies both).
    Calculates mint requirements (total plus tokens needed minus existing).
    Adds extra mints if daily_tx minimum is not met.

    Args:
        missions:  List of mission dicts from config
        settings:  Settings dict
        balances:  {"usdt": float, "usdc": float, "usdt_plus": float, "usdc_plus": float}

    Returns:
        Plan dict with mints, stakes, sends, and total_txs
    """
    # ── Group missions by type and token ──
    mint_targets  = {}  # token -> total amount to mint (mission target)
    stake_needs   = {}  # token -> amount to stake
    send_needs    = {}  # token -> amount to send
    receive_needs = {}  # token -> amount to receive
    min_tx_count  = 0

    for m in missions:
        mtype = m["type"]
        token = m.get("token", "usdt")

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

    # ── Merge send + receive per token ──
    # From sender's perspective, "receive X at target" = "send X to target"
    effective_send = {}
    all_tokens = set(list(send_needs.keys()) + list(receive_needs.keys()))
    for token in all_tokens:
        s = send_needs.get(token, 0)
        r = receive_needs.get(token, 0)
        effective_send[token] = max(s, r)

    # ── Calculate mint requirements per token ──
    mint_per_tx = max(1, settings.get("mint_per_tx", DEFAULTS["mint_per_tx"]))

    plan_mints = {}
    for token in ["usdt", "usdc"]:
        plus_key = f"{token}_plus"
        existing = balances.get(plus_key, 0)

        # Total plus tokens needed = max(mint target, stake + send needs)
        total_needed = max(
            mint_targets.get(token, 0),
            stake_needs.get(token, 0) + effective_send.get(token, 0),
        )

        # Subtract existing plus-token balance
        mint_amount = max(0, total_needed - existing)

        if mint_amount > 0:
            tx_count = max(1, math.ceil(mint_amount / mint_per_tx))
            per_tx = mint_amount / tx_count  # exact per-tx to hit total
            plan_mints[token] = {
                "total": mint_amount,
                "tx_count": tx_count,
                "per_tx": per_tx,
            }
        else:
            plan_mints[token] = {"total": 0, "tx_count": 0, "per_tx": 0}

    # ── Build stake list ──
    plan_stakes = []
    for token, amount in stake_needs.items():
        if amount > 0:
            plan_stakes.append({"token": token, "amount": amount})

    # ── Build send list ──
    plan_sends = []
    for token, amount in effective_send.items():
        if amount > 0:
            plan_sends.append({"token": token, "amount": amount})

    # ── Count total txs ──
    total_txs = (
        sum(m["tx_count"] for m in plan_mints.values())
        + len(plan_stakes)
        + len(plan_sends)
    )

    # ── Add extra mints for daily_tx minimum if needed ──
    extra_mints = 0
    if total_txs < min_tx_count:
        extra_mints = min_tx_count - total_txs

        # Distribute extras evenly across both tokens
        per_token_extra = extra_mints // 2
        remainder = extra_mints % 2
        usdt_extra = per_token_extra
        usdc_extra = per_token_extra

        # Give remainder to token with fewer existing mints
        if remainder:
            if plan_mints["usdt"]["tx_count"] <= plan_mints["usdc"]["tx_count"]:
                usdt_extra += 1
            else:
                usdc_extra += 1

        for token, extra in [("usdt", usdt_extra), ("usdc", usdc_extra)]:
            if extra > 0:
                plan_mints[token]["tx_count"] += extra
                if plan_mints[token]["total"] > 0:
                    # Spread existing total across more txs
                    plan_mints[token]["per_tx"] = (
                        plan_mints[token]["total"] / plan_mints[token]["tx_count"]
                    )
                else:
                    # No existing mints; use mint_per_tx for extras
                    plan_mints[token]["total"] += extra * mint_per_tx
                    plan_mints[token]["per_tx"] = mint_per_tx

        total_txs = min_tx_count

    return {
        "mints": plan_mints,
        "stakes": plan_stakes,
        "sends": plan_sends,
        "total_txs": total_txs,
        "extra_mints_added": extra_mints,
        "min_tx_count": min_tx_count,
    }


def print_plan(plan, balances, dest_addr):
    """Pretty-print the execution plan with gas estimates."""
    mints  = plan["mints"]
    stakes = plan["stakes"]
    sends  = plan["sends"]

    print(f"\n{BOLD_GREEN}  📊 Execution Plan:{RESET}")
    print(f"{'─' * 70}")

    has_mints = any(m["tx_count"] > 0 for m in mints.values())
    if has_mints:
        for token in ["usdt", "usdc"]:
            m = mints[token]
            if m["tx_count"] > 0:
                cfg = TOKENS[token]
                print(
                    f"  {BOLD_WHITE}Mint {cfg['plus_name']:6s}: "
                    f"{m['tx_count']} tx × {m['per_tx']:.2f} = "
                    f"{m['total']:.2f} {cfg['name']}{RESET}"
                )

    if stakes:
        for s in stakes:
            cfg = TOKENS[s["token"]]
            print(
                f"  {BOLD_WHITE}Stake {cfg['plus_name']:5s}: "
                f"1 tx × {s['amount']:.2f}{RESET}"
            )

    if sends:
        for s in sends:
            cfg = TOKENS[s["token"]]
            print(
                f"  {BOLD_WHITE}Send {cfg['plus_name']:6s}: "
                f"1 tx × {s['amount']:.2f} → {dest_addr[:10]}...{RESET}"
            )

    print(f"{'─' * 70}")
    print(f"  {BOLD_GREEN}Total transactions: {plan['total_txs']}{RESET}")

    if plan["extra_mints_added"] > 0:
        print(
            f"  {BOLD_YELLOW}+ {plan['extra_mints_added']} extra mints "
            f"added for daily_tx minimum{RESET}"
        )

    if plan["min_tx_count"] > 0:
        print(f"  {BOLD_WHITE}Daily TX target: >= {plan['min_tx_count']}{RESET}")

    # Gas estimate
    mint_txs   = sum(m["tx_count"] for m in mints.values())
    stake_txs  = len(stakes)
    send_txs   = len(sends)
    total_gas  = mint_txs * GAS_MINT + stake_txs * GAS_STAKE + send_txs * GAS_SEND
    est_eth    = total_gas * 30e9 / 1e18  # assume ~30 gwei
    print(
        f"\n  {BOLD_YELLOW}⛽ Est. gas: ~{est_eth:.6f} ETH "
        f"({total_gas:,} gas x ~30 gwei){RESET}"
    )

    # Balance summary
    print(f"\n{BOLD_CYAN}  📦 Current Balances:{RESET}")
    eth_bal = balances.get("eth", 0)
    print(f"  {BOLD_WHITE}ETH      : {eth_bal:.8f}{RESET}")
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        base_bal = balances.get(token, 0)
        plus_bal = balances.get(f"{token}_plus", 0)
        print(
            f"  {BOLD_WHITE}{cfg['name']:5s}  : {base_bal:10.6f} | "
            f"{cfg['plus_name']:6s}: {plus_bal:10.6f}{RESET}"
        )
    print()


# ═══════════════════════════════════════════════════════════════════════
# Execution
# ═══════════════════════════════════════════════════════════════════════

def execute_mints(plan, pk, addr, rpc_url, settings):
    """Execute all mint transactions. Returns (ok_count, tx_count)."""
    mints = plan["mints"]
    delay_min = settings.get("delay_min", DEFAULTS["delay_min"])
    delay_max = settings.get("delay_max", DEFAULTS["delay_max"])
    total_txs = plan["total_txs"]

    tx_count = 0
    ok_count = 0

    for token in ["usdt", "usdc"]:
        m = mints[token]
        if m["tx_count"] == 0:
            continue

        cfg = TOKENS[token]
        token_raw  = int(m["per_tx"] * 10**cfg["decimals"])
        plus_raw   = token_raw * 10**(cfg["plus_decimals"] - cfg["decimals"])
        mint_cd    = build_mint_calldata(addr, addr, cfg["token"], token_raw, plus_raw)

        # Pre-check base token balance before starting this token's mints
        base_bal_raw = get_token_balance(rpc_url, addr, cfg["token"])
        base_bal = base_bal_raw / 10**cfg["decimals"]
        needed_total = m["tx_count"] * m["per_tx"]
        if base_bal < needed_total:
            log_warn(
                f"{cfg['name']} balance may be insufficient for all {m['tx_count']} mints. "
                f"Need {needed_total:.2f}, have {base_bal:.2f}. Will try anyway."
            )

        for i in range(1, m["tx_count"] + 1):
            tx_count += 1
            log_task(
                f"[{tx_count}/{total_txs}] Mint {cfg['plus_name']} "
                f"{i}/{m['tx_count']} | "
                f"{m['per_tx']:.2f} {cfg['name']} -> {cfg['plus_name']}"
            )

            result = send_transaction(
                rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
                chain_id=SEPOLIA_CHAIN_ID, pk=pk, address=addr,
                to_contract=cfg["plus"], value_wei=0,
                calldata=mint_cd,
                action_name=f"Mint {cfg['plus_name']} #{i}/{m['tx_count']}",
                gas_limit_override=GAS_MINT, proxy=None,
            )

            if result and result not in ("FAILED", "INSUFFICIENT", None):
                ok_count += 1
                log_success(f"  Mint {cfg['plus_name']} #{i} complete")
            else:
                log_error(f"  Mint {cfg['plus_name']} #{i} failed: {result}")
                if result == "INSUFFICIENT":
                    log_error("Insufficient ETH for gas, stopping mints")
                    return ok_count, tx_count

            if i < m["tx_count"]:
                delay = random.uniform(delay_min, delay_max)
                log_info(f"Waiting {delay:.1f}s...")
                time.sleep(delay)

    return ok_count, tx_count


def execute_stakes(plan, pk, addr, rpc_url, settings):
    """Execute all stake transactions. Returns (ok_count, tx_count)."""
    stakes = plan["stakes"]
    delay_min = settings.get("delay_min", DEFAULTS["delay_min"])
    delay_max = settings.get("delay_max", DEFAULTS["delay_max"])
    total_txs = plan["total_txs"]

    tx_count = 0
    ok_count = 0

    for idx, s in enumerate(stakes):
        token  = s["token"]
        amount = s["amount"]
        cfg    = TOKENS[token]

        # Re-check balance before staking (mints may have changed it)
        bal_raw = get_token_balance(rpc_url, addr, cfg["plus"])
        bal     = bal_raw / 10**cfg["plus_decimals"]

        actual_amount = min(amount, bal)
        if actual_amount <= 0:
            log_error(f"No {cfg['plus_name']} balance to stake, skipping")
            continue

        if actual_amount < amount:
            log_warn(
                f"Stake shortfall: need {amount:.6f}, have {bal:.6f}. "
                f"Staking {actual_amount:.6f}"
            )

        amount_raw = int(actual_amount * 10**cfg["plus_decimals"])
        stake_cd   = build_stake_calldata(amount_raw, addr)

        tx_count += 1
        log_task(
            f"[{tx_count}/{total_txs}] Stake {actual_amount:.6f} {cfg['plus_name']}"
        )

        result = send_transaction(
            rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
            chain_id=SEPOLIA_CHAIN_ID, pk=pk, address=addr,
            to_contract=cfg["stake_contract"], value_wei=0,
            calldata=stake_cd,
            action_name=f"Stake {actual_amount:.6f} {cfg['plus_name']}",
            gas_limit_override=GAS_STAKE, proxy=None,
        )

        if result and result not in ("FAILED", "INSUFFICIENT", None):
            ok_count += 1
            log_success(f"  Stake {cfg['plus_name']} complete")
        else:
            log_error(f"  Stake {cfg['plus_name']} failed: {result}")
            if result == "INSUFFICIENT":
                log_error("Insufficient ETH for gas, stopping")
                return ok_count, tx_count

        if idx < len(stakes) - 1:
            delay = random.uniform(delay_min, delay_max)
            log_info(f"Waiting {delay:.1f}s...")
            time.sleep(delay)

    return ok_count, tx_count


def execute_sends(plan, pk, addr, dest_addr, rpc_url, settings):
    """Execute all send transactions. Returns (ok_count, tx_count)."""
    sends = plan["sends"]
    delay_min = settings.get("delay_min", DEFAULTS["delay_min"])
    delay_max = settings.get("delay_max", DEFAULTS["delay_max"])
    total_txs = plan["total_txs"]

    tx_count = 0
    ok_count = 0

    for idx, s in enumerate(sends):
        token  = s["token"]
        amount = s["amount"]
        cfg    = TOKENS[token]

        # Re-check balance before sending
        bal_raw = get_token_balance(rpc_url, addr, cfg["plus"])
        bal     = bal_raw / 10**cfg["plus_decimals"]

        actual_amount = min(amount, bal)
        if actual_amount <= 0:
            log_error(f"No {cfg['plus_name']} balance to send, skipping")
            continue

        if actual_amount < amount:
            log_warn(
                f"Send shortfall: need {amount:.6f}, have {bal:.6f}. "
                f"Sending {actual_amount:.6f}"
            )

        amount_raw = int(actual_amount * 10**cfg["plus_decimals"])
        send_cd    = build_send_calldata(dest_addr, amount_raw)

        tx_count += 1
        log_task(
            f"[{tx_count}/{total_txs}] Send {actual_amount:.6f} "
            f"{cfg['plus_name']} -> {dest_addr[:10]}..."
        )

        result = send_transaction(
            rpc_url=rpc_url, explorer_url=SEPOLIA_EXPLORER,
            chain_id=SEPOLIA_CHAIN_ID, pk=pk, address=addr,
            to_contract=cfg["plus"], value_wei=0,
            calldata=send_cd,
            action_name=f"Send {actual_amount:.6f} {cfg['plus_name']}",
            gas_limit_override=GAS_SEND, proxy=None,
        )

        if result and result not in ("FAILED", "INSUFFICIENT", None):
            ok_count += 1
            log_success(f"  Send {cfg['plus_name']} complete")
        else:
            log_error(f"  Send {cfg['plus_name']} failed: {result}")
            if result == "INSUFFICIENT":
                log_error("Insufficient ETH for gas, stopping")
                return ok_count, tx_count

        if idx < len(sends) - 1:
            delay = random.uniform(delay_min, delay_max)
            log_info(f"Waiting {delay:.1f}s...")
            time.sleep(delay)

    return ok_count, tx_count


def execute_plan(plan, pk, addr, dest_addr, rpc_url, settings):
    """Execute the full mission plan. Returns (total_ok, total_tx)."""
    total_ok  = 0
    total_tx  = 0

    # ── Phase 1: Mints ──
    has_mints = any(m["tx_count"] > 0 for m in plan["mints"].values())
    if has_mints:
        print(f"\n{BOLD_MAGENTA}{'━' * 70}{RESET}")
        print(f"{BOLD_YELLOW}  [Phase 1/3] Mint (Token Conversion){RESET}")
        print(f"{BOLD_MAGENTA}{'━' * 70}{RESET}")

        ok, tx = execute_mints(plan, pk, addr, rpc_url, settings)
        total_ok += ok
        total_tx += tx

    # ── Phase 2: Stakes ──
    if plan["stakes"]:
        print(f"\n{BOLD_MAGENTA}{'━' * 70}{RESET}")
        print(f"{BOLD_YELLOW}  [Phase 2/3] Stake{RESET}")
        print(f"{BOLD_MAGENTA}{'━' * 70}{RESET}")

        ok, tx = execute_stakes(plan, pk, addr, rpc_url, settings)
        total_ok += ok
        total_tx += tx

    # ── Phase 3: Sends ──
    if plan["sends"]:
        print(f"\n{BOLD_MAGENTA}{'━' * 70}{RESET}")
        print(f"{BOLD_YELLOW}  [Phase 3/3] Send{RESET}")
        print(f"{BOLD_MAGENTA}{'━' * 70}{RESET}")

        ok, tx = execute_sends(plan, pk, addr, dest_addr, rpc_url, settings)
        total_ok += ok
        total_tx += tx

    return total_ok, total_tx


# ═══════════════════════════════════════════════════════════════════════
# Final Report
# ═══════════════════════════════════════════════════════════════════════

def print_final_report(rpc_url, addr, dest_addr, total_ok, total_tx, missions, plan, start_balances):
    """Print final balances and mission completion status."""
    print(f"\n{BOLD_GREEN}{'=' * 70}{RESET}")
    print(f"{BOLD_GREEN}  🎉 All tasks complete!{RESET}")
    print(f"  {BOLD_WHITE}Total txs : {total_tx}{RESET}")
    print(f"  {BOLD_GREEN}Success   : {total_ok}{RESET}")
    fail = total_tx - total_ok
    if fail > 0:
        print(f"  {BOLD_RED}Failed    : {fail}{RESET}")

    # ── Mission status ──
    print(f"\n{BOLD_CYAN}  📋 Mission Status:{RESET}")
    for m in missions:
        mtype  = m["type"]
        token  = m.get("token", "")
        amount = m.get("amount", 0)
        label  = m.get("label", f"{mtype}: {amount}")

        if mtype == "daily_tx":
            txs = plan["total_txs"]
            target = plan["min_tx_count"]
            status = "DONE" if txs >= target else "INCOMPLETE"
            color = BOLD_GREEN if txs >= target else BOLD_RED
            print(f"  {color}{status}{RESET}  {BOLD_WHITE}{label} ({txs}/{target} txs){RESET}")
        elif mtype == "mint":
            cfg = TOKENS.get(token, {})
            plus_name = cfg.get("plus_name", f"{token.upper()}+")
            existing = start_balances.get(f"{token}_plus", 0)
            plan_mint = plan["mints"].get(token, {}).get("total", 0)
            will_have = existing + plan_mint
            status = "DONE" if will_have >= amount else "PARTIAL"
            color = BOLD_GREEN if will_have >= amount else BOLD_YELLOW
            print(
                f"  {color}{status}{RESET}  {BOLD_WHITE}{label}"
                f" (will have {will_have:.2f}/{amount} {plus_name}){RESET}"
            )
        elif mtype == "stake":
            cfg = TOKENS.get(token, {})
            plus_name = cfg.get("plus_name", f"{token.upper()}+")
            staked = sum(s["amount"] for s in plan["stakes"] if s["token"] == token)
            status = "DONE" if staked >= amount else "PARTIAL"
            color = BOLD_GREEN if staked >= amount else BOLD_YELLOW
            print(
                f"  {color}{status}{RESET}  {BOLD_WHITE}{label}"
                f" (staking {staked:.2f}/{amount} {plus_name}){RESET}"
            )
        elif mtype in ("send", "receive"):
            cfg = TOKENS.get(token, {})
            plus_name = cfg.get("plus_name", f"{token.upper()}+")
            sent = max(
                (s["amount"] for s in plan["sends"] if s["token"] == token),
                default=0,
            )
            status = "DONE" if sent >= amount else "PARTIAL"
            color = BOLD_GREEN if sent >= amount else BOLD_YELLOW
            print(
                f"  {color}{status}{RESET}  {BOLD_WHITE}{label}"
                f" (sending {sent:.2f}/{amount} {plus_name}){RESET}"
            )

    # ── Final balances ──
    eth_bal = get_balance_eth(rpc_url, addr)
    print(f"\n{BOLD_CYAN}  📊 Final Balances:{RESET}")
    print(f"  {BOLD_WHITE}ETH       : {eth_bal:.8f}{RESET}")

    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        base_bal = get_token_balance(rpc_url, addr, cfg["token"]) / 10**cfg["decimals"]
        plus_bal = get_token_balance(rpc_url, addr, cfg["plus"]) / 10**cfg["plus_decimals"]
        dest_bal = get_token_balance(rpc_url, dest_addr, cfg["plus"]) / 10**cfg["plus_decimals"]
        print(
            f"  {BOLD_WHITE}{cfg['name']:5s}  : {base_bal:.6f} | "
            f"{cfg['plus_name']:6s}: {plus_bal:.6f} | "
            f"Target {cfg['plus_name']}: {dest_bal:.6f}{RESET}"
        )

    print(f"{BOLD_GREEN}{'=' * 70}{RESET}\n")


# ═══════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Smart Mission Runner — reads missions.json and executes all missions"
    )
    parser.add_argument("--auto", action="store_true",
                        help="Auto mode: skip confirmation prompts")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show execution plan without executing")
    parser.add_argument("--config", default="missions.json",
                        help="Path to missions config (default: missions.json)")
    args = parser.parse_args()

    banner()
    print(f"  {BOLD_WHITE}Network : Sepolia Testnet (Chain ID {SEPOLIA_CHAIN_ID}){RESET}")
    print(f"  {BOLD_WHITE}Feature : Smart Mission Runner{RESET}")
    if args.dry_run:
        print(f"  {BOLD_YELLOW}Mode    : Dry Run (plan only){RESET}\n")
    elif args.auto:
        print(f"  {BOLD_GREEN}Mode    : Auto{RESET}\n")
    else:
        print(f"  {BOLD_YELLOW}Mode    : Interactive{RESET}\n")

    # ── Load wallet ──
    pk = config.load_master_key()
    if not pk:
        log_error("No private key found. Add it to master_privatekey.txt")
        log_error("  or set FUNDING_PRIVATE_KEY=0x... in .env")
        sys.exit(1)

    addr = private_key_to_address(pk)
    wallets = config.load_wallets()

    if not wallets:
        log_error("No target wallet found. Add addresses to wallets.txt")
        sys.exit(1)

    # ── Find working RPC ──
    log_task("Scanning for available RPC nodes...")
    rpc_url = find_working_rpc(DEFAULT_RPC_ENDPOINTS)
    if not rpc_url:
        log_error("All RPC nodes are unavailable. Check your network connection.")
        sys.exit(1)

    # ── Query balances (needed before interactive input) ──
    log_task("Querying token balances...")
    balances_start = {}
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        balances_start[token] = get_token_balance(rpc_url, addr, cfg["token"]) / 10**cfg["decimals"]
        balances_start[f"{token}_plus"] = get_token_balance(rpc_url, addr, cfg["plus"]) / 10**cfg["plus_decimals"]
    balances_start["eth"] = get_balance_eth(rpc_url, addr)

    # ── Show wallet & balances BEFORE configuration ──
    dest_addr = wallets[0]  # temporary; updated after settings load

    print(f"\n{BOLD_CYAN}{'=' * 70}{RESET}")
    print(f"{BOLD_GREEN}  🔥 Smart Mission Runner — Sepolia{RESET}")
    print(f"  {BOLD_WHITE}Wallet : {addr}{RESET}")
    print(f"  {BOLD_WHITE}Target : {dest_addr}{RESET}")
    print(f"  {BOLD_WHITE}ETH    : {balances_start['eth']:.8f}{RESET}")
    for token in ["usdt", "usdc"]:
        cfg = TOKENS[token]
        print(
            f"  {BOLD_WHITE}{cfg['name']:5s} : {balances_start[token]:.6f} | "
            f"{cfg['plus_name']:6s} : {balances_start[f'{token}_plus']:.6f}{RESET}"
        )
    print(f"{BOLD_CYAN}{'=' * 70}{RESET}")

    # ── Load or configure missions ──
    if args.auto or args.dry_run:
        # Auto/dry-run mode: load from config file
        result = load_missions(args.config)
        if not result:
            sys.exit(1)
        missions, settings = result

        print(f"  {BOLD_WHITE}Missions loaded: {len(missions)}{RESET}")
        for m in missions:
            label = m.get(
                "label",
                f"{m['type']}: {m.get('token', '')} {m.get('amount', m.get('min_count', ''))}"
            )
            print(f"    * {label}")
        print()
    else:
        # Interactive mode: prompt user for parameters
        missions, settings = interactive_configure(balances_start)
        if not missions:
            sys.exit(1)

    # Resolve target wallet from settings
    target_idx = settings.get("target_wallet_index", 0)
    dest_addr = wallets[target_idx % len(wallets)]

    # ── Analyze missions -> create plan ──
    plan = analyze_missions(missions, settings, balances_start)
    print_plan(plan, balances_start, dest_addr)

    # ── Dry run exit ──
    if args.dry_run:
        log_info("Dry run complete. No transactions executed.")
        sys.exit(0)

    # ── Confirm execution ──
    auto_confirm = settings.get("auto_confirm", False)
    if not auto_confirm and not args.auto:
        confirm = input(f"  {BOLD_WHITE}Execute plan? (y/n): {RESET}").strip().lower()
        if confirm not in ("y", "yes"):
            log_info("Execution cancelled")
            sys.exit(0)

    # ── Execute ──
    total_ok, total_tx = execute_plan(plan, pk, addr, dest_addr, rpc_url, settings)

    # ── Final report ──
    print_final_report(rpc_url, addr, dest_addr, total_ok, total_tx, missions, plan, balances_start)

    sys.exit(0 if total_ok == total_tx else 1)


if __name__ == "__main__":
    main()
