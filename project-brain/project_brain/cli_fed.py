"""project_brain/cli_fed.py — Federation and session CLI commands (CLI-01)"""
import sys
import os
from pathlib import Path
from project_brain.cli_utils import (
    R, B, D, G, Y, RE, C, P, GR, W,
    _workdir, _ok, _err, _info,
)
from project_brain.constants import DEFAULT_SEARCH_LIMIT


def cmd_fed(args):
    """
    VISION-03: 跨專案聯邦知識共享（brain fed）

    子命令：
      brain fed export   — 匯出本地知識 bundle
      brain fed import   — 匯入外部 bundle 到 KRB Staging
      brain fed sync     — 自動從所有 sync_sources 同步知識
      brain fed subscribe / unsubscribe / list — 管理領域訂閱
    """
    wd = _workdir(args)
    from pathlib import Path as _P
    bd = _P(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    fed_sub = getattr(args, 'fed_sub', 'list')

    if fed_sub in ('subscribe', 'unsubscribe', 'list'):
        from project_brain.federation import cmd_fed_subscribe
        args.action = fed_sub
        cmd_fed_subscribe(bd, args)

    elif fed_sub == 'export':
        from project_brain.brain_db import BrainDB
        from project_brain.graph    import KnowledgeGraph
        from project_brain.federation import cmd_fed_export
        db    = BrainDB(bd)
        graph = KnowledgeGraph(bd / "brain.db")
        cmd_fed_export(bd, graph, args)

    elif fed_sub == 'import':
        from project_brain.brain_db    import BrainDB
        from project_brain.graph       import KnowledgeGraph
        from project_brain.review_board import KnowledgeReviewBoard
        from project_brain.federation   import cmd_fed_import
        db    = BrainDB(bd)
        graph = KnowledgeGraph(bd / "brain.db")
        krb   = KnowledgeReviewBoard(db, graph)
        cmd_fed_import(bd, krb, args)

    elif fed_sub == 'sync':
        from project_brain.brain_db    import BrainDB
        from project_brain.graph       import KnowledgeGraph
        from project_brain.review_board import KnowledgeReviewBoard
        from project_brain.federation   import cmd_fed_sync
        db    = BrainDB(bd)
        graph = KnowledgeGraph(bd / "brain.db")
        krb   = KnowledgeReviewBoard(db, graph)
        cmd_fed_sync(bd, krb, args)

    elif fed_sub == 'imports':
        from project_brain.federation import cmd_fed_import_list
        cmd_fed_import_list(bd, args)

    else:
        _err(f"未知子命令：{fed_sub}")
        _info("用法：brain fed export | import | sync | imports | subscribe | unsubscribe | list")


def cmd_migrate(args):
    """FEAT-07: 跨專案知識遷移（brain migrate --from <path>）"""
    wd        = _workdir(args)
    src_path  = getattr(args, 'from_path', None)
    if not src_path:
        _err("請提供來源路徑：brain migrate --from <path_to_brain.db>"); return
    from pathlib import Path as _P
    src = _P(src_path).resolve()
    if not src.exists():
        alt = src / ".brain" / "brain.db"
        if alt.exists():
            src = alt
        else:
            _err(f"找不到來源資料庫：{src}"); return

    bd = _P(wd) / ".brain"
    if not bd.exists():
        _err("目標 Brain 尚未初始化，請執行：brain setup"); return

    scope      = getattr(args, 'scope', 'global') or 'global'
    min_conf   = float(getattr(args, 'min_confidence', 0.0) or 0.0)
    dry_run    = getattr(args, 'dry_run', False)
    to_path    = getattr(args, 'to_path', None)

    if to_path:
        dest_bd = _P(to_path) / ".brain"
    else:
        dest_bd = bd

    from project_brain.brain_db import BrainDB
    db     = BrainDB(dest_bd)
    result = db.migrate_from(src, scope=scope, min_confidence=min_conf, dry_run=dry_run)

    tag = f"{Y}[DRY-RUN] {R}" if dry_run else ""
    _ok(f"{tag}遷移完成：節點 {result['nodes']}  邊 {result['edges']}  錯誤 {result['errors']}")
    if dry_run:
        _info("加 --execute 參數可實際執行遷移（去掉 --dry-run）")


def cmd_session(args):
    """FEAT-04: brain session archive / list"""
    sub = getattr(args, 'session_sub', 'list') or 'list'
    wd  = _workdir(args)
    bd  = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化"); return

    from project_brain.session_store import SessionStore
    store = SessionStore(bd)

    if sub == 'archive':
        out = store.archive(
            session_id=getattr(args, 'session', '') or '',
            older_than_days=int(getattr(args, 'older_than', 0) or 0),
        )
        if out:
            _ok(f"Session 已歸檔：{out}")
        else:
            _info("當前 session 無條目可歸檔")
    elif sub == 'list':
        entries = store.list_all()
        if not entries:
            _info("L1a 工作記憶為空"); return
        print(f"\n{C}{B}🧠  L1a 工作記憶（{len(entries)} 筆）{R}")
        for e in entries[:20]:
            cat = e.category
            print(f"  {GR}{cat:10}{R}  {e.key[:30]:30}  {e.value[:60]}")
        print()
    else:
        _err(f"未知子命令：{sub}（可用：list, archive）")
