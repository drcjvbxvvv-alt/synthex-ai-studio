"""
project_brain/setup_wizard.py -- brain setup wizard (v10.0)

One command does everything:
  1. Detect git repo
  2. Create .brain/brain.db
  3. Install git post-commit hook
  4. Auto-detect Claude Code / Cursor and install MCP
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def run_setup(workdir: str = ".") -> bool:
    """One-command setup. Returns True on success."""
    wd = Path(workdir).resolve()

    G = "\033[92m"; B = "\033[1m"; R = "\033[0m"
    C = "\033[96m"; D = "\033[2m"; Y = "\033[93m"

    print(f"\n{B}{C}  Project Brain -- Quick Setup{R}")
    print(f"{D}{'--'*25}{R}\n")

    # -- Step 1: init brain.db --
    brain_dir = wd / ".brain"
    brain_dir.mkdir(parents=True, exist_ok=True)

    from project_brain.brain_db import BrainDB
    db = BrainDB(brain_dir)
    db.conn.execute(
        "INSERT OR REPLACE INTO brain_meta(key,value) VALUES('project_name',?)",
        (wd.name,)
    )
    db.conn.commit()
    print(f"  {G}OK{R}  Knowledge base ready  {D}({brain_dir}/brain.db){R}")

    # Detect and migrate legacy databases
    legacy = ["knowledge_graph.db","session_store.db","events.db"]
    if any((brain_dir / f).exists() for f in legacy):
        r = db.migrate_from_legacy(brain_dir)
        if r["nodes"] > 0:
            print(f"  {G}OK{R}  Migrated legacy data  {D}({r['nodes']} nodes){R}")

    # -- Step 2: git hook --
    git_root = wd
    if not (wd / ".git").exists():
        for parent in wd.parents:
            if (parent / ".git").exists():
                git_root = parent
                break

    if (git_root / ".git").exists():
        hook_dir  = git_root / ".git" / "hooks"
        hook_path = hook_dir  / "post-commit"
        hook_dir.mkdir(exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        # P2-B: hook works without LLM — extracts commit message as Note (confidence=0.4)
        _wd_s  = str(wd)
        _gr_s  = str(git_root)
        _py_s  = str(git_root / 'brain.py')
        # P2-B fix: hook calls `brain sync` (reads git log itself)
        # No $NOTE passing — brain sync handles git internally
        # Hook calls brain sync — no $NOTE passing needed
        _sync_global  = 'brain sync --workdir "' + _wd_s + '" --quiet 2>/dev/null || true'
        _sync_local   = 'python "' + _py_s + '" sync --workdir "' + _wd_s + '" --quiet 2>/dev/null || true'
        hook_script = (
            '#!/bin/sh\n'
            '# Project Brain auto-learn hook\n'
            'if command -v brain >/dev/null 2>&1; then\n'
            '    ' + _sync_global + '\n'
            'elif [ -f "' + _py_s + '" ]; then\n'
            '    ' + _sync_local + '\n'
            'fi\n'
        )
        hook_path.write_text(hook_script)
        hook_path.chmod(0o755)
        print(f"  {G}OK{R}  Git hook installed  {D}(auto-learn on every commit){R}")

    # Phase 2A: Generate .claude/CLAUDE.md for Claude Code integration
    claude_dir = git_root / '.claude'
    claude_md  = claude_dir / 'CLAUDE.md'
    if not claude_md.exists():
        try:
            claude_dir.mkdir(exist_ok=True)
            claude_md.write_text(
                f'# Project Brain\n\n'
                f'Project Brain is installed at `{wd}`.\n\n'
                f'## Memory System Instructions\n\n'
                f'At the start of every task, call the `get_context` MCP tool\n'
                f'with the task description and current file path.\n\n'
                f'If Brain returns nudges or warnings, treat them as **hard constraints**.\n\n'
                f'When you discover any of the following, call `add_knowledge` immediately\n'
                f'— do not wait until the end of the task:\n\n'
                f'- A bug and the reason it happened (kind: Pitfall)\n'
                f'- An architectural decision and why (kind: Decision)\n'
                f'- A rule that must always be followed (kind: Rule)\n'
                f'- Something that does not work as expected (kind: Pitfall)\n\n'
                f'Use confidence=0.9 for verified facts, 0.7 for reasonable inferences.\n'
            )
            print(f"  {G}OK{R}  .claude/CLAUDE.md created  {D}(Claude Code auto-context){R}")
        except Exception:
            pass  # non-critical
    else:
        print(f"  {Y}??{R}  No git repo found -- skipping hook")

    # -- Step 3: auto-detect MCP --
    mcp_entry = {
        "command": "python",
        "args": ["-m", "project_brain.mcp_server"],
        "env": {"BRAIN_WORKDIR": str(wd)}
    }
    installed = []

    # Claude Code
    claude_cfg = Path.home() / ".claude" / "settings.json"
    try:
        import mcp  # noqa: F401
        claude_cfg.parent.mkdir(exist_ok=True)
        data = json.loads(claude_cfg.read_text()) if claude_cfg.exists() else {}
        data.setdefault("mcpServers", {})
        data["mcpServers"]["project-brain"] = mcp_entry
        claude_cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        installed.append("Claude Code")
    except (ImportError, Exception):
        pass

    # Cursor
    cursor_cfg = wd / ".cursor" / "mcp.json"
    if (Path.home() / ".cursor").exists() or cursor_cfg.parent.exists():
        try:
            cursor_cfg.parent.mkdir(exist_ok=True)
            data = json.loads(cursor_cfg.read_text()) if cursor_cfg.exists() else {}
            data.setdefault("mcpServers", {})
            data["mcpServers"]["project-brain"] = mcp_entry
            cursor_cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            installed.append("Cursor")
        except Exception:
            pass

    if installed:
        print(f"  {G}OK{R}  MCP installed  {D}({', '.join(installed)} -- restart required){R}")
    else:
        print(f"  {D}--  MCP skipped (pip install mcp to enable){R}")

    # -- Done --
    print(f"\n  {D}{'--'*25}{R}")
    print(f"  {G}{B}Setup complete!{R}  Project: {C}{wd.name}{R}")
    print()
    print(f"  {D}Quick commands:{R}")
    print(f"  {C}  brain ask \"how does JWT work here?\"{R}")
    print(f"  {C}  brain add \"note to remember\"{R}")
    print(f"  {C}  brain status{R}")
    print()
    print(f"  {D}Optional: auto-consolidate working memory nightly{R}")
    print(f"  {D}  crontab -e  →  add:{R}")
    print(f"  {Y}  0 2 * * * brain consolidate --workdir {wd}{R}")
    print()
    return True
