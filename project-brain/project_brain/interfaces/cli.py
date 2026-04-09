#!/usr/bin/env python3
"""project_brain.cli — Project Brain CLI 入口

CLI-01: Functions split into sub-modules:
    cli_utils.py     — shared utilities + parser building (_build_parser, _apply_aliases)
    cli_knowledge.py — knowledge management commands
    cli_admin.py     — system administration commands
    cli_serve.py     — server commands
    cli_fed.py       — federation and session commands
"""
import sys, os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 保留兼容本地開發（python brain.py）
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── CLI-01: Import from sub-modules ───────────────────────────
from project_brain.cli_utils import (
    R, B, D, G, Y, RE, C, P, GR, W,
    _Spinner, _banner, _workdir, _ok, _err, _info,
    _brain, _infer_scope, _env_source, _check_l2_health,
    _now, _load_dotenv, _settings_block, _show_guide,
    _scan_banner, _verify_sqlite_vec,
    _build_parser, _apply_aliases,
    setup_logging,
)

from project_brain.cli_knowledge import (
    cmd_ask, cmd_search, cmd_timeline, cmd_history,
    cmd_restore, cmd_deprecated, cmd_deprecate, cmd_lifecycle, cmd_rollback,
    cmd_link_issue, cmd_review,
    cmd_sync,
    _cmd_add_interactive,
)

from project_brain.cli_admin import (
    cmd_init, cmd_status, cmd_setup, cmd_doctor, cmd_config,
    cmd_optimize, cmd_clear, cmd_scan, cmd_health_report, cmd_report,
    cmd_analytics, cmd_export, cmd_import, cmd_index,
    cmd_health,
    _cmd_backfill_git,
)

from project_brain.cli_serve import cmd_serve, cmd_webui
from project_brain.cli_fed import cmd_fed, cmd_migrate, cmd_session


# ── cmd_add / cmd_context: defined here so tests can patch project_brain.cli._brain ──

def cmd_add(args):
    """手動加入一筆知識"""
    no_text  = not getattr(args, 'text', None)
    no_title = not getattr(args, 'title', None)
    if no_text and no_title:
        args = _cmd_add_interactive(args)
        if args is None:
            return
    elif getattr(args, 'text', None) and not getattr(args, 'title', None):
        txt = ' '.join(args.text)
        args.title   = [txt[:60].strip()]
        if not args.content: args.content = txt
    elif not getattr(args, 'title', None):
        _err('請提供內容，例如：brain add "JWT 必須使用 RS256"'); return
    wd      = _workdir(args)
    title   = ' '.join(args.title) if args.title else ''
    content = args.content or ''
    kind    = args.kind or 'Pitfall'
    tags    = args.tags or []
    if not title:
        _err("請提供 --title"); return
    ew = getattr(args, 'emotional_weight', 0.5)
    b = _brain(wd)
    # ARCH-04: --global is deprecated, use --scope global
    _explicit_global = getattr(args, 'global_scope', False)
    _raw_scope = getattr(args, 'scope', None)
    if _explicit_global:
        print(f"  {D}⚠ --global is deprecated, use --scope global instead{R}", file=sys.stderr)
        _scope = 'global'
    elif _raw_scope and _raw_scope != 'global':
        _scope = _raw_scope
    else:
        _scope = _infer_scope(wd)
    if _scope == 'global' and not _explicit_global and not getattr(args, 'quiet', False):
        _info(f"⚠ 此知識將寫入 global scope（跨所有專案可見）。"
              f"如需隔離請加 --scope <名稱>，或加 --global 確認寫入 global。")
    _conf   = getattr(args, 'confidence', 0.8) or 0.8
    node_id = b.add_knowledge(title, content, kind, tags,
                             scope=_scope, confidence=_conf)
    if ew != 0.5:
        try:
            b.graph._conn.execute(
                "UPDATE nodes SET emotional_weight=? WHERE id=?", (ew, node_id))
            b.graph._conn.commit()
        except Exception as _e:
            logger.debug("emotional_weight update failed", exc_info=True)
    _ok(f"知識已加入：{C}{B}{node_id}{R}")
    _info(f"類型：{kind}  標題：{title}")
    if not getattr(args, 'quiet', False):
        try:
            evts = b.db.recent_events(event_type="near_duplicate", limit=1)
            if evts and evts[0].get("payload"):
                import json as _j
                p = _j.loads(evts[0]["payload"]) if isinstance(evts[0]["payload"], str) else evts[0]["payload"]
                if p.get("new_id") == node_id:
                    print(f"  {Y}⚠ 相似知識已存在（相似度 {p['similarity']:.0%}）：{p['existing_id'][:16]}{R}")
                    print(f"  {D}  若確認重複請執行：brain dedup --execute{R}")
        except Exception as _e:
            logger.debug("near_duplicate event check failed", exc_info=True)
        first_word = title.split()[0] if title.split() else title
        _info(f"查詢：{GR}brain ask \"{first_word}\"{R}")


def cmd_context(args):
    """查詢：這個任務需要注入哪些知識？"""
    wd   = _workdir(args)
    task = ' '.join(args.task) if args.task else ''
    if not task:
        _err("請提供 --task 或直接寫任務描述"); return
    b   = _brain(wd)
    ctx = b.get_context(task)
    if getattr(args, 'interactive', False):
        try:
            bd = Path(wd) / ".brain"
            from project_brain.brain_db import BrainDB
            from project_brain.nudge_engine import NudgeEngine
            _db = BrainDB(bd)
            ne  = NudgeEngine(b.graph, brain_db=_db)
            qs  = ne.generate_questions(task)
            if qs:
                print(f"\n{P}{B}❓  Brain 想知道（低信心知識確認）{R}")
                for q in qs:
                    print(f"  {Y}?{R}  {q['question']}")
                    print(f"     {GR}brain add --kind {q['node_type']} \"{q['question'][:40]}\"{R}")
                print()
        except Exception as _e:
            logger.debug("nudge questions display failed", exc_info=True)
    if ctx:
        print(f"\n{C}{B}🧠  相關知識注入{R}\n{GR}{'─'*50}{R}")
        print(ctx)
        print(f"{GR}{'─'*50}{R}")
    else:
        stats = b.graph.stats()
        total = stats.get('nodes', 0)
        by_type = stats.get('by_type', {})
        knowledge_types = [t for t in ('Pitfall','Decision','Rule','ADR') if by_type.get(t,0) > 0]
        if total == 0:
            print(f"{Y}⚠{R}  知識庫剛建立，還沒有任何知識")
            print(f"   加入第一條知識：")
            print(f"   {GR}  brain add \"JWT 必須使用 RS256\"  --kind Rule{R}")
            print(f"   {GR}  brain add \"你的踩坑記錄\"        --kind Pitfall{R}")
            print(f"   {D}每次 commit 也會自動記錄（透過 git hook）{R}")
        elif not knowledge_types:
            from project_brain.brain_db import BrainDB as _BDB
            from pathlib import Path as _P
            _bdb  = _BDB(_P(wd) / ".brain")
            _note_count = _bdb.conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE type='Note'"
            ).fetchone()[0]
            if _note_count > 0:
                print(f"{Y}⚠{R}  找到 {W}{_note_count}{R} 筆筆記，但關鍵字不符")
                print(f"   試試更換關鍵字，或加入更多知識")
                print(f"   {GR}  brain add \"更多知識\"  --kind Rule{R}")
            else:
                print(f"{Y}⚠{R}  知識庫剛建立，還沒有知識")
                print(f"   馬上加入第一條規則：")
                print(f"   {GR}  brain add \"你的第一條規則或踩坑\"  --kind Rule{R}")
                print(f"   {GR}  brain add \"你的第一條踩坑紀錄\"   --kind Pitfall{R}")
        else:
            print(f"{Y}⚠{R}  找不到「{task}」相關的知識")
            print(f"   知識庫現有：{', '.join(f'{t} {by_type[t]}' for t in knowledge_types)}")
            print(f"   試試更換關鍵字，或用 {D}brain add{R} 手動加入相關知識")


def main():
    _load_dotenv()
    setup_logging()   # OPT-09: JSON logging if BRAIN_LOG_JSON=1
    parser = _build_parser()

    if len(sys.argv) == 1:
        print(_settings_block())
        print()
        parser.print_help()
        return

    _apply_aliases()
    args = parser.parse_args()

    if getattr(args, 'guide', False):
        _show_guide()
        return

    dispatch = {
        'init':          cmd_init,
        'status':        cmd_status,
        'setup':         cmd_setup,
        'ask':           cmd_ask,
        'sync':          cmd_sync,
        'add':           cmd_add,
        'context':       cmd_context,
        # meta: REFACTOR-01 已移除，由 _apply_aliases 攔截並 exit
        'doctor':        cmd_doctor,
        'health':        cmd_health,
        'config':        cmd_config,
        'optimize':      cmd_optimize,
        'clear':         cmd_clear,
        'review':        cmd_review,
        'scan':          cmd_scan,
        'serve':         cmd_serve,
        'session':       cmd_session,
        'index':         cmd_index,
        'webui':         cmd_webui,
        'health-report': cmd_health_report,
        'report':        cmd_report,
        'search':        cmd_search,
        'link-issue':    cmd_link_issue,
        'analytics':     cmd_analytics,
        'export':        cmd_export,
        'import':        cmd_import,
        'timeline':      cmd_timeline,
        'rollback':      cmd_rollback,
        'history':       cmd_history,
        'restore':       cmd_restore,
        'deprecated':    cmd_deprecated,
        'migrate':       cmd_migrate,
        'fed':            cmd_fed,
        # counterfactual: REFACTOR-01 已移除，由 _apply_aliases 攔截並 exit
        'backfill-git':  _cmd_backfill_git,
        'deprecate':     cmd_deprecate,
        'lifecycle':     cmd_lifecycle,
    }

    fn = dispatch.get(args.cmd)
    if fn:
        try:
            fn(args)
        except KeyboardInterrupt:
            print(f"\n{GR}已中止{R}")
    else:
        print(_settings_block())
        print()
        parser.print_help()

if __name__ == '__main__':
    main()
