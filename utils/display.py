import os
import re
import shutil

# Terminal colors
RESET        = "\033[0m"
BOLD_GREEN   = "\033[1;32m"
BOLD_YELLOW  = "\033[1;33m"
BOLD_RED     = "\033[1;31m"
BOLD_CYAN    = "\033[1;36m"
BOLD_MAGENTA = "\033[1;35m"
BOLD_WHITE   = "\033[1;37m"
DIM          = "\033[2m"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
VERSION_DATE = "2026-06-14"

_PASTEL_COLORS = [
    (100, 200, 255), (130, 210, 255), (160, 220, 255),
    (100, 180, 255), (130, 190, 255), (160, 200, 255),
    (100, 220, 240),
]

def log_success(msg): print(f"{BOLD_GREEN}[OK] {msg}{RESET}")
def log_error(msg):   print(f"{BOLD_RED}[ERROR] {msg}{RESET}")
def log_info(msg):    print(f"{BOLD_YELLOW}[INFO] {msg}{RESET}")
def log_process(msg): print(f"{BOLD_CYAN}[...] {msg}{RESET}")
def log_task(msg):    print(f"{BOLD_MAGENTA}[TASK] {msg}{RESET}")
def log_warn(msg):    print(f"{BOLD_YELLOW}[WARN] {msg}{RESET}")

def _terminal_cols():
    try:
        return max(60, shutil.get_terminal_size().columns)
    except Exception:
        return 80

def _plain_text(text):
    return ANSI_RE.sub("", text).rstrip()

def _rgb_color(r, g, b):
    return f"\033[38;2;{r};{g};{b}m"

def _gradient_pastel(text):
    lines = text.split("\n")
    colored_lines = []
    for line in lines:
        chars = list(line)
        visible = [c for c in chars if c.strip()]
        total = max(len(visible), 1)
        visible_idx = 0
        n = len(_PASTEL_COLORS) - 1
        parts = []
        for c in chars:
            if not c.strip():
                parts.append(c)
                continue
            t = visible_idx / max(total - 1, 1)
            pos = t * n
            i = min(int(pos), n - 1)
            frac = pos - i
            c1, c2 = _PASTEL_COLORS[i], _PASTEL_COLORS[i + 1]
            r = int(c1[0] + (c2[0] - c1[0]) * frac)
            g = int(c1[1] + (c2[1] - c1[1]) * frac)
            b = int(c1[2] + (c2[2] - c1[2]) * frac)
            parts.append(f"{_rgb_color(r, g, b)}{c}")
            visible_idx += 1
        colored_lines.append("".join(parts) + RESET)
    return "\n".join(colored_lines)

def _center_line(line, cols=None):
    cols = cols or _terminal_cols()
    pad = max(0, (cols - len(_plain_text(line))) // 2)
    return " " * pad + line

def _center_block(text, cols=None):
    cols = cols or _terminal_cols()
    return "\n".join(_center_line(line, cols) for line in text.split("\n"))

def _center_block_uniform(text, cols=None):
    cols = cols or _terminal_cols()
    lines = text.split("\n")
    max_len = max(len(_plain_text(line)) for line in lines) if lines else 1
    pad = max(0, (cols - max_len) // 2)
    return "\n".join(" " * pad + line for line in lines)

def _make_round_box(text, width=45, border_color=BOLD_RED, padding=(1, 2, 1, 2)):
    top_pad, right_pad, bottom_pad, left_pad = padding
    inner_w = width - 2
    text_w = inner_w - left_pad - right_pad
    rows = []
    for _ in range(top_pad):
        rows.append(" " * inner_w)
    for line in text.split("\n"):
        plain = _plain_text(line)
        pad_l = max(0, (text_w - len(plain)) // 2)
        pad_r = max(0, text_w - len(plain) - pad_l)
        rows.append(" " * left_pad + " " * pad_l + line + " " * pad_r + " " * right_pad)
    for _ in range(bottom_pad):
        rows.append(" " * inner_w)
    top = f"{border_color}╭{'─' * inner_w}╮{RESET}"
    bottom = f"{border_color}╰{'─' * inner_w}╯{RESET}"
    middle = [f"{border_color}│{RESET}{row}{border_color}│{RESET}" for row in rows]
    return "\n".join([top] + middle + [bottom])

def get_banner_string():
    cols = _terminal_cols()
    title = _center_block(_gradient_pastel("Ethereum Sepolia - Daily Mission Runner"), cols)
    version = _center_line(f"{BOLD_YELLOW}Version: {VERSION_DATE}{RESET}", cols)
    network = _center_line(f"{BOLD_CYAN}Network: Sepolia Testnet (Chain ID: 11155111){RESET}", cols)
    sep = _center_line(f"{DIM}{'=' * 60}{RESET}", cols)
    return f"\n{title}\n{network}\n{version}\n\n{sep}\n"

def banner(label=None):
    if not os.getenv("NO_CLEAR"):
        os.system("cls" if os.name == "nt" else "clear")
    if label:
        title = _center_block(_gradient_pastel(label), _terminal_cols())
        print(f"\n{title}\n")
    else:
        print(get_banner_string())
