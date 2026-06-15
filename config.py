import os
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 网络配置（LitVM LiteForge 测试网）
# ============================================================
RPC_URL = "https://liteforge.rpc.caldera.xyz/http"
CHAIN_ID = 4441
EXPLORER_URL = "https://liteforge.explorer.caldera.xyz"
GAS_MULTIPLIER = 1.5

# Disperse 合约相关
DISPERSE_SELECTOR = "e63d38ed"
BYTECODE_FILE = "disperse_bytecode.txt"       # 合约部署字节码（自动生成，勿改）
CONTRACT_CACHE_FILE = "disperse_contract.txt"  # 部署后自动保存合约地址

def _bool(key, default=False):
    v = os.getenv(key, "").strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no"):
        return False
    return default

def _float(key, default):
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        return default

def _int(key, default):
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        return default

# ============================================================
# 运行参数（可在 .env 中覆盖）
# ============================================================
AMOUNT_MIN = _float("AMOUNT_MIN", 0.001)    # 每笔最小金额（zkLTC）
AMOUNT_MAX = _float("AMOUNT_MAX", 0.005)    # 每笔最大金额（zkLTC）
DELAY_MIN = _float("DELAY_MIN", 3.0)        # 批次间最小等待（秒）
DELAY_MAX = _float("DELAY_MAX", 8.0)        # 批次间最大等待（秒）
BATCH_SIZE = _int("BATCH_SIZE", 20)         # 每批最多分发几个地址
AUTO_DEPLOY = _bool("AUTO_DEPLOY", True)    # 首次运行自动部署合约
FORCE_DIRECT = _bool("FORCE_DIRECT", False)   # 强制直连，忽略代理
DISPERSE_CONTRACT = os.getenv("DISPERSE_CONTRACT", "").strip()

def load_master_key(path="master_privatekey.txt"):
    """读取主钱包私钥（用于发起合约转账）"""
    env_pk = os.getenv("FUNDING_PRIVATE_KEY", "").strip()
    if env_pk:
        if not env_pk.startswith("0x"):
            env_pk = "0x" + env_pk
        return env_pk

    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            pk = line.split(":")[-1].strip()
            if not pk.startswith("0x"):
                pk = "0x" + pk
            if len(pk) == 66:
                return pk
    return None

def load_wallets(path="wallets.txt"):
    """Read target wallet addresses."""
    if not os.path.exists(path):
        return []
    wallets = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Format: label:address or just address
            addr = line.split(":")[-1].strip()
            if not addr.startswith("0x"):
                addr = "0x" + addr
            if len(addr) == 42:
                wallets.append(addr.lower())
    return wallets


def load_wallet_pairs(path="wallets.txt"):
    """Read wallet pairs: (address, private_key) from wallets.txt.

    File format (one per line):
      address:private_key
    Comments (#) and blank lines are ignored.
    """
    if not os.path.exists(path):
        return []
    pairs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(":")
            if len(parts) < 2:
                continue
            addr = parts[0].strip()
            pk = parts[1].strip()
            if not addr.startswith("0x"):
                addr = "0x" + addr
            if not pk.startswith("0x"):
                pk = "0x" + pk
            if len(addr) == 42 and len(pk) == 66:
                pairs.append((addr.lower(), pk))
    return pairs

def load_proxies(path="proxy.txt"):
    """读取代理列表（可选，不需要可留空或设 FORCE_DIRECT=true）"""
    if FORCE_DIRECT or not os.path.exists(path):
        return []
    proxies = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                proxies.append(line)
    return proxies
