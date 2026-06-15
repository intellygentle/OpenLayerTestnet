"""
Proxy resolution module.

Priority (highest to lowest):
1. Static proxies from proxy.txt (fixed IP)
2. System/environment variable proxies (system proxy mode, VPN global mode)
3. Direct connection (VPS, VPN TUN mode, etc.)
"""

import os
from typing import List, Optional, Tuple

# Proxy mode identifiers
PROXY_MODE_STATIC = "static"
PROXY_MODE_SYSTEM = "system"
PROXY_MODE_DIRECT = "direct"


def get_system_proxy() -> Optional[str]:
    """Detect system proxy from environment variables."""
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        val = os.getenv(key, "").strip()
        if val:
            return val
    return None


def resolve_proxy(wallet_index: int, static_proxies: List[str]) -> Tuple[Optional[str], str]:
    """
    Resolve proxy for the given wallet index.

    Returns: (proxy_url, mode)
      - proxy_url: actual proxy address; None for direct connection
      - mode: static / system / direct
    """
    if static_proxies:
        proxy = static_proxies[wallet_index % len(static_proxies)]
        return proxy, PROXY_MODE_STATIC

    system_proxy = get_system_proxy()
    if system_proxy:
        return system_proxy, PROXY_MODE_SYSTEM

    return None, PROXY_MODE_DIRECT


def build_requests_proxies(proxy: Optional[str] = None):
    """Build proxies dict for the requests library."""
    if proxy:
        return {"http": proxy, "https": proxy}
    return None


def proxy_mode_label(mode: str) -> str:
    """Convert proxy mode to display label."""
    labels = {
        PROXY_MODE_STATIC: "Static Proxy",
        PROXY_MODE_SYSTEM: "System Proxy",
        PROXY_MODE_DIRECT: "Direct",
    }
    return labels.get(mode, mode)
