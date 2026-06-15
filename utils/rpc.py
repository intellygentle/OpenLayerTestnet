# import sys
# import time
# import requests
# from utils.display import (
#     log_warn, log_error, log_info, log_success, log_process,
#     BOLD_WHITE, BOLD_GREEN, BOLD_CYAN, BOLD_YELLOW, RESET,
# )
# from utils.proxy import build_requests_proxies
# from utils.messages import (
#     explain_exception, explain_rpc_method,
#     explain_broadcast_error,
# )

# # ============================================================
# # RPC 调用
# # ============================================================
# def rpc_call(rpc_url, method, params=None, retries=5, timeout=60, proxy=None):
#     if params is None:
#         params = []
#     payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
#     headers = {
#         "Content-Type": "application/json",
#         "Accept": "*/*",
#         "User-Agent": "Mozilla/5.0",
#     }
#     proxies = build_requests_proxies(proxy)
#     for attempt in range(1, retries + 1):
#         try:
#             resp = requests.post(
#                 rpc_url, json=payload, headers=headers,
#                 timeout=timeout, proxies=proxies,
#             )
#             resp.raise_for_status()
#             return resp.json()
#         except requests.exceptions.Timeout:
#             log_warn(f"[{explain_rpc_method(method)}] 连接超时（{attempt}/{retries}），正在重试...")
#             time.sleep(3 * attempt)
#         except Exception as e:
#             short, hint = explain_exception(e)
#             log_warn(f"[{explain_rpc_method(method)}] {short}（{attempt}/{retries}）")
#             if attempt == retries:
#                 log_warn(f"  💡 {hint}")
#             time.sleep(2 * attempt)
#     log_error(f"[{explain_rpc_method(method)}] {retries} 次重试均失败")
#     log_error("  💡 请检查网络，或清空 proxy.txt 改用直连")
#     return None

# def get_nonce(rpc_url, address, proxy=None):
#     r = rpc_call(rpc_url, "eth_getTransactionCount", [address, "pending"], proxy=proxy)
#     if r and "result" in r:
#         return int(r["result"], 16)
#     return None

# def get_balance(rpc_url, address, proxy=None):
#     r = rpc_call(rpc_url, "eth_getBalance", [address, "latest"], proxy=proxy)
#     if r and "result" in r:
#         return int(r["result"], 16)
#     return 0

# def get_balance_eth(rpc_url, address, proxy=None):
#     return get_balance(rpc_url, address, proxy) / 10**18


# def find_working_rpc(rpc_list):
#     """尝试 RPC 列表，返回第一个可用的 URL，全失败返回 None"""
#     for rpc in rpc_list:
#         try:
#             result = rpc_call(rpc, "eth_blockNumber", timeout=8)
#             if result and "result" in result:
#                 blk = int(result["result"], 16)
#                 log_info(f"RPC 连接成功: {rpc[:50]}... (区块 {blk})")
#                 return rpc
#         except Exception:
#             pass
#         log_warn(f"RPC 不可用: {rpc[:60]}...")
#     return None


# def get_block_number(rpc_url, proxy=None):
#     r = rpc_call(rpc_url, "eth_blockNumber", [], proxy=proxy)
#     if r and "result" in r:
#         return int(r["result"], 16)
#     return 0

# def get_gas_price(rpc_url, proxy=None):
#     r = rpc_call(rpc_url, "eth_gasPrice", [], proxy=proxy)
#     if r and "result" in r:
#         return int(r["result"], 16)
#     return 10000000

# def estimate_gas(rpc_url, tx, proxy=None):
#     r = rpc_call(rpc_url, "eth_estimateGas", [tx], proxy=proxy)
#     if r and "result" in r:
#         return int(r["result"], 16), None
#     if r and "error" in r:
#         e = r["error"]
#         return None, {"message": e.get("message", "未知错误"), "data": e.get("data", "")}
#     return None, {"message": "未知 RPC 错误", "data": ""}

# def send_raw_tx(rpc_url, signed_tx, retries=5, proxy=None):
#     for attempt in range(1, retries + 1):
#         log_info(f"广播尝试 {attempt}/{retries}...")
#         r = rpc_call(rpc_url, "eth_sendRawTransaction", [signed_tx], retries=1, timeout=90, proxy=proxy)
#         if r:
#             if "result" in r:
#                 return r["result"], None
#             if "error" in r:
#                 err = r["error"]
#                 msg = err.get("message", "")
#                 if "already known" in msg.lower() or "nonce too low" in msg.lower():
#                     return None, err
#                 if "insufficient funds" in msg.lower():
#                     return None, err
#                 if "timeout" in msg.lower() or "deadline" in msg.lower():
#                     log_warn(f"[广播交易] 节点响应超时，{5 * attempt} 秒后重试...")
#                     time.sleep(5 * attempt)
#                     continue
#                 short, hint = explain_broadcast_error(msg)
#                 log_error(f"[广播交易] {short}")
#                 log_error(f"  💡 {hint}")
#                 return None, err
#         else:
#             log_warn(f"[广播交易] 节点无响应，{5 * attempt} 秒后重试...")
#             time.sleep(5 * attempt)
#     log_error(f"[广播交易] {retries} 次广播均失败")
#     return None, {"message": f"{retries} 次尝试后失败"}

# def get_tx_receipt(rpc_url, tx_hash, proxy=None):
#     r = rpc_call(rpc_url, "eth_getTransactionReceipt", [tx_hash], proxy=proxy)
#     if r and "result" in r:
#         return r["result"]
#     return None

# def wait_for_confirmation(rpc_url, tx_hash, proxy=None, timeout=300):
#     log_process("等待链上确认...")
#     for i in range(timeout // 3):
#         time.sleep(3)
#         receipt = get_tx_receipt(rpc_url, tx_hash, proxy)
#         if receipt:
#             status = int(receipt.get("status", "0x0"), 16)
#             block_num = int(receipt.get("blockNumber", "0x0"), 16)
#             gas_used = int(receipt.get("gasUsed", "0x0"), 16)
#             print()
#             if status == 1:
#                 log_success("链上确认成功！")
#                 print(f"  {BOLD_WHITE}状态  : {BOLD_GREEN}成功{RESET}")
#                 print(f"  {BOLD_WHITE}区块  : {BOLD_CYAN}{block_num}{RESET}")
#                 print(f"  {BOLD_WHITE}Gas   : {BOLD_YELLOW}{gas_used}{RESET}")
#                 return True, block_num, gas_used
#             log_error("链上执行失败（合约回滚），Gas 费已扣除")
#             print(f"  {BOLD_WHITE}区块  : {BOLD_CYAN}{block_num}{RESET}")
#             print(f"  {BOLD_WHITE}Gas   : {BOLD_YELLOW}{gas_used}{RESET}")
#             return False, block_num, gas_used
#         sys.stdout.write(f"\r  {BOLD_YELLOW}[等待确认] 已等待 {(i + 1) * 3} 秒...{RESET}    ")
#         sys.stdout.flush()
#     print()
#     log_warn("等待确认超时，请到区块浏览器手动查看")
#     return None, 0, 0

# # ============================================================
# # 合约部署
# # ============================================================
# def deploy_contract(rpc_url, explorer_url, chain_id, gas_multiplier,
#                     pk, address, bytecode, action_name="部署合约",
#                     gas_limit_override=None, proxy=None):
#     from utils.crypto import sign_transaction

#     if not bytecode.startswith("0x"):
#         bytecode = "0x" + bytecode

#     print(f"\n  {BOLD_CYAN}--- {action_name} ---{RESET}")
#     nonce = get_nonce(rpc_url, address, proxy)
#     if nonce is None:
#         log_error("无法获取 Nonce，部署失败")
#         return None, None

#     gas_price = get_gas_price(rpc_url, proxy)
#     if gas_limit_override:
#         gas_limit = gas_limit_override
#     else:
#         estimated, _ = estimate_gas(rpc_url, {"from": address, "data": bytecode}, proxy=proxy)
#         gas_limit = int(estimated * gas_multiplier) if estimated else 400000

#     required = gas_limit * gas_price
#     if get_balance(rpc_url, address, proxy) < required:
#         log_error(f"余额不足，部署需要约 {required / 10**18:.8f} zkLTC Gas")
#         return None, None

#     tx = {"nonce": nonce, "gasPrice": gas_price, "gas": gas_limit,
#           "to": "", "value": 0, "data": bytecode}
#     log_process("正在签名部署交易...")
#     try:
#         signed = sign_transaction(tx, pk, chain_id)
#     except Exception as e:
#         log_error(f"签名失败: {e}")
#         return None, None

#     log_process("正在广播部署交易...")
#     tx_hash, err = send_raw_tx(rpc_url, signed, proxy=proxy)
#     if not tx_hash:
#         log_error(f"部署广播失败: {err.get('message', '') if err else ''}")
#         return None, None

#     print(f"  {BOLD_WHITE}哈希  : {BOLD_CYAN}{tx_hash}{RESET}")
#     print(f"  {BOLD_WHITE}浏览器: {BOLD_CYAN}{explorer_url}/tx/{tx_hash}{RESET}")
#     confirmed, _, _ = wait_for_confirmation(rpc_url, tx_hash, proxy)
#     if not confirmed:
#         log_warn("部署交易未确认，请手动检查")
#         return tx_hash, None

#     receipt = get_tx_receipt(rpc_url, tx_hash, proxy)
#     if receipt and receipt.get("contractAddress"):
#         contract_addr = receipt["contractAddress"]
#         log_success(f"合约已部署: {contract_addr}")
#         return tx_hash, contract_addr
#     return tx_hash, None

# # ============================================================
# # 发送交易
# # ============================================================


# def send_transaction(rpc_url, explorer_url, chain_id,
#                      pk, address, to_contract, value_wei,
#                      calldata, action_name, gas_limit_override=None, proxy=None):
#     from utils.crypto import sign_transaction

#     print(f"\n  {BOLD_CYAN}--- 构建交易: {action_name} ---{RESET}")
#     blk = get_block_number(rpc_url, proxy)
#     if blk:
#         print(f"  {BOLD_WHITE}区块  : {BOLD_CYAN}{blk}{RESET}")

#     nonce = get_nonce(rpc_url, address, proxy)
#     if nonce is None:
#         log_error("无法获取 Nonce，RPC 连接失败")
#         return None
#     print(f"  {BOLD_WHITE}Nonce : {nonce}{RESET}")

#     gas_price = get_gas_price(rpc_url, proxy)
#     print(f"  {BOLD_WHITE}Gas价格: {gas_price / 10**9:.4f} Gwei{RESET}")

#     if gas_limit_override:
#         gas_limit = gas_limit_override
#     else:
#         gas_limit = 500000
#         log_warn("未指定 Gas，使用默认值 500000")
#     print(f"  {BOLD_WHITE}Gas   : {gas_limit}{RESET}")

#     current_bal = get_balance(rpc_url, address, proxy)
#     required = value_wei + gas_limit * gas_price
#     if current_bal < required:
#         log_error("zkLTC 余额不足")
#         log_error(f"  当前余额: {current_bal / 10**18:.8f} zkLTC")
#         log_error(f"  需要至少: {required / 10**18:.8f} zkLTC（含转账 + Gas）")
#         return "INSUFFICIENT"

#     print(f"  {BOLD_WHITE}金额  : {BOLD_GREEN}{value_wei / 10**18:.8f} zkLTC{RESET}")
#     print(f"  {BOLD_WHITE}目标  : {BOLD_CYAN}{to_contract}{RESET}")

#     tx = {"nonce": nonce, "gasPrice": gas_price, "gas": gas_limit,
#           "to": to_contract, "value": value_wei, "data": calldata}

#     log_process("正在签名...")
#     try:
#         signed = sign_transaction(tx, pk, chain_id)
#         log_success("签名完成")
#     except Exception as e:
#         log_error(f"签名失败: {e}")
#         log_error("  💡 请检查 master_privatekey.txt 中的私钥是否正确")
#         return None

#     log_process("正在广播...")
#     tx_hash, err = send_raw_tx(rpc_url, signed, proxy=proxy)
#     if not tx_hash:
#         emsg = err.get("message", "") if err else ""
#         short, hint = explain_broadcast_error(emsg)
#         log_error(f"[广播交易] {short}")
#         log_error(f"  💡 {hint}")
#         if err and "insufficient funds" in emsg.lower():
#             return "INSUFFICIENT"
#         return None

#     print(f"\n{BOLD_GREEN}{'=' * 70}{RESET}")
#     log_success(f"交易已发送: {action_name}")
#     print(f"  {BOLD_WHITE}哈希  : {BOLD_CYAN}{tx_hash}{RESET}")
#     print(f"  {BOLD_WHITE}浏览器: {BOLD_CYAN}{explorer_url}/tx/{tx_hash}{RESET}")
#     print(f"{BOLD_GREEN}{'=' * 70}{RESET}")

#     confirmed, _, _ = wait_for_confirmation(rpc_url, tx_hash, proxy)
#     if confirmed is True:
#         return tx_hash
#     if confirmed is False:
#         return "FAILED"
#     log_warn(f"交易已发出但未确认，请查看: {explorer_url}/tx/{tx_hash}")
#     return tx_hash

"""
RPC utilities for Ethereum Sepolia testnet.
Handles RPC calls, gas estimation, transaction signing, and broadcasting.
"""
import json
import time
import requests

from utils.crypto import sign_transaction
from utils.display import (
    BOLD_CYAN, BOLD_GREEN, BOLD_WHITE, BOLD_YELLOW, RESET,
    log_error, log_info, log_success, log_task, log_warn, log_process
)

# ── Network-specific safety floors ──
MIN_GAS_PRICE_GWEI = 5          # absolute floor in gwei
GAS_PRICE_MULTIPLIER = 2.0      # 2× buffer on fetched price
MAX_GAS_PRICE_GWEI = 500        # safety cap to prevent accidents


def rpc_call(rpc_url, method, params, proxy=None, timeout=15):
    """Make a JSON-RPC call."""
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }
    proxies = {"http": proxy, "https": proxy} if proxy else None
    try:
        resp = requests.post(
            rpc_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            proxies=proxies,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            log_error(f"RPC error: {data['error']}")
            return None
        return data
    except requests.exceptions.Timeout:
        log_warn(f"RPC timeout: {rpc_url}")
        return None
    except Exception as e:
        log_warn(f"RPC failed: {rpc_url} — {e}")
        return None


def find_working_rpc(rpc_list, proxy=None):
    """Test RPCs and return the first working one."""
    for url in rpc_list:
        result = rpc_call(url, "eth_blockNumber", [], proxy=proxy, timeout=8)
        if result and "result" in result:
            log_success(f"RPC 可用: {url}")
            return url
    return None


def get_balance_eth(rpc_url, address, proxy=None):
    """Get ETH balance in ether."""
    result = rpc_call(rpc_url, "eth_getBalance", [address, "latest"], proxy=proxy)
    if result and "result" in result:
        wei = int(result["result"], 16)
        return wei / 10**18
    return 0.0


def get_block_number(rpc_url, proxy=None):
    """Get current block number."""
    result = rpc_call(rpc_url, "eth_blockNumber", [], proxy=proxy)
    if result and "result" in result:
        return int(result["result"], 16)
    return None


def get_gas_price(rpc_url, proxy=None):
    """
    Fetch current gas price from network with smart pricing.
    Returns price in wei that is safe to use.
    """
    result = rpc_call(rpc_url, "eth_gasPrice", [], proxy=proxy)
    if not result or "result" not in result:
        log_warn("无法获取 gas price，使用默认值 10 gwei")
        return 10 * 10**9

    network_gas = int(result["result"], 16)
    network_gwei = network_gas / 10**9

    # Apply multiplier
    adjusted = int(network_gas * GAS_PRICE_MULTIPLIER)
    adjusted_gwei = adjusted / 10**9

    # Enforce minimum floor (critical for Sepolia)
    min_wei = MIN_GAS_PRICE_GWEI * 10**9
    if adjusted < min_wei:
        log_info(f"网络 gas {adjusted_gwei:.2f} gwei 低于安全值，提升至 {MIN_GAS_PRICE_GWEI} gwei")
        adjusted = min_wei
        adjusted_gwei = MIN_GAS_PRICE_GWEI

    # Enforce maximum cap
    max_wei = MAX_GAS_PRICE_GWEI * 10**9
    if adjusted > max_wei:
        log_warn(f"网络 gas {adjusted_gwei:.2f} gwei 超过上限，限制为 {MAX_GAS_PRICE_GWEI} gwei")
        adjusted = max_wei
        adjusted_gwei = MAX_GAS_PRICE_GWEI

    log_info(f"网络 Gas: {network_gwei:.2f} gwei → 使用: {adjusted_gwei:.2f} gwei (×{GAS_PRICE_MULTIPLIER})")
    return adjusted


def get_nonce(rpc_url, address, proxy=None):
    """
    Get next nonce from network (includes pending transactions).
    Falls back to 'latest' if 'pending' fails.
    """
    for tag in ("pending", "latest"):
        result = rpc_call(rpc_url, "eth_getTransactionCount", [address, tag], proxy=proxy)
        if result and "result" in result:
            nonce = int(result["result"], 16)
            log_info(f"自动 Nonce ({tag}): {nonce}")
            return nonce
    log_error("无法获取 Nonce")
    return None


def estimate_gas(rpc_url, tx_dict, proxy=None):
    """Estimate gas for a transaction."""
    result = rpc_call(rpc_url, "eth_estimateGas", [tx_dict], proxy=proxy)
    if result and "result" in result:
        return int(result["result"], 16)
    return None


def send_raw_tx(rpc_url, signed_tx_hex, proxy=None):
    """Broadcast a raw signed transaction."""
    result = rpc_call(rpc_url, "eth_sendRawTransaction", [signed_tx_hex], proxy=proxy)
    if result and "result" in result:
        return result["result"], None  # tx hash, no error
    if result and "error" in result:
        return None, result["error"]
    return None, None


def explain_broadcast_error(emsg):
    """Return (short_msg, hint) for common broadcast errors."""
    emsg = (emsg or "").lower()
    if "insufficient funds" in emsg:
        return "余额不足", "请确保钱包中有足够的 ETH 支付 Gas"
    if "nonce too low" in emsg:
        return "Nonce 过低", "该 Nonce 已经被使用，请等待或获取最新 Nonce"
    if "replacement transaction underpriced" in emsg:
        return "替换交易 Gas 不足", "加速/取消交易时，新交易的 Gas 价格必须比旧交易高至少 10%"
    if "intrinsic gas too low" in emsg:
        return "Gas Limit 过低", "请提高 gas_limit_override"
    if "already known" in emsg:
        return "交易已存在", "该交易已在内存池中，无需重发"
    return f"广播失败: {emsg[:60]}", "请检查 RPC 连接和交易参数"


def wait_for_confirmation(rpc_url, tx_hash, proxy=None, timeout_sec=120, poll_interval=5):
    """
    Wait for transaction receipt.
    Returns (confirmed_bool, status_int, block_int)
    confirmed_bool: True=success, False=reverted, None=timeout
    """
    start = time.time()
    elapsed = 0
    while elapsed < timeout_sec:
        receipt = rpc_call(rpc_url, "eth_getTransactionReceipt", [tx_hash], proxy=proxy)
        if receipt and receipt.get("result"):
            r = receipt["result"]
            status = int(r.get("status", "0x1"), 16)
            block = int(r.get("blockNumber", "0x0"), 16)
            return (status == 1), status, block
        time.sleep(poll_interval)
        elapsed = time.time() - start
        if elapsed % 15 < poll_interval:
            log_process(f"等待确认... 已等待 {int(elapsed)} 秒")
    return None, None, None


def send_transaction(
    rpc_url,
    explorer_url,
    chain_id,
    pk,
    address,
    to_contract,
    value_wei,
    calldata,
    action_name,
    gas_limit_override=None,
    gas_price=None,          # optional override
    nonce=None,              # optional override
    proxy=None,
):
    """
    Build, sign, and send an Ethereum transaction.
    Gas price and nonce are determined automatically from the network
    unless explicitly provided.
    """
    print(f"\n  {BOLD_CYAN}--- 构建交易: {action_name} ---{RESET}")
    blk = get_block_number(rpc_url, proxy)
    if blk:
        print(f"  {BOLD_WHITE}区块  : {BOLD_CYAN}{blk}{RESET}")

    # ── Auto Nonce ──
    if nonce is None:
        nonce = get_nonce(rpc_url, address, proxy)
        if nonce is None:
            log_error("无法获取 Nonce，RPC 连接失败")
            return None
    print(f"  {BOLD_WHITE}Nonce : {nonce}{RESET}")

    # ── Auto Gas Price (with safety floor) ──
    if gas_price is None:
        gas_price = get_gas_price(rpc_url, proxy)
    print(f"  {BOLD_WHITE}Gas价格: {gas_price / 10**9:.4f} Gwei{RESET}")

    # ── Gas Limit ──
    if gas_limit_override:
        gas_limit = gas_limit_override
    else:
        gas_limit = 500000
        log_warn("未指定 Gas，使用默认值 500000")
    print(f"  {BOLD_WHITE}Gas   : {gas_limit}{RESET}")

    # ── Balance check (ETH for gas) ──
    current_bal = get_balance_eth(rpc_url, address, proxy)
    required_eth = (value_wei + gas_limit * gas_price) / 10**18
    if current_bal < required_eth:
        log_error("ETH 余额不足支付 Gas")
        log_error(f"  当前余额: {current_bal:.8f} ETH")
        log_error(f"  需要至少: {required_eth:.8f} ETH（含转账 + Gas）")
        return "INSUFFICIENT"

    # ── FIX: Show token amount if ERC-20 transfer ──
    # For ERC-20 transfers, value_wei is 0, so extract amount from calldata
    if value_wei == 0 and calldata and len(calldata) >= 138:
        try:
            amount_raw = int(calldata[-64:], 16)
            # Try common decimals: 6 (USDC), 18 (most ERC-20)
            # Display both for clarity
            amount_6 = amount_raw / 10**6
            amount_18 = amount_raw / 10**18
            if amount_6 >= 0.000001 and amount_6 == int(amount_6) or amount_6 > 1:
                print(f"  {BOLD_WHITE}金额  : {BOLD_GREEN}{amount_6:.6f} USDC+ (6 decimals){RESET}")
            elif amount_18 >= 0.000000000001:
                print(f"  {BOLD_WHITE}金额  : {BOLD_GREEN}{amount_18:.18f} tokens (18 decimals){RESET}")
            else:
                print(f"  {BOLD_WHITE}金额  : {BOLD_GREEN}{amount_raw} raw{RESET}")
        except:
            print(f"  {BOLD_WHITE}金额  : {BOLD_GREEN}0 ETH (ERC-20 代币转账){RESET}")
    else:
        print(f"  {BOLD_WHITE}金额  : {BOLD_GREEN}{value_wei / 10**18:.8f} ETH{RESET}")

    print(f"  {BOLD_WHITE}目标  : {BOLD_CYAN}{to_contract}{RESET}")

    # ── Build & Sign ──
    tx = {
        "nonce": nonce,
        "gasPrice": gas_price,
        "gas": gas_limit,
        "to": to_contract,
        "value": value_wei,
        "data": calldata,
    }

    log_process("正在签名...")
    try:
        signed = sign_transaction(tx, pk, chain_id)
        log_success("签名完成")
    except Exception as e:
        log_error(f"签名失败: {e}")
        log_error("  💡 请检查 master_privatekey.txt 中的私钥是否正确")
        return None

    # ── Broadcast ──
    log_process("正在广播...")
    for attempt in range(1, 6):
        log_info(f"广播尝试 {attempt}/5...")
        tx_hash, err = send_raw_tx(rpc_url, signed, proxy=proxy)
        if tx_hash:
            break
        if err:
            emsg = err.get("message", "")
            if "already known" in emsg.lower() or "nonce too low" in emsg.lower():
                short, hint = explain_broadcast_error(emsg)
                log_warn(f"{short} — {hint}")
                if "nonce too low" in emsg.lower():
                    log_info("Nonce 已被使用，尝试获取最新 Nonce 重发...")
                    nonce = get_nonce(rpc_url, address, proxy)
                    if nonce is not None:
                        tx["nonce"] = nonce
                        signed = sign_transaction(tx, pk, chain_id)
                        continue
            else:
                short, hint = explain_broadcast_error(emsg)
                log_error(f"[广播交易] {short}")
                log_error(f"  💡 {hint}")
                if "insufficient funds" in emsg.lower():
                    return "INSUFFICIENT"
                return None
        time.sleep(2)
    else:
        log_error("广播失败：所有尝试均未成功")
        return None

    print(f"\n{BOLD_GREEN}{'=' * 70}{RESET}")
    log_success(f"交易已发送: {action_name}")
    print(f"  {BOLD_WHITE}哈希  : {BOLD_CYAN}{tx_hash}{RESET}")
    print(f"  {BOLD_WHITE}浏览器: {BOLD_CYAN}{explorer_url}/tx/{tx_hash}{RESET}")
    print(f"{BOLD_GREEN}{'=' * 70}{RESET}")

    # ── Wait for confirmation ──
    confirmed, status, block = wait_for_confirmation(rpc_url, tx_hash, proxy)
    if confirmed is True:
        log_success(f"✓ 交易已确认 (Block {block})")
        return tx_hash
    if confirmed is False:
        log_error(f"✗ 交易执行失败/回滚 (Block {block})")
        return "FAILED"
    log_warn(f"交易已发出但未在 120 秒内确认，请查看: {explorer_url}/tx/{tx_hash}")
    return tx_hash