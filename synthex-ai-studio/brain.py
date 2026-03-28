#!/usr/bin/env python3
"""
brain — Project Brain 獨立 CLI

Project Brain 的記憶系統，完全獨立於 SYNTHEX AI STUDIO。
可以單獨安裝、單獨使用，也可以和任何 LLM 工具整合。

使用方式：
    python brain.py init   --workdir /your/project
    python brain.py status --workdir /your/project
    python brain.py serve  --workdir /your/project   # OpenAI 相容 API

安裝為全域命令（選填）：
    pip install -e .   # 然後直接用 brain <cmd>
"""
import sys, os
from pathlib import Path

# 確保能 import core/brain
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

# ── ANSI 顏色 ─────────────────────────────────────────────────
R="\033[0m"; B="\033[1m"; D="\033[2m"
G="\033[92m"; Y="\033[93m"; RE="\033[91m"
C="\033[96m"; P="\033[95m"; GR="\033[90m"; W="\033[97m"

BANNER = f"""{P}{B}
  🧠  Project Brain  {GR}v4.0.0  ·  獨立記憶系統{R}
  {D}不依賴 SYNTHEX AI STUDIO，可搭配任何 LLM 使用{R}
"""

def _workdir(args) -> str:
    import argparse
    wd = getattr(args, 'workdir', None) or os.environ.get('BRAIN_WORKDIR') or os.getcwd()
    return str(Path(wd).resolve())

def _brain(workdir: str):
    from core.brain.engine import ProjectBrain
    return ProjectBrain(workdir)

def _ok(msg):  print(f"{G}✓{R} {msg}")
def _err(msg): print(f"{RE}✗{R} {msg}")
def _info(msg):print(f"{C}ℹ{R} {msg}")

# ══════════════════════════════════════════════════════════════
#  命令實作
# ══════════════════════════════════════════════════════════════

def cmd_init(args):
    """初始化 Project Brain（建立 .brain/ 目錄 + 知識圖譜）"""
    wd   = _workdir(args)
    name = getattr(args, 'name', '') or Path(wd).name
    b    = _brain(wd)
    print(b.init(project_name=name))

def cmd_status(args):
    """查看知識庫狀態（L1/L2/L3 三層，彩色輸出）"""
    wd = _workdir(args)
    b  = _brain(wd)
    print(b.status())

def cmd_add(args):
    """手動加入一筆知識"""
    wd      = _workdir(args)
    title   = ' '.join(args.title) if args.title else ''
    content = args.content or ''
    kind    = args.kind or 'Pitfall'
    tags    = args.tags or []
    if not title:
        _err("請提供 --title"); return
    b = _brain(wd)
    node_id = b.add_knowledge(title, content, kind, tags)
    _ok(f"知識已加入：{C}{B}{node_id}{R}")
    _info(f"類型：{kind}  標題：{title}")

def cmd_scan(args):
    """考古掃描：從 git 歷史提取所有知識（呼叫 AI API）"""
    wd = _workdir(args)
    _info(f"開始考古掃描：{C}{wd}{R}")
    _info(f"{D}分析 git 歷史，視 commit 數量需要數分鐘...{R}")
    b = _brain(wd)
    report = b.scan(verbose=True)
    report_path = Path(wd) / '.brain' / 'SCAN_REPORT.md'
    _ok(f"考古報告：{C}{report_path}{R}")
    print(f"\n{GR}{report[:800]}{R}")

def cmd_learn(args):
    """從指定 git commit 學習知識"""
    wd     = _workdir(args)
    commit = args.commit or 'HEAD'
    b = _brain(wd)
    n = b.learn_from_commit(commit)
    _ok(f"從 {C}{commit}{R} 學習了 {W}{B}{n}{R} 個知識片段")

def cmd_context(args):
    """查詢：這個任務需要注入哪些知識？"""
    wd   = _workdir(args)
    task = ' '.join(args.task) if args.task else ''
    if not task:
        _err("請提供 --task 或直接寫任務描述"); return
    b   = _brain(wd)
    ctx = b.get_context(task)
    if ctx:
        print(f"\n{C}{B}🧠  相關知識注入{R}\n{GR}{'─'*50}{R}")
        print(ctx)
        print(f"{GR}{'─'*50}{R}")
    else:
        print(f"{Y}⚠{R}  知識庫為空，請先執行：{D}brain scan{R}")

def cmd_distill(args):
    """知識蒸餾：產生可給任何 LLM 使用的知識摘要"""
    wd     = _workdir(args)
    layers = args.layers or ['context', 'prompts', 'lora']
    print(f"\n{P}{B}⚗  知識蒸餾{R}  {D}layers={layers}{R}")
    b = _brain(wd)
    result = b.distiller.distill_all(layers=layers)
    print(result.summary())
    print(f"\n{G}{B}💡 使用方式{R}")
    out_dir = Path(wd) / '.brain' / 'distilled'
    if (out_dir / 'SYNTHEX_KNOWLEDGE.md').exists():
        print(f"  {C}任何 LLM{R}：複製 {W}{out_dir}/SYNTHEX_KNOWLEDGE.md{R} 的內容到 system prompt")
    print(f"  {C}Cursor{R}：用 .cursorrules 引入 → 見 brain export-rules")
    print(f"  {C}OpenAI 相容{R}：brain serve → POST http://localhost:7891/v1/context")

def cmd_validate(args):
    """自主知識驗證（確認知識是否仍然準確）"""
    wd       = _workdir(args)
    max_api  = args.max_api_calls
    dry_run  = args.dry_run
    print(f"\n{C}{B}🔍  知識驗證{R}  {D}max_api_calls={max_api}  dry_run={dry_run}{R}")
    b = _brain(wd)
    report = b.validator.run(max_api_calls=max_api, dry_run=dry_run)
    print(report.summary())

def cmd_export(args):
    """匯出知識圖譜（Mermaid 格式）"""
    wd  = _workdir(args)
    b   = _brain(wd)
    out = str(Path(wd) / '.brain' / 'graph.md')
    mermaid = b.export_mermaid()
    Path(out).write_text(f"```mermaid\n{mermaid}\n```")
    _ok(f"知識圖譜已匯出：{C}{out}{R}")
    print(f"\n{GR}{mermaid[:500]}{R}")

def cmd_export_rules(args):
    """
    匯出 .cursorrules / CLAUDE.md / system-prompt.md
    讓 Cursor、Claude、ChatGPT 等工具直接讀取知識
    """
    wd     = _workdir(args)
    target = args.target or 'cursorrules'
    b      = _brain(wd)

    # 確保已蒸餾
    distill_path = Path(wd) / '.brain' / 'distilled' / 'SYNTHEX_KNOWLEDGE.md'
    if not distill_path.exists():
        _info("先執行知識蒸餾...")
        b.distiller.distill_all(layers=['context'])

    knowledge = distill_path.read_text(encoding='utf-8')
    intro = f"# 專案知識庫（由 Project Brain v4.0 自動生成）\n# 更新時間：{_now()[:10]}\n\n"

    if target == 'cursorrules':
        out = Path(wd) / '.cursorrules'
        out.write_text(intro + knowledge, encoding='utf-8')
        _ok(f".cursorrules 已更新：{C}{out}{R}")
        _info("Cursor 將在每次對話自動讀取這份知識")

    elif target == 'claude':
        out = Path(wd) / 'CLAUDE.md'
        # 在 CLAUDE.md 末尾加入知識注入區塊
        existing = out.read_text('utf-8') if out.exists() else ''
        marker_start = '<!-- PROJECT_BRAIN_START -->'
        marker_end   = '<!-- PROJECT_BRAIN_END -->'
        block = f"{marker_start}\n\n{knowledge}\n\n{marker_end}"
        if marker_start in existing:
            import re
            existing = re.sub(
                f'{marker_start}.*{marker_end}', block, existing, flags=re.DOTALL
            )
        else:
            existing += f'\n\n{block}'
        out.write_text(existing, encoding='utf-8')
        _ok(f"CLAUDE.md 知識區塊已更新：{C}{out}{R}")

    elif target == 'system-prompt':
        out = Path(wd) / '.brain' / 'system-prompt.md'
        out.write_text(intro + knowledge, encoding='utf-8')
        _ok(f"system-prompt.md 已更新：{C}{out}{R}")
        _info("複製此檔案內容到任何 LLM 的 system prompt 欄位")
        _info(f"ChatGPT：Settings → Custom Instructions")
        _info(f"Gemini：貼入對話開頭")
        _info(f"LM Studio / Ollama：設定 System Prompt")

    elif target == 'openai-compat':
        # 產生 openai-compat 格式的 messages JSON
        import json
        out = Path(wd) / '.brain' / 'context_messages.json'
        messages = [{"role": "system", "content": intro + knowledge}]
        out.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding='utf-8')
        _ok(f"OpenAI 相容格式已產生：{C}{out}{R}")
        _info("在任何 OpenAI SDK 呼叫前 prepend 這個 messages 陣列")

def cmd_serve(args):
    """
    啟動 Project Brain API Server（OpenAI 相容格式）

    提供統一的 REST API，讓任何支援 OpenAI 格式的工具都能查詢知識：
      Ollama、LM Studio、Cursor、Copilot、自訂 Script

    端點：
      GET  /health                → 服務健康狀態
      GET  /v1/context?q=<task>   → 取得知識注入字串
      POST /v1/context            → { "task": "..." } → 知識字串
      GET  /v1/knowledge          → 完整知識摘要（for system prompt）
      GET  /v1/stats              → 知識庫統計
      POST /v1/messages           → OpenAI 相容端點（自動注入知識到 system prompt）
    """
    wd   = _workdir(args)
    port = args.port or 7891

    brain_dir = Path(wd) / '.brain'
    if not brain_dir.exists():
        _err(f"找不到 .brain 目錄，請先執行：brain init --workdir {wd}")
        return

    try:
        from flask import Flask, request, jsonify
        from flask_cors import CORS
    except ImportError:
        _err("請安裝依賴：pip install flask flask-cors")
        return

    from core.brain.engine import ProjectBrain
    brain = ProjectBrain(wd)

    app = Flask(__name__)
    CORS(app)

    @app.route('/health')
    def health():
        return jsonify({
            "status": "ok",
            "version": "4.0.0",
            "workdir": Path(wd).name,
            "nodes": brain.graph.stats().get('nodes', 0),
        })

    @app.route('/v1/stats')
    def stats():
        s = brain.graph.stats()
        return jsonify({
            "nodes":   s.get('nodes', 0),
            "edges":   s.get('edges', 0),
            "by_type": s.get('by_type', {}),
        })

    @app.route('/v1/knowledge')
    def knowledge():
        """返回完整知識摘要（適合直接貼到 system prompt）"""
        distill_path = brain_dir / 'distilled' / 'SYNTHEX_KNOWLEDGE.md'
        if distill_path.exists():
            return distill_path.read_text('utf-8'), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        # 即時蒸餾
        brain.distiller.distill_all(layers=['context'])
        return distill_path.read_text('utf-8'), 200, {'Content-Type': 'text/plain; charset=utf-8'}

    @app.route('/v1/context', methods=['GET', 'POST'])
    def context():
        """根據任務查詢相關知識（精準注入）"""
        task = (request.args.get('q', '')
                or (request.json or {}).get('task', ''))
        if not task:
            return jsonify({"error": "請提供 q 參數或 task 欄位"}), 400
        ctx = brain.get_context(task)
        return jsonify({"task": task, "context": ctx, "found": bool(ctx)})

    @app.route('/v1/messages', methods=['POST'])
    def messages_compat():
        """
        OpenAI 相容端點 — 自動把知識注入 system prompt
        
        支援格式：
          { "messages": [...], "model": "..." }
        
        返回格式（在 messages 開頭插入知識）：
          { "messages": [{"role":"system","content":"<知識>"}, ...] }
        
        用法（任何 OpenAI SDK）：
          # 把 base_url 指向這個 server
          client = OpenAI(base_url="http://localhost:7891", api_key="dummy")
          
          # 或 Ollama
          client = OpenAI(base_url="http://localhost:7891", api_key="ollama")
        """
        data     = request.json or {}
        messages = data.get('messages', [])
        task     = next((m['content'] for m in messages if m.get('role') == 'user'), '')

        # 取得知識注入
        ctx = brain.get_context(task) if task else ''

        if ctx:
            # 在 system message 前面注入知識
            knowledge_msg = {"role": "system", "content": ctx}
            # 找到現有的 system message 並合併，或插入到開頭
            has_system = any(m.get('role') == 'system' for m in messages)
            if has_system:
                enriched = []
                for m in messages:
                    if m.get('role') == 'system':
                        enriched.append({
                            "role": "system",
                            "content": ctx + "\n\n---\n\n" + m['content']
                        })
                    else:
                        enriched.append(m)
            else:
                enriched = [knowledge_msg] + messages
        else:
            enriched = messages

        return jsonify({
            "messages": enriched,
            "knowledge_injected": bool(ctx),
            "knowledge_chars": len(ctx),
        })

    @app.route('/v1/add', methods=['POST'])
    def add_knowledge():
        """新增知識（REST API 方式）"""
        data    = request.json or {}
        title   = data.get('title', '')
        content = data.get('content', '')
        kind    = data.get('kind', 'Pitfall')
        tags    = data.get('tags', [])
        if not title:
            return jsonify({"error": "title 必填"}), 400
        node_id = brain.add_knowledge(title, content, kind, tags)
        return jsonify({"node_id": node_id, "kind": kind, "title": title})

    print(BANNER)
    print(f"  {G}{B}🚀 Project Brain API Server{R}")
    print(f"  {C}http://localhost:{port}{R}")
    print(f"  工作目錄：{GR}{wd}{R}")
    print(f"\n  {B}端點{R}")
    print(f"  {GR}GET  /health{R}              服務健康")
    print(f"  {GR}GET  /v1/knowledge{R}         完整知識摘要（system prompt 用）")
    print(f"  {GR}GET  /v1/context?q=<任務>{R}  精準知識查詢")
    print(f"  {GR}POST /v1/messages{R}           OpenAI 相容，自動注入知識")
    print(f"  {GR}GET  /v1/stats{R}              知識庫統計")
    print()
    print(f"  {B}整合到其他 LLM{R}")
    print(f"  {D}Ollama / LM Studio：{R}")
    print(f"    {GR}curl http://localhost:{port}/v1/knowledge{R}  → 貼到 system prompt")
    print(f"  {D}任何 OpenAI SDK：{R}")
    print(f"    {GR}client = OpenAI(base_url='http://localhost:{port}', api_key='brain'){R}")
    print(f"  {D}Cursor：{R}")
    print(f"    {GR}brain export-rules --target cursorrules{R}")
    print()

    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)

def cmd_webui(args):
    """啟動知識圖譜視覺化 Web UI（D3.js 力導向圖）"""
    wd   = _workdir(args)
    port = args.port or 7890
    db   = Path(wd) / '.brain' / 'knowledge_graph.db'
    if not db.exists():
        _info("DB 不存在，補建中...")
        from core.brain.graph import KnowledgeGraph
        KnowledgeGraph(Path(wd) / '.brain')
    from core.brain.web_ui.server import run_server
    run_server(Path(wd), port=port)

# ══════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════

def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()

def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog='brain',
        description='Project Brain — AI 記憶系統（獨立版，可搭配任何 LLM）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
命令快速參考：
  brain init      --workdir .          初始化記憶系統
  brain status    --workdir .          查看三層記憶狀態
  brain scan      --workdir .          AI 掃描 git 歷史（需要 API Key）
  brain add       --title "..." --content "..." --kind Pitfall
  brain context   --workdir . "實作支付退款功能"
  brain distill   --workdir .          產生 LLM 通用知識摘要
  brain validate  --workdir . --dry-run
  brain export-rules --target cursorrules   → .cursorrules
  brain export-rules --target claude        → CLAUDE.md
  brain export-rules --target system-prompt → 通用格式
  brain serve     --workdir . --port 7891   OpenAI 相容 API
  brain webui     --workdir . --port 7890   D3.js 視覺化

環境變數：
  BRAIN_WORKDIR   預設工作目錄（省略 --workdir）
  GRAPHITI_URL    Graphiti L2 連線（預設 redis://localhost:6379）
  ANTHROPIC_API_KEY  AI 分析功能所需
        """
    )

    sub = parser.add_subparsers(dest='cmd', metavar='<command>')

    def mkp(name, help_text):
        p = sub.add_parser(name, help=help_text)
        p.add_argument('--workdir', '-w', default=None,
                       help='專案目錄（預設：$BRAIN_WORKDIR 或當前目錄）')
        return p

    # init
    p = mkp('init', '初始化 Project Brain')
    p.add_argument('--name', default='', help='專案名稱')

    # status
    mkp('status', '查看三層記憶狀態（L1/L2/L3）')

    # scan
    mkp('scan', '從 git 歷史 AI 掃描並提取知識（需要 ANTHROPIC_API_KEY）')

    # learn
    p = mkp('learn', '從指定 commit 學習知識')
    p.add_argument('--commit', default='HEAD')

    # add
    p = mkp('add', '手動加入一筆知識')
    p.add_argument('--title',   nargs='+', required=True)
    p.add_argument('--content', default='')
    p.add_argument('--kind',    default='Pitfall',
                   choices=['Decision','Pitfall','Rule','ADR','Component'])
    p.add_argument('--tags',    nargs='+', default=[])

    # context
    p = mkp('context', '查詢任務相關知識（Context 注入）')
    p.add_argument('task', nargs='*', help='任務描述')

    # distill
    p = mkp('distill', '知識蒸餾：產生可給任何 LLM 使用的知識摘要')
    p.add_argument('--layers', nargs='+', default=['context','prompts','lora'],
                   choices=['context','prompts','lora'])

    # validate
    p = mkp('validate', '自主知識驗證')
    p.add_argument('--max-api-calls', type=int, default=20)
    p.add_argument('--dry-run', action='store_true')

    # export
    mkp('export', '匯出知識圖譜（Mermaid 格式）')

    # export-rules
    p = mkp('export-rules', '匯出知識到各種 LLM 規則文件')
    p.add_argument('--target', default='cursorrules',
                   choices=['cursorrules','claude','system-prompt','openai-compat'],
                   help=('cursorrules=.cursorrules, claude=CLAUDE.md, '
                         'system-prompt=通用 Markdown, openai-compat=JSON'))

    # serve
    p = mkp('serve', '啟動 OpenAI 相容 API（讓 Ollama/LM Studio/Cursor 查詢知識）')
    p.add_argument('--port', type=int, default=7891)

    # webui
    p = mkp('webui', '啟動 D3.js 知識圖譜視覺化')
    p.add_argument('--port', type=int, default=7890)

    if len(sys.argv) == 1:
        print(BANNER)
        parser.print_help()
        return

    args = parser.parse_args()

    dispatch = {
        'init':         cmd_init,
        'status':       cmd_status,
        'scan':         cmd_scan,
        'learn':        cmd_learn,
        'add':          cmd_add,
        'context':      cmd_context,
        'distill':      cmd_distill,
        'validate':     cmd_validate,
        'export':       cmd_export,
        'export-rules': cmd_export_rules,
        'serve':        cmd_serve,
        'webui':        cmd_webui,
    }

    fn = dispatch.get(args.cmd)
    if fn:
        try:
            fn(args)
        except KeyboardInterrupt:
            print(f"\n{GR}已中止{R}")
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
