"""project_brain/interfaces/cli_admin_keys.py — E-05: API Key Management CLI

Usage:
  brain admin create-key --role contributor --name "Alice"
  brain admin list-keys
  brain admin revoke-key <key_id>

Integrates with the existing `brain admin` CLI via sub-subcommand dispatch.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from project_brain.interfaces.cli_utils import (
    R, B, D, G, Y, C,
    _workdir, _ok, _err, _info,
)


def cmd_admin_keys(args):
    """Dispatch admin key management sub-subcommands."""
    admin_sub = getattr(args, "admin_sub", "")

    if admin_sub == "create-key":
        _do_create_key(args)
    elif admin_sub == "list-keys":
        _do_list_keys(args)
    elif admin_sub == "revoke-key":
        _do_revoke_key(args)
    else:
        return False  # not handled — fall through to original admin dispatch
    return True


def _do_create_key(args):
    """Create a new API key."""
    wd = _workdir(args)
    brain_dir = Path(wd) / ".brain"
    if not brain_dir.exists():
        _err("Brain 尚未初始化")
        return

    role = getattr(args, "role", "reader") or "reader"
    name = getattr(args, "name", "") or ""

    from project_brain.rbac import VALID_ROLES
    if role not in VALID_ROLES:
        _err(f"無效角色 '{role}'，必須是 {sorted(VALID_ROLES)} 之一")
        return

    if not name:
        _err("需要 --name 參數（例：--name 'Alice'）")
        return

    # Generate a secure token
    token = f"brn_{role[0]}_{secrets.token_urlsafe(24)}"

    from project_brain.core.brain_db import BrainDB
    db = BrainDB(brain_dir)
    key_id = db.store_api_key(token, role, name)
    db.close()

    _ok(f"API key 已建立（ID: {key_id}）")
    print(f"\n  {B}{C}請保存以下 key（只顯示一次）：{R}")
    print(f"  {G}{token}{R}")
    print(f"\n  {D}角色：{role}  名稱：{name}{R}")
    print(f"  {D}設定環境變數：export BRAIN_API_KEY={token}{R}")


def _do_list_keys(args):
    """List all API keys."""
    wd = _workdir(args)
    brain_dir = Path(wd) / ".brain"
    if not brain_dir.exists():
        _err("Brain 尚未初始化")
        return

    from project_brain.core.brain_db import BrainDB
    db = BrainDB(brain_dir)
    keys = db.list_api_keys()
    db.close()

    if not keys:
        _info("尚無 API key")
        return

    print(f"\n  {B}{C}API Keys{R}")
    print(f"  {'ID':<6} {'Role':<14} {'Name':<16} {'Status':<10} {'Created'}")
    print(f"  {'─'*6} {'─'*14} {'─'*16} {'─'*10} {'─'*20}")
    for k in keys:
        status = f"{Y}revoked{R}" if k.get("is_revoked") else f"{G}active{R}"
        print(f"  {k['id']:<6} {k['role']:<14} {k['name']:<16} {status:<19} {k.get('created_at', '')[:16]}")


def _do_revoke_key(args):
    """Revoke an API key."""
    wd = _workdir(args)
    brain_dir = Path(wd) / ".brain"
    if not brain_dir.exists():
        _err("Brain 尚未初始化")
        return

    key_id_str = getattr(args, "key_id", "")
    if not key_id_str:
        _err("缺少 key ID。用法：brain admin revoke-key <key_id>")
        return

    try:
        key_id = int(key_id_str)
    except ValueError:
        _err(f"無效 key ID：{key_id_str}")
        return

    from project_brain.core.brain_db import BrainDB
    db = BrainDB(brain_dir)
    success = db.revoke_api_key(key_id)
    db.close()

    if success:
        _ok(f"API key {key_id} 已撤銷")
    else:
        _err(f"Key {key_id} 不存在或已撤銷")
