"""Friendly error message explanations."""

def explain_exception(exc):
    """Translate network exceptions into user-friendly messages."""
    text = str(exc).lower()
    exc_type = type(exc).__name__

    if "proxy" in text and ("connect" in text or "remote" in text):
        return "Proxy connection failed", "Check proxy.txt or clear proxies to use direct connection"
    if "timeout" in text or exc_type == "Timeout":
        return "Connection timed out", "Will retry automatically, or try a different connection"
    if "connection" in text:
        return "Network connection interrupted", "Check your network or VPN status"
    if "ssl" in text or "certificate" in text:
        return "SSL certificate verification failed", "Check system time or proxy settings"
    return f"Network error ({exc_type})", "Check your network and try again"

def explain_rpc_method(method):
    """Human-readable RPC method names."""
    names = {
        "eth_getBalance":            "Check Balance",
        "eth_getTransactionCount":   "Get Nonce",
        "eth_blockNumber":           "Get Block",
        "eth_gasPrice":              "Get Gas Price",
        "eth_estimateGas":           "Estimate Gas",
        "eth_sendRawTransaction":    "Broadcast TX",
        "eth_getTransactionReceipt": "Get Receipt",
    }
    return names.get(method, f"RPC ({method})")

def explain_broadcast_error(msg):
    """User-friendly broadcast error messages."""
    if not msg:
        return "Unknown error", "Please try again later"
    low = msg.lower()
    if "insufficient funds" in low:
        return "Insufficient balance", "Please top up ETH for gas or reduce the amount"
    if "nonce too low" in low:
        return "Nonce too low", "Wait a few minutes and try again"
    if "already known" in low:
        return "Transaction already in mempool", "Just wait for confirmation"
    if "timeout" in low or "deadline" in low:
        return "Node response timeout", "The script will retry automatically"
    if "revert" in low:
        return "Contract reverted", "Check your balance and target address"
    return msg, "Check the logs above for details"
