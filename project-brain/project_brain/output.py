"""
core/brain/output.py — Project Brain 統一彩色輸出工具

所有 brain 命令的輸出都通過這裡，確保風格一致。
"""
from __future__ import annotations

# ── ANSI 顏色 ─────────────────────────────────────────────────
R  = "\033[0m"   # Reset
B  = "\033[1m"   # Bold
D  = "\033[2m"   # Dim
G  = "\033[92m"  # Green
Y  = "\033[93m"  # Yellow
RE = "\033[91m"  # Red
C  = "\033[96m"  # Cyan
BL = "\033[94m"  # Blue
P  = "\033[95m"  # Purple
W  = "\033[97m"  # White
GR = "\033[90m"  # Gray

OK   = f"{G}✓{R}"
WARN = f"{Y}⚠{R}"
ERR  = f"{RE}✗{R}"
INFO = f"{C}ℹ{R}"
RUN  = f"{P}▶{R}"

KIND_COLOR = {
    "Decision": BL, "Pitfall": RE, "Rule": Y,
    "ADR": P, "Component": C, "Person": G,
}

def badge(kind: str) -> str:
    c = KIND_COLOR.get(kind, W)
    return f"{c}{B}[{kind}]{R}"

def hr(w: int = 54, char: str = "─") -> str:
    return f"{GR}{char * w}{R}"

def section(title: str) -> str:
    return f"\n{B}{C}{title}{R}\n{hr()}"

def conf_color(v: float) -> str:
    if v >= 0.75: return G
    if v >= 0.50: return Y
    return RE

def header(title: str, subtitle: str = "") -> str:
    s = f"\n{P}{B}  {title}{R}"
    if subtitle:
        s += f"  {GR}{subtitle}{R}"
    return s + "\n" + hr("═")
