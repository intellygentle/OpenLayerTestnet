"""Disperse 合约调用数据编码"""
import config

def p32(val):
    if isinstance(val, int):
        return hex(val)[2:].zfill(64)
    return str(val).lower().replace("0x", "").zfill(64)

def build_disperse_calldata(recipients, values):
    """编码 disperseEther(address[], uint256[]) 调用数据"""
    if len(recipients) != len(values):
        raise ValueError("收款地址数量与金额数量不一致")
    if not recipients:
        raise ValueError("至少需要一个收款地址")

    n = len(recipients)
    recip_offset = 64
    values_offset = 64 + 32 + 32 * n

    parts = [config.DISPERSE_SELECTOR]
    parts.append(p32(recip_offset))
    parts.append(p32(values_offset))
    parts.append(p32(n))
    for addr in recipients:
        parts.append(p32(int(addr.lower().replace("0x", ""), 16)))
    parts.append(p32(n))
    for amount in values:
        parts.append(p32(amount))
    return "0x" + "".join(parts)

def load_deploy_bytecode():
    """读取合约部署字节码"""
    with open(config.BYTECODE_FILE, "r", encoding="utf-8") as f:
        bytecode = f.read().strip()
    if not bytecode.startswith("0x"):
        bytecode = "0x" + bytecode
    return bytecode
