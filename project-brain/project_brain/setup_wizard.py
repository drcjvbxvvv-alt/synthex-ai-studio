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
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_claude_md(workdir: str) -> str:
    """
    Generate the full CLAUDE.md Brain behavior protocol.

    This template instructs the AI agent how to interact with Project Brain
    across three mandatory phases: task start, task complete, and knowledge feedback.

    All prompt text is in English to maximise model compliance.
    """
    return (
        f"# Project Brain\n\n"
        f"Project Brain is installed at `{workdir}`.\n\n"
        "## Memory System Instructions\n\n"
        "At the start of every task, call the `get_context` MCP tool\n"
        "with the task description, current file path, and **current working directory**\n"
        "(the directory Claude Code is currently operating in).\n\n"
        "Always pass `workdir` = the primary working directory of the current session.\n"
        "Brain will automatically walk up from that path to find the nearest `.brain/`.\n\n"
        "If Brain returns nudges or warnings, treat them as **hard constraints**.\n\n"
        "When you discover any of the following, call `add_knowledge` immediately\n"
        "— do not wait until the end of the task:\n\n"
        "- A bug and the reason it happened (kind: Pitfall)\n"
        "- An architectural decision and why (kind: Decision)\n"
        "- A rule that must always be followed (kind: Rule)\n"
        "- Something that does not work as expected (kind: Pitfall)\n\n"
        "Always pass `workdir` to `add_knowledge` and `brain_status` as well.\n\n"
        "Use confidence=0.9 for verified facts, 0.7 for reasonable inferences.\n\n"
        + _task_start_protocol() + "\n\n"
        + _task_complete_protocol() + "\n\n"
        + _knowledge_feedback_protocol() + "\n"
    )


def _task_start_protocol() -> str:
    return """\
## Task Start Protocol

Before beginning **any** task:

1. Call `get_context` with the task description and current file path.
2. If the result contains **Pitfall** entries, read each one carefully and
   explicitly state how you will avoid that mistake before writing code.
3. If the result contains **Rule** entries, those rules are mandatory for
   this task — do not deviate from them.
4. If the result contains **Decision** entries, treat them as established
   architecture — do not reverse them without discussion."""


def _task_complete_protocol() -> str:
    return """\
## Task Complete Protocol

After completing **any** non-trivial task:

1. Call `complete_task` with:
   - `task_description`: one-sentence summary of what was done
   - `decisions`: list of architectural or design choices made (can be empty)
   - `lessons`: list of things learned that would help future work (can be empty)
   - `pitfalls`: list of mistakes encountered or near-misses (can be empty)
2. If a **new bug pattern** was discovered during the task, also call
   `add_knowledge(kind="Pitfall", ...)` immediately — do not rely solely on
   `complete_task` for Pitfall recording.
3. If an **important architectural decision** was made, call
   `add_knowledge(kind="Decision", ...)` as well."""


def _knowledge_feedback_protocol() -> str:
    return """\
## Knowledge Feedback Protocol

After a task that used knowledge retrieved from Brain:

- If a retrieved knowledge node **directly helped** complete the task correctly,
  call `report_knowledge_outcome(node_id=..., was_useful=True)`.
- If a retrieved knowledge node was **outdated, incorrect, or irrelevant**,
  call `report_knowledge_outcome(node_id=..., was_useful=False, notes="reason")`.

This feedback loop keeps confidence scores accurate and prevents stale knowledge
from surfacing in future queries."""


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
            claude_md.write_text(generate_claude_md(str(wd)))
            print(f"  {G}OK{R}  .claude/CLAUDE.md created  {D}(Claude Code auto-context){R}")
        except Exception as _e:
            logger.debug("CLAUDE.md creation failed", exc_info=True)  # non-critical
    else:
        # CLAUDE.md already exists — merge any missing protocol sections
        try:
            existing = claude_md.read_text()
            # Sections from generate_claude_md() that must be present
            _PROTOCOL_SECTIONS = [
                ("## Task Start Protocol",     _task_start_protocol()),
                ("## Task Complete Protocol",  _task_complete_protocol()),
                ("## Knowledge Feedback Protocol", _knowledge_feedback_protocol()),
            ]
            missing = [(hdr, body) for hdr, body in _PROTOCOL_SECTIONS if hdr not in existing]
            if missing:
                appendix = "\n" + "\n\n".join(body for _, body in missing) + "\n"
                claude_md.write_text(existing.rstrip() + appendix)
                added = ", ".join(hdr for hdr, _ in missing)
                print(f"  {G}OK{R}  .claude/CLAUDE.md updated  {D}(added: {added}){R}")
            else:
                print(f"  {D}--{R}  .claude/CLAUDE.md already up-to-date")
        except Exception as _e:
            logger.debug("CLAUDE.md merge failed", exc_info=True)  # non-critical

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
        except Exception as _e:
            logger.debug("Cursor MCP config install failed", exc_info=True)

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
