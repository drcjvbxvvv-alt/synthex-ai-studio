"""project_brain/interfaces/cli_push.py — E-05: brain push CLI command

Usage:
  brain push --to <url> --key <key> [--kind Pitfall] [--min-confidence 0.8] [--dry-run]
"""
from __future__ import annotations

import os
from pathlib import Path

from project_brain.interfaces.cli_utils import (
    R, B, D, G, Y, C, GR,
    _workdir, _ok, _err, _info,
)


def cmd_push(args):
    """推送本地知識到 Central Brain。"""
    wd = _workdir(args)
    brain_dir = Path(wd) / ".brain"
    if not brain_dir.exists():
        _err(f"Brain 尚未初始化，請先執行：brain init --workdir {wd}")
        return

    # Resolve target URL and key
    target_url = getattr(args, "to", "") or ""
    api_key = getattr(args, "key", "") or os.environ.get("BRAIN_API_KEY", "")

    # Try team config if not provided
    if not target_url:
        try:
            from project_brain.brain_config import load_config
            cfg = load_config(brain_dir)
            target_url = cfg.team.central_brain_url
            if not api_key:
                api_key = cfg.team.central_brain_key
        except Exception:
            pass

    if not target_url:
        _err("缺少 --to 參數且無 [team] 設定。用法：brain push --to <url> --key <key>")
        _info("或先執行：brain connect <url> --key <key>")
        return

    kind = getattr(args, "kind", "") or ""
    min_confidence = float(getattr(args, "min_confidence", 0.8) or 0.8)
    max_nodes = int(getattr(args, "max_nodes", 50) or 50)
    dry_run = getattr(args, "dry_run", False)
    direct = getattr(args, "direct", False)

    print(f"\n  {B}{C}📤 Brain Push to Central{R}")
    print(f"  {D}Target:     {target_url}{R}")
    print(f"  {D}Kind:       {kind or '(all)'}{R}")
    print(f"  {D}Min conf:   {min_confidence}{R}")
    print(f"  {D}Max nodes:  {max_nodes}{R}")
    print(f"  {D}Direct:     {direct}{R}")
    print(f"  {D}Dry-run:    {dry_run}{R}")
    print()

    # Initialize
    from project_brain.core.brain_db import BrainDB
    from project_brain.integrations.push_central import PushTransport

    db = BrainDB(brain_dir)

    transport = PushTransport()
    nodes = transport.select_nodes(
        db, kind=kind, min_confidence=min_confidence, max_nodes=max_nodes,
    )

    if not nodes:
        _info(f"無符合條件的節點（kind={kind or 'all'}, confidence≥{min_confidence}）")
        db.close()
        return

    sanitized = transport.sanitize_nodes(nodes)
    print(f"  {D}篩選到 {len(nodes)} 個節點，清理後 {len(sanitized)} 個{R}")

    if dry_run:
        print(f"\n  {Y}[DRY-RUN] 預覽（不實際推送）：{R}")
        for item in transport.preview(sanitized):
            print(f"  {D}  [{item['kind']:<10}] {item['confidence']:.2f}  {item['title']}{R}")
        db.close()
        return

    # Live push
    from project_brain.integrations.central_brain_client import CentralBrainClient
    client = CentralBrainClient(url=target_url, api_key=api_key)

    if not client.ping():
        _err(f"無法連接 {target_url}（ping failed）")
        db.close()
        return

    result = transport.push(client, sanitized, source_label="push", direct=direct)
    db.close()

    print(f"\n  {G}推送完成{R}")
    print(f"  {D}成功：{result.pushed_ok}{R}")
    if result.pushed_fail:
        print(f"  {Y}失敗：{result.pushed_fail}{R}")
    if result.errors:
        for e in result.errors[:5]:
            print(f"    {D}{e}{R}")
