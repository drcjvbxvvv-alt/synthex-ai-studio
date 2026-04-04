#!/usr/bin/env python3
"""
project_brain.cli — Project Brain CLI 入口

安裝後直接使用：
    pip install project-brain
    brain init   --workdir .
    brain scan
    brain context "JWT 認證問題"

開發者 Python API：
    from project_brain import Brain
    b = Brain(".")
    ctx = b.get_context("JWT 認證問題")

CLI-01: Functions split into sub-modules:
    cli_utils.py     — shared utilities (ANSI, helpers)
    cli_knowledge.py — knowledge management commands
    cli_admin.py     — system administration commands
    cli_serve.py     — server commands
    cli_fed.py       — federation and session commands
"""
import sys, os
from pathlib import Path
from project_brain.constants import DEFAULT_SEARCH_LIMIT  # REF-04

# project_brain 套件安裝後不需要手動設定 sys.path
# 保留兼容本地開發（python brain.py）
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ── CLI-01: Import from sub-modules ───────────────────────────
# ANSI 顏色 + 共享工具（backward compat: still importable from cli)
from project_brain.cli_utils import (
    R, B, D, G, Y, RE, C, P, GR, W,
    _Spinner, _banner, _workdir, _ok, _err, _info,
    _brain, _infer_scope, _env_source, _check_l2_health,
    _now, _load_dotenv, _settings_block, _show_guide,
    _scan_banner, _verify_sqlite_vec,
)

# Knowledge management commands
from project_brain.cli_knowledge import (
    cmd_ask, cmd_search, cmd_timeline, cmd_history,
    cmd_restore, cmd_deprecated, cmd_deprecate, cmd_lifecycle, cmd_rollback,
    cmd_link_issue, cmd_meta_knowledge, cmd_review, cmd_counterfactual,
    cmd_sync,
    _cmd_add_interactive,
)

# System administration commands
from project_brain.cli_admin import (
    cmd_init, cmd_status, cmd_setup, cmd_doctor, cmd_config,
    cmd_optimize, cmd_clear, cmd_scan, cmd_health_report, cmd_report,
    cmd_analytics, cmd_export, cmd_import, cmd_index,
)

# Server commands
from project_brain.cli_serve import cmd_serve, cmd_webui

# Federation and session commands
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
    # STB-04: 若最終 scope 為 global，提示使用者（跨所有專案可見）
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
        except Exception:
            pass
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
        except Exception:
            pass
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
        except Exception:
            pass
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
    import argparse

    _load_dotenv()

    parser = argparse.ArgumentParser(
        prog='brain',
        description='Project Brain — AI 記憶系統（獨立版，可搭配任何 LLM）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""命令快速參考：
  brain setup                          一鍵設定（第一次使用）
  brain add "JWT 筆記"                 加入知識（快速模式）
  brain ask "JWT 怎麼設定"              查詢知識
  brain status                         查看記憶狀態
  brain doctor                         系統健康檢查
  brain doctor --fix                   自動修復問題
  brain serve --port 7891              啟動 REST API
  brain webui --port 7890              D3.js 視覺化驗證
  brain sync --quiet                   從 git commit 學習（hook 呼叫）

環境變數：
  BRAIN_WORKDIR         預設工作目錄（省略 --workdir）
  ANTHROPIC_API_KEY     AI 分析功能所需（scan/sync）
  BRAIN_LLM_PROVIDER    anthropic（預設）或 openai（本地 Ollama/LM Studio）
  BRAIN_LLM_BASE_URL    本地 LLM 端點（預設 http://localhost:11434/v1）
  BRAIN_LLM_MODEL       本地模型名稱（預設 llama3.1:8b）
  BRAIN_SYNTHESIZE      1 = 啟用記憶融合模式（opt-in）
""",
    )
    parser.add_argument('--guide', action='store_true',
                        help='完整使用指南（新專案/舊專案/環境變數/LLM 整合）')
    from project_brain import __version__ as _ver
    parser.add_argument('--version', '-v', action='version',
                        version=f'brain {_ver}',
                        help='顯示版本號碼')

    sub = parser.add_subparsers(dest='cmd', metavar='<command>')

    def mkp(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument('--workdir', '-w', default=None,
                       help='專案目錄（預設：自動從當前目錄往上找 .brain/，無需設定）')
        return p

    p = mkp('init',   '初始化 Project Brain')
    p.add_argument('--local-only', action='store_true',
                   help='本地模式：不呼叫任何 API，完全離線')
    p.add_argument('--name', default='', help='專案名稱')
    mkp('status', '查看三層記憶狀態（L1/L2/L3）')
    mkp('setup', 'One-command setup (first-time use)')

    p = mkp('ask', 'Ask Brain a question (alias for context)')
    p.add_argument('query', nargs='+', help='Question')
    p.add_argument('--json', action='store_true', help='PH2-07: 輸出結構化 JSON')

    p = mkp('sync', 'Learn from latest git commit (used by hook)')
    p.add_argument('--quiet', action='store_true', help='Suppress output')


    p = mkp('add', '手動加入一筆知識')
    p.add_argument('text', nargs='*', default=[],
                   help='快速模式：brain add "筆記內容"')
    p.add_argument('--title',   nargs='+')
    p.add_argument('--content', default='')
    p.add_argument('--confidence', type=float, default=None,
                   help='信心分數 0.0~1.0（預設 0.8）')
    p.add_argument('--quiet', action='store_true',
                   help='靜默模式（不輸出確認）')
    p.add_argument('--scope', default=None,
                   help='作用域（預設：從 git remote 自動推斷；global = 所有專案共享）')
    p.add_argument('--global', dest='global_scope', action='store_true',
                   help='[已棄用] 請改用 --scope global（FLY-02/STB-04：寫入 global scope）')
    p.add_argument('--kind',    default='Note',
                   choices=['Decision','Pitfall','Rule','ADR','Component','Note'],
                   help='類型（預設：Pitfall）')
    p.add_argument('--tags',    nargs='+', default=[])
    p.add_argument('--emotional-weight', dest='emotional_weight', type=float,
                   default=0.5, help='情感重量 0.0~1.0（踩坑越痛=越高，影響衰減速度）')

    p = mkp('context', '查詢任務相關知識（Context 注入）')
    p.add_argument('task', nargs='*', help='任務描述')
    p.add_argument('--interactive', '-i', action='store_true',
                   help='DEEP-04: 顯示 Brain 想確認的低信心問題')

    p.add_argument('--dry-run', dest='dry_run', action='store_true',
                   help='只預覽，不執行（與不加 --execute 等效，提供慣用語法）')






    p = mkp('review', '審查 KRB Staging 中待核准的知識')
    p.add_argument('review_sub', nargs='?', default='list',
                   choices=['list','approve','reject','pre-screen'],
                   help='子命令（預設：list）')
    p.add_argument('id', nargs='?', default=None,
                   help='Staged node ID（approve / reject 時必填）')
    p.add_argument('--reviewer',      default='human', help='審查者名稱')
    p.add_argument('--note',          default='',      help='核准備注')
    p.add_argument('--reason',        default='',      help='拒絕原因')
    p.add_argument('--limit',         type=int, default=20,  help='列出/預篩筆數上限')
    p.add_argument('--pending-ai',    dest='pending_ai', action='store_true',
                   help='只列出 AI 標記為 review 的待人工審查項目')
    p.add_argument('--auto-approve',  dest='auto_approve', type=float, default=None,
                   help='AI 信心 ≥ 此值時自動核准（預設關閉）')
    p.add_argument('--auto-reject',   dest='auto_reject',  type=float, default=None,
                   help='AI 信心 ≥ 此值且建議拒絕時自動執行（預設關閉）')
    p.add_argument('--max-api-calls', dest='max_api_calls', type=int, default=20,
                   help='pre-screen 最大 API 呼叫次數（預設 20）')

    p = mkp('doctor', '系統健康檢查與自動修復')
    p.add_argument('--fix', action='store_true', help='嘗試自動修復發現的問題')

    mkp('config', '顯示並驗證所有設定來源（5 處）')

    p = mkp('optimize', 'C-1: 資料庫維護 — VACUUM + FTS5 rebuild（節省磁碟）')
    p.add_argument('--prune-episodes', action='store_true',
                   help='清理舊 Episode（L2 git commit 記錄），搭配 --older-than 使用')
    p.add_argument('--older-than', dest='older_than', type=int, default=365,
                   help='清理幾天前的 episode（預設 365）')

    p = mkp('clear', 'U-5: 安全清除工作記憶（session 條目）')
    p.add_argument('--all', dest='target', action='store_const', const='all',
                   default='session', help='清除所有 L3 知識節點（危險）')
    p.add_argument('--yes', '-y', action='store_true', help='跳過確認（--all 時有效）')

    p = mkp('scan', '舊專案考古掃描，重建 L3 知識')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--local', action='store_true',
                      help='本機模式：零費用，無 API 呼叫（推薦入門）')
    mode.add_argument('--llm', action='store_true',
                      help='LLM 模式：高品質，需要 API key')
    mode.add_argument('--heuristic', action='store_true',
                      help='同 --local（向下相容）')
    p.add_argument('--yes', '-y', action='store_true',
                   help='LLM 模式跳過確認提示')
    p.add_argument('--all', dest='scan_all', action='store_true',
                   help='掃描全部 commit（預設只掃最近 100 個）')
    p.add_argument('--quiet', action='store_true', help='靜默模式')

    p = mkp('health-report', 'FEAT-01：知識庫健康度儀表板')
    p.add_argument('--format', choices=['text','json'], default='text')

    p = mkp('report', 'PH1-06：週期性 ROI + 健康度 + 使用率綜合報告')
    p.add_argument('--days', type=int, default=7, help='回溯天數（預設：7）')
    p.add_argument('--format', choices=['text','json'], default='text')
    p.add_argument('--output', '-o', default=None, help='儲存報告至檔案')

    p = mkp('search', 'PH2-02：純語意搜尋（不組裝 Context，速度更快）')
    p.add_argument('query', nargs='+', help='搜尋關鍵詞')
    p.add_argument('--limit', type=int, default=10, help='最多顯示幾筆（預設 10）')
    p.add_argument('--kind', default=None,
                   choices=['Decision','Pitfall','Rule','ADR','Component','Note'],
                   help='只搜尋特定類型')
    p.add_argument('--scope', default=None, help='只搜尋特定 scope')
    p.add_argument('--format', choices=['text','json'], default='text')

    p = mkp('link-issue', 'PH2-06：連結 Brain 節點與 GitHub/Linear issue（ROI 歸因）')
    p.add_argument('--node-id', dest='node_id', default=None, help='Brain 節點 ID（可用前綴）')
    p.add_argument('--url', default=None, help='GitHub / Linear issue URL')
    p.add_argument('--list', action='store_true', help='列出所有已連結的 issue')

    p = mkp('analytics', 'FEAT-03：使用率分析報告')
    p.add_argument('--format', choices=['text','json'], default='text')
    p.add_argument('--export', choices=['csv'], default=None,
                   help='匯出格式（csv）')
    p.add_argument('--output', '-o', default=None, help='輸出路徑')

    p = mkp('export', 'FEAT-05：匯出知識庫（JSON / Markdown）')
    p.add_argument('--format', choices=['json','markdown','neo4j'], default='json')
    p.add_argument('--kind',   default=None, help='只匯出某類型節點')
    p.add_argument('--scope',  default=None, help='只匯出某 scope 節點')
    p.add_argument('--output', '-o', default=None, help='輸出路徑（預設：brain_export.json）')

    p = mkp('import', 'FEAT-05：匯入知識庫（JSON）')
    p.add_argument('file', help='匯入檔案路徑（brain export 產生的 JSON）')
    p.add_argument('--overwrite', action='store_true', help='覆蓋已存在的節點')
    p.add_argument('--merge-strategy', choices=['skip','overwrite','confidence_wins','interactive'],
                   default='skip', dest='merge_strategy',
                   help='衝突解決策略（預設: skip）')

    p = mkp('index', '向量索引（語意搜尋 Phase 1）')
    p.add_argument('--quiet', action='store_true')

    # FEAT-06: Version history
    p = mkp('timeline', 'FEAT-06：顯示節點版本歷史')
    p.add_argument('node_ref', nargs='+', help='節點 ID 或標題')

    p = mkp('rollback', 'FEAT-06：恢復節點到指定版本')
    p.add_argument('node_id', help='節點 ID')
    p.add_argument('--to', type=int, required=True, help='目標版本號')

    # FEAT-01: history / restore aliases
    p = mkp('history', 'FEAT-01：顯示節點版本歷史（含 change_type）')
    p.add_argument('node_id', help='節點 ID 或標題')

    p = mkp('restore', 'FEAT-01：還原節點到指定版本')
    p.add_argument('node_id', help='節點 ID')
    p.add_argument('--version', type=int, required=True, help='目標版本號')

    # ARCH-05: deprecated subcommand
    p = mkp('deprecated', 'ARCH-05：管理已棄用節點（list / purge）')
    p.add_argument('deprecated_sub', nargs='?', default='list',
                   choices=['list', 'purge'], help='子命令（預設：list）')
    p.add_argument('--limit', type=int, default=50, help='列出筆數上限（預設 50）')
    p.add_argument('--older-than', dest='older_than', type=int, default=90,
                   help='purge：刪除棄用超過幾天的節點（預設 90）')

    # FEAT-13
    p = mkp('deprecate', 'FEAT-13：標記節點為棄用')
    p.add_argument('node_id', help='節點 ID')
    p.add_argument('--replaced-by', default='', dest='replaced_by', help='取代節點 ID')
    p.add_argument('--reason', default='', help='棄用原因')

    p = mkp('lifecycle', 'FEAT-13：查看節點生命週期')
    p.add_argument('node_id', help='節點 ID')

    # FEAT-07: Cross-project migration
    p = mkp('migrate', 'FEAT-07：跨專案知識遷移')
    p.add_argument('--from', dest='from_path', required=True,
                   help='來源 brain.db 路徑（或含 .brain/ 的目錄）')
    p.add_argument('--to', dest='to_path', default=None,
                   help='目標目錄（預設：當前工作目錄）')
    p.add_argument('--scope', default='global', help='遷移指定 scope（預設 global）')
    p.add_argument('--min-confidence', dest='min_confidence', type=float, default=0.0,
                   help='只遷移信心值 >= 此值的節點（預設 0.0）')
    p.add_argument('--dry-run', action='store_true', help='預覽模式（不實際寫入）')

    # VISION-03: Federation
    p = mkp('fed', 'VISION-03：跨專案聯邦知識共享（export / import / sync / subscribe）')
    p.add_argument('fed_sub', nargs='?', default='list',
                   choices=['export','import','sync','imports','subscribe','unsubscribe','list'],
                   help='子命令（預設：list）')
    p.add_argument('--output',    '-o', default=None, help='匯出路徑（export 時使用）')
    p.add_argument('--scope',     default='global',   help='匯出 scope（預設 global）')
    p.add_argument('--confidence',type=float, default=0.5, help='最低信心值（預設 0.5）')
    p.add_argument('--max-nodes', dest='max_nodes', type=int, default=500)
    p.add_argument('--project',   default='',         help='專案名稱（export 時嵌入 bundle）')
    p.add_argument('bundle_path', nargs='?', default='', help='Bundle JSON 路徑（import 時使用）')
    p.add_argument('--dry-run',   dest='dry_run', action='store_true')
    p.add_argument('--domain',    default='',     help='領域（subscribe / unsubscribe 時使用）')
    p.add_argument('--add-source',    dest='add_source',    default=None,
                   help='sync：新增來源（格式：name:bundle_path）')
    p.add_argument('--remove-source', dest='remove_source', default=None,
                   help='sync：移除來源（依名稱）')

    # DEEP-03: Counterfactual
    p = mkp('counterfactual', 'DEEP-03：反事實推理')
    p.add_argument('hypothesis', nargs='+', help='假設條件（如：如果我們用 NoSQL）')

    p = mkp('webui', 'D3.js 視覺化（驗證知識庫）')
    p.add_argument('--port', type=int, default=7890)

    p = mkp('session', 'FEAT-04：管理 L1a 工作記憶（list / archive）')
    p.add_argument('session_sub', nargs='?', default='list',
                   choices=['list', 'archive'], help='子命令（預設：list）')
    p.add_argument('--session', default='', help='archive：指定 session ID（預設：當前）')
    p.add_argument('--older-than', dest='older_than', type=int, default=0,
                   help='archive：同時清理超過 N 天的歸檔')

    p = mkp('serve', '啟動 OpenAI 相容 API（讓 Ollama/LM Studio/Cursor 查詢知識）')
    p.add_argument('--port',           type=int,   default=7891,  help='監聽 port（預設：7891）')
    p.add_argument('--production',     action='store_true',       help='生產模式：使用 Gunicorn multi-worker')
    p.add_argument('--workers',        type=int,   default=4,     help='Gunicorn worker 數量（--production 時有效）')
    p.add_argument('--host',           default='0.0.0.0',         help='綁定 host（預設 0.0.0.0）')
    p.add_argument('--mcp',            action='store_true',        help='MCP Server 模式（Claude Code / Cursor 直接連接）')
    p.add_argument('--readonly',        action='store_true',        help='唯讀模式：禁止寫入操作，適合團隊共享查詢')
    p.add_argument('--slack-webhook',  dest='slack_webhook', default=None,
                   help='FEAT-10: Slack Incoming Webhook URL（覆蓋 BRAIN_SLACK_WEBHOOK_URL）')


    # 無參數時：印出設定區塊 + 標準 argparse help
    if len(sys.argv) == 1:
        print(_settings_block())
        print()
        parser.print_help()
        return

    # ── 常見打字錯誤自動修正 ─────────────────────────────────
    _aliases = {
        'server':       'serve',
        'start':        'serve',
        'run':          'serve',
        'ui':           'webui',
        'web':          'webui',
        'web-ui':       'webui',
        'stat':         'status',
        'info':         'status',
        'query':        'context',
        'embed':        'index',
        'check':        'validate',
        'verify':       'validate',
        'export_rules': 'export-rules',
        'rules':        'export-rules',
    }
    # 偵測多餘的 'brain' 前綴（用戶輸入：python brain.py brain serve）
    if len(sys.argv) > 2 and sys.argv[1] == 'brain':
        print(f"  {D}（提示：直接用 brain.py {sys.argv[2]}，不需要再打 'brain'）{R}")
        sys.argv.pop(1)

    if len(sys.argv) > 1 and sys.argv[1] in _aliases:
        corrected = _aliases[sys.argv[1]]
        import sys as _sys
        print(f"  [90m（已修正：{sys.argv[1]} → {corrected}）[0m")
        _sys.argv[1] = corrected

    # ── 廢棄命令提示（v9.3）────────────────────────────────────────────
    _deprecated_cmds = {
        'daemon':       ('status',     'brain status 查看系統狀態（daemon 已整合）'),
        'watch-ack':    ('watch',      'brain watch --ack <id>（watch-ack 已整合）'),
        'mcp-install':  ('serve',      'brain serve --mcp --install（mcp-install 已整合）'),
        'causal-chain': ('add-causal', 'brain add-causal --list（causal-chain 已整合）'),
    }
    if len(sys.argv) > 1 and sys.argv[1] in _deprecated_cmds:
        new_cmd, hint = _deprecated_cmds[sys.argv[1]]
        print(f"  {D}⚠ '{sys.argv[1]}' 已廢棄，自動導向：{C}{new_cmd}{R}")
        print(f"  {D}建議改用：{hint}{R}")
        sys.argv[1] = new_cmd

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
        'meta':          cmd_meta_knowledge,
        'doctor':        cmd_doctor,
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
        'counterfactual': cmd_counterfactual,
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
