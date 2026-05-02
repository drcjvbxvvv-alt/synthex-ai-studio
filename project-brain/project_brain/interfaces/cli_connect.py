"""project_brain/interfaces/cli_connect.py — E-03: brain connect CLI command

Usage:
  brain connect <url> --key <key> [--mode overlay]    設定 Central Brain 連線
  brain connect --test                                 測試連線
  brain connect --status                               顯示連線狀態
  brain connect --disconnect                           中斷連線
"""
from __future__ import annotations

import os
from pathlib import Path

from project_brain.interfaces.cli_utils import (
    R, B, D, G, Y, C, GR,
    _workdir, _ok, _err, _info,
)


def cmd_connect(args):
    """設定 / 測試 / 中斷 Central Brain 連線。"""
    wd = _workdir(args)
    brain_dir = Path(wd) / ".brain"
    toml_path = brain_dir / "brain.toml"

    if getattr(args, "disconnect", False):
        _do_disconnect(toml_path)
        return

    if getattr(args, "status", False):
        _do_status(brain_dir)
        return

    if getattr(args, "test", False):
        _do_test(brain_dir)
        return

    # Default: set up connection
    url = getattr(args, "url", None)
    if not url:
        _err("缺少 URL 參數。用法：brain connect <url> --key <key> [--mode overlay]")
        return

    key = getattr(args, "key", "") or os.environ.get("BRAIN_API_KEY", "")
    mode = getattr(args, "mode", "overlay")

    if not brain_dir.exists():
        _err(f"Brain 尚未初始化，請先執行：brain init --workdir {wd}")
        return

    _do_connect(toml_path, url, key, mode)


def _do_connect(toml_path: Path, url: str, key: str, mode: str):
    """Write [team] section to brain.toml."""
    url = url.rstrip("/")

    # Validate mode
    valid_modes = {"overlay", "central-only", "local-only"}
    if mode not in valid_modes:
        _err(f"無效模式 '{mode}'，必須是 {valid_modes} 之一")
        return

    # Read existing content (preserve other sections)
    existing = ""
    if toml_path.exists():
        existing = toml_path.read_text(encoding="utf-8")

    # Remove existing [team] section if present
    lines = existing.split("\n")
    new_lines = []
    in_team = False
    for line in lines:
        if line.strip() == "[team]":
            in_team = True
            continue
        if in_team and line.strip().startswith("["):
            in_team = False
        if not in_team:
            new_lines.append(line)

    # Remove trailing blank lines
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()

    # Append [team] section
    team_block = f"""
[team]
central_brain_url = "{url}"
central_brain_key = "{key}"
mode = "{mode}"
overlay_threshold = 0.6
"""
    content = "\n".join(new_lines) + "\n" + team_block
    toml_path.write_text(content.strip() + "\n", encoding="utf-8")

    _ok(f"已設定 Central Brain 連線")
    print(f"  {D}URL:  {url}{R}")
    print(f"  {D}Mode: {mode}{R}")
    print(f"  {D}Key:  {'***' + key[-4:] if len(key) > 4 else '(none)'}{R}")
    _info("執行 brain connect --test 驗證連線")


def _do_disconnect(toml_path: Path):
    """Remove [team] section from brain.toml."""
    if not toml_path.exists():
        _info("無 brain.toml，已處於 local-only 模式")
        return

    existing = toml_path.read_text(encoding="utf-8")
    lines = existing.split("\n")
    new_lines = []
    in_team = False
    for line in lines:
        if line.strip() == "[team]":
            in_team = True
            continue
        if in_team and line.strip().startswith("["):
            in_team = False
        if not in_team:
            new_lines.append(line)

    # Remove trailing blank lines
    while new_lines and not new_lines[-1].strip():
        new_lines.pop()

    content = "\n".join(new_lines)
    if content.strip():
        toml_path.write_text(content.strip() + "\n", encoding="utf-8")
    else:
        toml_path.unlink(missing_ok=True)

    _ok("已中斷 Central Brain 連線（回到 local-only 模式）")


def _do_status(brain_dir: Path):
    """Show current team config status."""
    try:
        from project_brain.brain_config import load_config
        cfg = load_config(brain_dir)
        tm = cfg.team

        if not tm.central_brain_url:
            print(f"  {D}Mode: local-only（未設定 Central Brain）{R}")
            return

        print(f"\n  {B}{C}Central Brain 連線狀態{R}")
        print(f"  {D}URL:       {tm.central_brain_url}{R}")
        print(f"  {D}Mode:      {tm.mode}{R}")
        print(f"  {D}Threshold: {tm.overlay_threshold}{R}")
        print(f"  {D}Key:       {'***' + tm.central_brain_key[-4:] if len(tm.central_brain_key) > 4 else '(none)'}{R}")
    except Exception as e:
        _err(f"讀取配置失敗：{e}")


def _do_test(brain_dir: Path):
    """Test connection to central brain."""
    try:
        from project_brain.brain_config import load_config
        cfg = load_config(brain_dir)
        tm = cfg.team

        if not tm.central_brain_url:
            _err("未設定 Central Brain URL。先執行：brain connect <url> --key <key>")
            return

        print(f"  {D}測試連線：{tm.central_brain_url}{R}")

        from project_brain.integrations.central_brain_client import CentralBrainClient
        client = CentralBrainClient(
            url=tm.central_brain_url,
            api_key=tm.central_brain_key,
        )

        if client.ping():
            _ok(f"連線成功 — {tm.central_brain_url}/health 回應 OK")

            # Try a quick search to verify full access
            results = client.search_knowledge("test", top_k=1)
            if results is not None:
                _ok(f"search_knowledge 可用（{len(results)} 筆結果）")
            else:
                _info("search_knowledge 未回傳結果（可能需要 API key 或知識庫為空）")
        else:
            _err(f"連線失敗 — 無法連接 {tm.central_brain_url}/health")
            _info("請確認：URL 正確、server 已啟動、網路可達")
    except Exception as e:
        _err(f"測試失敗：{e}")
