"""project_brain/cli_admin.py — System administration CLI commands (CLI-01)"""
import sys
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from project_brain.cli_utils import (
    R, B, D, G, Y, RE, C, P, GR, W,
    _workdir, _ok, _err, _info, _Spinner,
    _brain, _check_l2_health, _scan_banner, _verify_sqlite_vec,
)
from project_brain.constants import DEFAULT_SEARCH_LIMIT


def cmd_init(args):
    """初始化 Project Brain（建立 .brain/ + brain.toml + git hook + CLAUDE.md）"""
    wd         = _workdir(args)
    local_only = getattr(args, 'local_only', False)

    # 完整初始化（DB + git hook + CLAUDE.md + MCP）
    from project_brain.setup_wizard import run_setup
    run_setup(workdir=wd)

    # brain.toml 生成（setup_wizard 完成後補上）
    bd = Path(wd) / ".brain"
    try:
        from project_brain.brain_config import generate_brain_toml
        toml_path = bd / "brain.toml"
        if toml_path.exists():
            _info(f"brain.toml 已存在，略過（使用 'brain config init' 重新生成）")
        else:
            generate_brain_toml(bd, local_only=local_only)
            if local_only:
                _ok(f"brain.toml 已生成（Ollama 本地模式）")
                _info("LLM：gemma4:27b on Ollama（需要先執行 ollama serve && ollama pull gemma4:27b）")
                _info("所有資料完全離線，不呼叫任何外部 API")
            else:
                _ok(f"brain.toml 已生成（可編輯 {toml_path} 調整設定）")
    except Exception as _e:
        logger.debug("brain.toml generation failed", exc_info=True)

    # synonyms.json（自訂同義詞設定檔）
    try:
        import json as _j
        _syn_path = bd / 'synonyms.json'
        if not _syn_path.exists():
            _default_synonyms = {
                "_comment": "PH2-05: 自訂同義詞設定檔。新增你的業務術語，會與內建同義詞合併。格式：{ '術語': ['同義詞1','同義詞2'] }",
                "範例術語": ["example_term", "sample"],
            }
            _syn_path.write_text(_j.dumps(_default_synonyms, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as _e:
        logger.debug("synonyms.json creation failed", exc_info=True)


def cmd_setup(args):
    """brain setup 是 brain init 的別名（向後相容）"""
    cmd_init(args)


def cmd_status(args):
    """查看知識庫狀態（L1/L2/L3 三層，彩色輸出）"""
    wd = _workdir(args)
    b  = _brain(wd)
    print(b.status())


def cmd_health(args):
    """REFACTOR-01: 已整合至 doctor --mcp-port，保留供向後相容。"""
    mcp_port = getattr(args, 'mcp_port', None)
    port_hint = f" --mcp-port {mcp_port}" if mcp_port else " --mcp-port 3000"
    print(f"  \033[33m⚠ brain health 已整合至 brain doctor\033[0m")
    print(f"  \033[90m  請改用：brain doctor{port_hint}\033[0m")
    import socket, time as _time
    G = "\033[32m"; Y = "\033[33m"; R = "\033[31m"; RE = "\033[0m"

    # ── MCP TCP 連接 ──────────────────────────────
    port = getattr(args, "mcp_port", None) or int(os.environ.get("BRAIN_MCP_PORT", "3000"))
    t0 = _time.monotonic()
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.close()
        ms = int((_time.monotonic() - t0) * 1000)
        print(f"  {G}✅ MCP server 回應{RE}  port={port}  latency={ms}ms")
    except OSError as e:
        print(f"  {R}❌ MCP server 無回應{RE}  port={port}  ({e})")
        print(f"  {Y}提示：執行 brain serve --mcp 啟動 MCP server{RE}")

    # ── .brain 目錄 ───────────────────────────────
    wd = _workdir(args)
    brain_dir = Path(wd) / ".brain"
    if brain_dir.exists():
        db_path = brain_dir / "brain.db"
        kb_path = brain_dir / "knowledge_graph.db"
        print(f"  {G}✅ .brain 目錄存在{RE}  {brain_dir}")
        for p, label in [(db_path, "brain.db"), (kb_path, "knowledge_graph.db")]:
            if p.exists():
                size_kb = p.stat().st_size // 1024
                print(f"     {G}✓{RE} {label:<24} {size_kb} KB")
            else:
                print(f"     {Y}⚠{RE} {label:<24} 不存在")
    else:
        print(f"  {R}❌ .brain 目錄不存在{RE}  執行 brain init 初始化")


def cmd_setup(args):
    """One-command setup (first-time use)."""
    wd = _workdir(args)
    from project_brain.setup_wizard import run_setup
    run_setup(workdir=wd)


def cmd_config(args):
    """顯示並驗證所有設定來源（brain config）"""
    wd = args.workdir or os.environ.get("BRAIN_WORKDIR") or os.getcwd()
    brain_dir = Path(wd) / ".brain"

    # brain config init：重新生成 brain.toml
    subcmd = getattr(args, 'config_subcmd', None)
    if subcmd == 'init':
        from project_brain.brain_config import generate_brain_toml
        toml_path = brain_dir / "brain.toml"
        if toml_path.exists():
            answer = input(f"  brain.toml 已存在，確認覆蓋？ [y/N] ").strip().lower()
            if answer != 'y':
                _info("已取消。")
                return
        generate_brain_toml(brain_dir)
        _ok(f"brain.toml 已重新生成：{toml_path}")
        return

    print(f"\n{B}⚙  Project Brain — 設定來源一覽{R}\n")

    # brain.toml（新）
    toml_path = brain_dir / "brain.toml"
    print(f"  {C}0. .brain/brain.toml{R}", f"{'✓' if toml_path.exists() else '（未設定，使用預設值）  brain config init 可生成'}")
    if toml_path.exists():
        try:
            from project_brain.brain_config import load_config
            cfg = load_config(brain_dir)
            print(f"     LLM：{cfg.pipeline.llm.provider} / {cfg.pipeline.llm.model}")
            print(f"     pipeline.enabled：{cfg.pipeline.enabled}")
            print(f"     decay.enabled：{cfg.decay.enabled}")
        except Exception as e:
            print(f"     {RE}讀取失敗：{e}{R}")

    cfg_path = brain_dir / "config.json"
    print(f"\n  {C}1. .brain/config.json{R}", f"{'✓' if cfg_path.exists() else '✗ 不存在'}")
    if cfg_path.exists():
        try:
            cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
            for k, v in cfg_data.items():
                print(f"     {k}: {v}")
        except Exception as e:
            print(f"     {RE}讀取失敗：{e}{R}")

    decay_path = brain_dir / "decay_config.json"
    print(f"\n  {C}2. .brain/decay_config.json{R}", f"{'✓' if decay_path.exists() else '（未設定，使用預設值）'}")
    if decay_path.exists():
        try:
            decay_data = json.loads(decay_path.read_text(encoding="utf-8"))
            for k, v in decay_data.items():
                print(f"     {k}: {v}")
        except Exception as e:
            print(f"     {RE}讀取失敗：{e}{R}")

    fed_path = brain_dir / "federation.json"
    print(f"\n  {C}3. .brain/federation.json{R}", f"{'✓' if fed_path.exists() else '（未設定）'}")
    if fed_path.exists():
        try:
            fed_data = json.loads(fed_path.read_text(encoding="utf-8"))
            sources = fed_data.get("sync_sources", [])
            print(f"     sync_sources: {len(sources)} 個來源")
        except Exception as e:
            print(f"     {RE}讀取失敗：{e}{R}")

    brain_env = brain_dir / ".env"
    print(f"\n  {C}4. .brain/.env{R}", f"{'✓' if brain_env.exists() else '（未設定）'}")
    if brain_env.exists():
        try:
            for line in brain_env.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key = line.split('=', 1)[0]
                    print(f"     {key}=***")
        except Exception as e:
            print(f"     {RE}讀取失敗：{e}{R}")

    root_env = Path(wd) / ".env"
    print(f"\n  {C}5. {root_env}{R}", f"{'✓' if root_env.exists() else '（未設定）'}")
    if root_env.exists():
        try:
            count = sum(1 for line in root_env.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.strip().startswith('#') and '=' in line)
            print(f"     {count} 個環境變數")
        except Exception as e:
            print(f"     {RE}讀取失敗：{e}{R}")

    brain_env_vars = {k: v for k, v in os.environ.items() if k.startswith("BRAIN_")}
    print(f"\n  {C}6. 目前 BRAIN_* 環境變數{R}", f"（{len(brain_env_vars)} 個）")
    for k, v in sorted(brain_env_vars.items()):
        display_v = "***" if any(s in k for s in ("KEY","TOKEN","SECRET","PASSWORD")) else v
        print(f"     {k}={display_v}")

    print()


def cmd_optimize(args):
    """C-1/C-3: 資料庫維護 — VACUUM + ANALYZE + FTS5 rebuild（brain optimize）"""
    from project_brain.brain_db import BrainDB
    wd    = args.workdir or os.environ.get("BRAIN_WORKDIR") or os.getcwd()
    brain_dir = Path(wd) / ".brain"
    if not brain_dir.exists():
        print(f"  {RE}✗ 找不到 .brain/，請先執行 brain init{R}")
        return
    print(f"  {C}⚙ brain optimize — 正在最佳化知識庫...{R}")
    db  = BrainDB(brain_dir)
    res = db.optimize()
    before_kb = res["size_before_bytes"] / 1024
    after_kb  = res["size_after_bytes"]  / 1024
    saved_kb  = res["saved_bytes"]       / 1024
    print(f"  {G}✓ VACUUM + ANALYZE 完成{R}")
    print(f"  {G}✓ FTS5 索引重建：{res['fts5_status']}{R}")
    print(f"  {B}磁碟使用：{before_kb:.1f} KB → {after_kb:.1f} KB  節省 {saved_kb:.1f} KB{R}")
    if getattr(args, 'prune_episodes', False):
        days    = getattr(args, 'older_than', 365)
        deleted = db.prune_episodes(older_than_days=days)
        if deleted:
            print(f"  {G}✓ 清理 episode：刪除 {deleted} 筆超過 {days} 天的 L2 記錄{R}")
        else:
            print(f"  {D}ℹ 無超過 {days} 天的 episode 記錄需要清理{R}")


def cmd_clear(args):
    """U-5: 安全清除工作記憶（brain clear）"""
    from project_brain.session_store import SessionStore
    wd    = args.workdir or os.environ.get("BRAIN_WORKDIR") or os.getcwd()
    brain_dir = Path(wd) / ".brain"
    if not brain_dir.exists():
        print(f"  {RE}✗ 找不到 .brain/，請先執行 brain init{R}")
        return

    target = getattr(args, 'target', 'session')
    if target == 'all':
        if not getattr(args, 'yes', False):
            print(f"  {Y}⚠ 警告：這將清除所有 L3 知識節點！{R}")
            ans = input("  輸入 'yes' 確認，或按 Enter 取消：").strip().lower()
            if ans != 'yes':
                print(f"  {D}已取消{R}")
                return
        from project_brain.brain_db import BrainDB
        db = BrainDB(brain_dir)
        n  = db.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        db.conn.execute("DELETE FROM nodes")
        db.conn.execute("DELETE FROM edges")
        db.conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
        db.conn.commit()
        print(f"  {G}✓ 已清除 {n} 個知識節點與所有邊{R}")
    else:
        store   = SessionStore(brain_dir=brain_dir)
        deleted = store.clear_session()
        purged  = store._purge_expired()
        print(f"  {G}✓ 已清除 {deleted} 個工作記憶條目，{purged} 個過期條目{R}")
        print(f"  {D}提示：使用 brain clear --all 可清除所有 L3 知識（危險操作）{R}")


def cmd_scan(args):
    """舊專案考古掃描：分析 git 歷史，重建 L3 知識圖譜"""
    import os, subprocess as _sp
    wd        = _workdir(args)
    verbose   = not getattr(args, 'quiet', False)
    use_local = getattr(args, 'local', False) or getattr(args, 'heuristic', False)
    use_llm   = getattr(args, 'llm', False)
    yes       = getattr(args, 'yes', False)
    scan_all  = getattr(args, 'scan_all', False)
    limit     = 999_999 if scan_all else 100
    bd        = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請先執行：brain setup"); return

    if use_local:
        scope_msg = "全部 commit" if scan_all else "最近 100 個 commit"
        _scan_banner("local", scope=scope_msg)
        try:
            log = _sp.check_output(
                ["git", "log", f"--max-count={limit}",
                 "--pretty=format:%H|%ae|%s", "--diff-filter=M"],
                cwd=wd, text=True, stderr=_sp.DEVNULL
            )
        except Exception:
            _err("無法讀取 git 歷史"); return

        lines = [l for l in log.strip().splitlines() if l.strip()]
        from project_brain.engine import ProjectBrain
        b  = ProjectBrain(wd)
        ok = 0
        with _Spinner("解析 commit", total=len(lines)) as sp:
            for line in lines:
                parts = line.split("|", 2)
                if len(parts) < 3:
                    sp.update("（格式不符，略過）")
                    continue
                commit_hash, author, msg = parts
                chunk = b._heuristic_extract(msg, commit_hash)
                if chunk:
                    sp.update(f"[{chunk['type']}] {msg}")
                    node_id = b.extractor.make_id(chunk["type"], chunk["title"] + chunk["content"])
                    b.db.add_node(node_id, chunk["type"], chunk["title"],
                                  content=chunk["content"],
                                  confidence=chunk["confidence"])
                    b.graph.add_node(node_id, chunk["type"], chunk["title"],
                                     content=chunk["content"],
                                     source_url=f"git-{commit_hash[:8]}")
                    ok += 1
                else:
                    sp.update(f"略過：{msg}")
        _ok(f"完成：{ok}/{len(lines)} 筆知識寫入 L3")
        _info("接著執行：brain embed  →  建立向量索引")
        return

    try:
        from project_brain.brain_config import load_config, _find_brain_dir
        _cfg     = load_config(_find_brain_dir())
        provider = _cfg.pipeline.llm.provider
        model_name = _cfg.pipeline.llm.model
    except Exception:
        provider   = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic")
        model_name = os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5-20251001")

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or
                   os.environ.get("OPENAI_API_KEY") or
                   provider in ("openai", "ollama"))
    if not has_key:
        _err("找不到 API key，無法使用 LLM 模式")
        print(f"""
  選擇一種方式繼續：

  {G}1. 本機掃描（免費，無需 API）{R}
     brain scan --local

  {G}2. 本地 Ollama（免費）{R}
     ollama pull gemma4:27b
     在 brain.toml 設定 provider="ollama", model="gemma4:27b"
     brain scan --llm

  {G}3. Claude Haiku（約 $0.05 / 100 commits）{R}
     export ANTHROPIC_API_KEY=sk-ant-...
     brain scan --llm
""")
        return
    scope_msg  = "全部 commit" if scan_all else "最近 100 個 commit"
    _scan_banner("llm", provider=provider, model=model_name, scope=scope_msg)

    if not yes:
        try:
            ans = input("  繼續？ [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"
        if ans not in ("y", "yes"):
            _info("已取消。使用 --local 可零費用掃描。")
            return
        print()

    try:
        log_lines = _sp.check_output(
            ["git", "log", f"--max-count={limit}", "--pretty=format:%H|%s"],
            cwd=wd, text=True, stderr=_sp.DEVNULL
        ).strip().splitlines()
        import re as _re
        skip = [r"^(Merge|bump|version|release|format|lint|style|typo)", r"^\d+\.\d+"]
        total = sum(
            1 for l in log_lines
            if l.strip() and not any(
                _re.match(p, l.split("|",1)[-1].strip(), _re.IGNORECASE)
                for p in skip
            )
        )
    except Exception:
        total = limit

    b = _brain(wd)

    _orig   = b.extractor.from_git_commit
    _sp_ctx = _Spinner("LLM 分析", total=total)
    _sp_ctx.__enter__()

    def _patched(commit_hash, commit_msg, diff):
        _sp_ctx.update(commit_msg)
        return _orig(commit_hash, commit_msg, diff)

    b.extractor.from_git_commit = _patched
    try:
        report = b.scan(verbose=False, limit=limit)
    finally:
        _sp_ctx.__exit__(None, None, None)
        b.extractor.from_git_commit = _orig

    print(report)


def cmd_health_report(args):
    """REFACTOR-01: 已整合至 report，保留供向後相容。"""
    print(f"  {Y}⚠ brain health-report 已整合至 brain report{R}")
    print(f"  {D}  請改用：brain report --format {getattr(args,'format','text')}{R}")
    wd = _workdir(args)
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)
    r  = db.health_report()

    fmt = getattr(args, 'format', 'text')
    if fmt == 'json':
        import json as _j
        print(_j.dumps(r, ensure_ascii=False, indent=2))
        return

    score = r["health_score"]
    color = G if score >= 0.7 else (Y if score >= 0.4 else RE)
    bar_w = 20
    filled = int(score * bar_w)
    bar = f"{G}{'█' * filled}{GR}{'░' * (bar_w - filled)}{R}"

    print(f"\n  {B}{P}🧠  Knowledge Health Report{R}")
    print(f"  {GR}{'═' * 46}{R}")
    print(f"  Health Score  {bar}  {color}{B}{score:.0%}{R}")
    print()

    _info(f"Nodes: {B}{r['total_nodes']}{R}  ({', '.join(f'{t}:{n}' for t,n in r['by_type'].items())})")
    _info(f"Avg confidence: {r['avg_confidence']:.2f}  Low-conf: {r['low_confidence_nodes']}")
    _info(f"Stale nodes: {r['stale_nodes']}  Deprecated: {r['deprecated_nodes']}  Expired: {r['expired_nodes']}")
    _info(f"FTS5 coverage: {r['fts5_coverage']}/{r['total_nodes']}  Vector: {r['vector_coverage']}/{r['total_nodes']}")
    _info(f"Episodes: {r['episodes']}  Sessions: {r['sessions']}  Recent (7d): {r['recent_7d']}")

    if r['stale_nodes'] > 0:
        print(f"\n  {Y}⚠ {r['stale_nodes']} 個節點已超過 90 天且信心值 < 0.5{R}")
        print(f"  {D}  可考慮執行 brain doctor --fix 清理{R}")
    if r['vector_coverage'] < r['total_nodes'] * 0.8:
        print(f"\n  {Y}⚠ 向量索引覆蓋率不足{R}")
        print(f"  {D}  執行：brain index{R}")
    print()


def cmd_report(args):
    """PH1-06: 週期性 ROI + 健康度 + 使用率綜合報告（brain report）"""
    wd = _workdir(args)
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    import sqlite3 as _sqlite3
    from project_brain.analytics_engine import AnalyticsEngine

    db_path = None
    for name in ("brain.db", "knowledge_graph.db"):
        p = bd / name
        if p.exists():
            db_path = p
            break
    if not db_path:
        _err("找不到 brain.db，請先執行 brain init"); return

    period = getattr(args, 'days', 7) or 7
    fmt    = getattr(args, 'format', 'text')
    out    = getattr(args, 'output', None)

    conn = _sqlite3.connect(str(db_path))
    conn.row_factory = _sqlite3.Row
    try:
        engine = AnalyticsEngine(conn)
        report = engine.generate_report(period_days=period)
    finally:
        conn.close()

    if fmt == 'json':
        import json as _j
        text = _j.dumps(report, ensure_ascii=False, indent=2)
        if out:
            out_path = Path(out)
            if out_path.is_dir():
                out_path = out_path / "brain_report.json"
            out_path.write_text(text, encoding='utf-8')
            _ok(f"報告已儲存：{out_path}")
        else:
            print(text)
        return

    if fmt == 'html':
        # FEAT-05: generate Chart.js HTML report with timeseries
        import json as _j
        ts = engine.generate_timeseries(period_days=period)
        roi_data = report["roi"]
        html_out = out or str(Path(wd) / "brain_report.html")
        if Path(html_out).is_dir():
            html_out = str(Path(html_out) / "brain_report.html")

        growth_labels = _j.dumps([r["bucket"] for r in ts["growth"]])
        growth_data   = _j.dumps([r["added"]  for r in ts["growth"]])
        conf_labels   = _j.dumps([r["range"]  for r in ts["confidence_dist"]])
        conf_data     = _j.dumps([r["count"]  for r in ts["confidence_dist"]])
        roi_score     = roi_data.get("knowledge_roi_score") or 0
        total_nodes   = report["usage"]["total_nodes"]
        recent_adds   = report["usage"]["recent_adds"]
        summary       = report["summary"]

        html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>Project Brain Report</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<style>
  body{{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:32px}}
  h1{{font-size:22px;margin-bottom:4px}}
  .meta{{color:#8b949e;font-size:13px;margin-bottom:32px}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
  .card{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:24px}}
  .card h2{{font-size:14px;color:#8b949e;margin:0 0 16px;text-transform:uppercase;letter-spacing:.08em}}
  .roi-score{{font-size:48px;font-weight:700;color:#4368e4}}
  .stat{{font-size:13px;color:#8b949e;margin-top:8px}}
  .stat span{{color:#e6edf3;font-weight:600}}
  canvas{{max-height:220px}}
  @media(max-width:720px){{.grid{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
<h1>🧠 Project Brain Report</h1>
<div class="meta">Generated {report['generated_at']} · Last {period}d window</div>
<div class="grid">
  <div class="card">
    <h2>ROI Score</h2>
    <div class="roi-score">{roi_score:.0%}</div>
    <div class="stat">Total nodes: <span>{total_nodes}</span></div>
    <div class="stat">Added last {period}d: <span>{recent_adds}</span></div>
    <div class="stat" style="margin-top:16px;color:#c9d1d9">{summary}</div>
  </div>
  <div class="card">
    <h2>Confidence Distribution</h2>
    <canvas id="confChart"></canvas>
  </div>
  <div class="card" style="grid-column:1/-1">
    <h2>Knowledge Growth (last {period}d · by {ts['bucket']})</h2>
    <canvas id="growthChart"></canvas>
  </div>
</div>
<script>
new Chart(document.getElementById('confChart'),{{
  type:'bar',
  data:{{labels:{conf_labels},datasets:[{{
    label:'Nodes',data:{conf_data},
    backgroundColor:'rgba(67,104,228,0.7)',borderRadius:4
  }}]}},
  options:{{plugins:{{legend:{{display:false}}}},scales:{{
    x:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}},
    y:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}}
  }}}}
}});
new Chart(document.getElementById('growthChart'),{{
  type:'line',
  data:{{labels:{growth_labels},datasets:[{{
    label:'Nodes Added',data:{growth_data},
    borderColor:'#4368e4',backgroundColor:'rgba(67,104,228,0.12)',
    fill:true,tension:0.4,pointRadius:3
  }}]}},
  options:{{plugins:{{legend:{{display:false}}}},scales:{{
    x:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}},
    y:{{ticks:{{color:'#8b949e'}},grid:{{color:'#21262d'}}}}
  }}}}
}});
</script>
</body></html>"""
        Path(html_out).write_text(html, encoding='utf-8')
        _ok(f"HTML 報告已儲存：{html_out}")
        return

    roi   = report["roi"]
    usage = report["usage"]
    score = roi["knowledge_roi_score"]
    score_c = G if score >= 0.70 else (Y if score >= 0.40 else RE)
    bar_w = 20
    filled = int(score * bar_w)
    bar = f"{G}{'█' * filled}{GR}{'░' * (bar_w - filled)}{R}"

    print(f"\n  {B}{P}📊  Brain Report  {GR}(last {period}d){R}")
    print(f"  {GR}{'═' * 50}{R}")

    print(f"\n  {B}{C}ROI Metrics{R}")
    print(f"  ROI Score     {bar}  {score_c}{B}{score:.0%}{R}")
    hit  = roi['query_hit_rate']
    ukr  = roi['useful_knowledge_rate']
    pas  = roi['pitfall_avoidance_score']
    _info(f"Query hit rate:          {f'{hit:.0%}' if hit is not None else 'n/a (no traces)'}")
    _info(f"Useful knowledge rate:   {f'{ukr:.0%}' if ukr is not None else 'n/a (no feedback yet)'}")
    _info(f"Pitfall avoidance score: {f'{pas:.0%}' if pas is not None else 'n/a (no pitfalls)'}")

    print(f"\n  {B}{C}Usage{R}")
    _info(f"Total nodes: {B}{usage['total_nodes']}{R}   "
          f"Added last {period}d: {G}{usage['recent_adds']}{R}")
    _info(f"Total queries: {usage['total_queries']}   "
          f"Queries last {period}d: {G}{usage['recent_queries']}{R}")
    if usage['by_type']:
        type_str = "  ".join(f"{t}:{n}" for t, n in usage['by_type'].items())
        _info(f"By type:  {type_str}")

    if report['top_pitfalls']:
        print(f"\n  {B}Most-accessed Pitfall nodes:{R}")
        for n in report['top_pitfalls']:
            print(f"    {GR}{n['access_count']:>3}×{R}  {RE}{n['title'][:55]}{R}")

    print(f"\n  {Y}{report['summary']}{R}\n")

    # REFACTOR-01: --analytics 旗標，整合自 cmd_analytics
    if getattr(args, 'analytics', False):
        from project_brain.brain_db import BrainDB
        _db = BrainDB(bd)
        r   = _db.usage_analytics()
        print(f"  {B}{C}📊  Usage Analytics{R}")
        print(f"  {GR}{'═' * 46}{R}")
        _info(f"Total nodes: {r['total_nodes']}  Episodes: {r['total_episodes']}")
        if r['by_type']:
            _info(f"By type:  {'  '.join(f'{t}:{n}' for t,n in r['by_type'].items())}")
        if r['by_scope']:
            _info(f"By scope: {'  '.join(f'{s}:{n}' for s,n in list(r['by_scope'].items())[:5])}")
        if r['top_accessed_nodes']:
            print(f"\n  {B}Top accessed nodes:{R}")
            for n in r['top_accessed_nodes'][:5]:
                print(f"    {GR}{n['access_count']:>3}×{R}  {n['title'][:50]}")
        if r['knowledge_growth']:
            print(f"\n  {B}Knowledge growth (recent weeks):{R}")
            for w in r['knowledge_growth'][:6]:
                bar = "▓" * min(w['count'], 20)
                print(f"    {GR}{w['week']}{R}  {G}{bar}{R} {w['count']}")
        print()

    if out:
        import json as _j
        out_path = Path(out)
        if out_path.is_dir():
            out_path = out_path / "brain_report.json"
        out_path.write_text(_j.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        _ok(f"詳細報告已儲存：{out_path}")


def cmd_analytics(args):
    """REFACTOR-01: 已整合至 report --analytics，保留供向後相容。"""
    print(f"  {Y}⚠ brain analytics 已整合至 brain report --analytics{R}")
    print(f"  {D}  請改用：brain report --analytics{R}")
    wd = _workdir(args)
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)
    r  = db.usage_analytics()

    fmt = getattr(args, 'format', 'text')
    if fmt == 'json':
        import json as _j
        print(_j.dumps(r, ensure_ascii=False, indent=2))
        return

    export_fmt = getattr(args, 'export', None)
    if export_fmt == 'csv':
        import csv, io
        out = getattr(args, 'output', None) or str(Path(wd) / "brain_analytics.csv")
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=[
            'node_id','title','type','scope','access_count',
            'last_accessed','confidence','importance'
        ])
        writer.writeheader()
        _db = BrainDB(bd)
        rows = _db.conn.execute(
            "SELECT id, title, type, scope, access_count, last_accessed,"
            " confidence, importance FROM nodes ORDER BY access_count DESC"
        ).fetchall()
        for row in rows:
            writer.writerow({
                'node_id': row[0], 'title': row[1], 'type': row[2],
                'scope': row[3], 'access_count': row[4] or 0,
                'last_accessed': (row[5] or '')[:10],
                'confidence': row[6], 'importance': row[7],
            })
        Path(out).write_text(buf.getvalue(), encoding='utf-8')
        _ok(f"CSV 匯出完成：{out}")
        return

    print(f"\n  {B}{C}📊  Usage Analytics{R}")
    print(f"  {GR}{'═' * 46}{R}")
    _info(f"Total nodes: {r['total_nodes']}  Episodes: {r['total_episodes']}")

    if r['by_type']:
        type_str = "  ".join(f"{t}:{n}" for t, n in r['by_type'].items())
        _info(f"By type:  {type_str}")

    if r['by_scope']:
        scope_str = "  ".join(f"{s}:{n}" for s, n in list(r['by_scope'].items())[:5])
        _info(f"By scope: {scope_str}")

    if r['top_accessed_nodes']:
        print(f"\n  {B}Top accessed nodes:{R}")
        for n in r['top_accessed_nodes'][:5]:
            print(f"    {GR}{n['access_count']:>3}×{R}  {n['title'][:50]}")

    if r['knowledge_growth']:
        print(f"\n  {B}Knowledge growth (recent weeks):{R}")
        for w in r['knowledge_growth'][:6]:
            bar = "▓" * min(w['count'], 20)
            print(f"    {GR}{w['week']}{R}  {G}{bar}{R} {w['count']}")
    print()


def cmd_export(args):
    """FEAT-05: 匯出知識庫（brain export）"""
    wd   = _workdir(args)
    bd   = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    db   = BrainDB(bd)
    fmt  = getattr(args, 'format', 'json')
    kind = getattr(args, 'kind',   None)
    sc   = getattr(args, 'scope',  None)
    out  = getattr(args, 'output', None)

    if fmt == 'markdown':
        content = db.export_markdown(node_type=kind, scope=sc)
        ext = ".md"
    elif fmt == 'neo4j':
        content = db.export_neo4j(node_type=kind, scope=sc)
        ext = ".cypher"
    elif fmt == 'graphml':
        # FEAT-05: GraphML 格式，可直接匯入 Gephi / yEd / Neo4j
        content = db.export_graphml(node_type=kind, scope=sc)
        ext = ".graphml"
    else:
        import json as _j
        content = _j.dumps(db.export_json(node_type=kind, scope=sc),
                           ensure_ascii=False, indent=2)
        ext = ".json"

    if out:
        Path(out).write_text(content, encoding="utf-8")
        _ok(f"匯出完成：{out}")
    else:
        default = Path(wd) / f"brain_export{ext}"
        default.write_text(content, encoding="utf-8")
        _ok(f"匯出完成：{default}")


def cmd_import(args):
    """FEAT-05/12: 匯入知識庫（brain import <file>）"""
    wd  = _workdir(args)
    bd  = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    src = getattr(args, 'file', None)
    if not src or not Path(src).exists():
        _err(f"找不到匯入檔案：{src}"); return

    from project_brain.brain_db import BrainDB
    import json as _j
    db             = BrainDB(bd)
    overwrite      = getattr(args, 'overwrite', False)
    merge_strategy = getattr(args, 'merge_strategy', 'skip')
    if overwrite:
        merge_strategy = 'overwrite'

    try:
        data = _j.loads(Path(src).read_text(encoding="utf-8"))
    except Exception as e:
        _err(f"讀取匯入檔案失敗：{e}"); return

    r = db.import_json(data, merge_strategy=merge_strategy)

    if merge_strategy == 'interactive' and r.get('conflicts'):
        print(f"\n  發現 {len(r['conflicts'])} 個衝突節點，請逐一選擇：\n")
        resolved = 0
        for c in r['conflicts']:
            ex  = c['existing']
            inc = c['incoming']
            print(f"  衝突: \"{ex.get('title','?')}\" (id={ex.get('id','?')})")
            print(f"    現有: confidence={ex.get('confidence',0.8):.2f}  updated={ex.get('updated_at','?')[:10]}")
            print(f"    匯入: confidence={inc.get('confidence',0.8):.2f}  updated={inc.get('updated_at','?')[:10]}")
            print("  選項: [k]eep existing  [i]mport new  [m]erge (取較高 confidence)  [s]kip")
            choice = input("  > ").strip().lower()
            if choice == 'i':
                db.import_json({"nodes": [inc], "edges": []}, merge_strategy='overwrite')
                resolved += 1
            elif choice == 'm':
                db.import_json({"nodes": [inc], "edges": []}, merge_strategy='confidence_wins')
                resolved += 1
        print()
        _ok(f"互動式解決完成：解決 {resolved}/{len(r['conflicts'])} 個衝突")
    else:
        _ok(f"匯入完成：節點 {r['nodes']}  邊 {r['edges']}  跳過 {r['skipped']}  錯誤 {r['errors']}")


def cmd_index(args):
    """Phase 1: 批次為現有知識建立向量索引（提升語意搜尋）"""
    wd    = _workdir(args)
    quiet = getattr(args, 'quiet', False)
    bd    = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    from project_brain.embedder  import get_embedder

    emb = get_embedder()
    if not emb:
        _info("Embedding 已停用（BRAIN_EMBED_PROVIDER=none）")
        return

    db      = BrainDB(bd)
    pending = db.get_nodes_without_vectors()
    if not pending:
        _info(f"所有節點已有向量索引（共 {db.stats()['total']} 個）")
        return

    model_name = getattr(emb, 'MODEL', type(emb).__name__)
    if not quiet:
        _info(f"向量索引：{len(pending)} 個節點  模型：{model_name}")
        if "tfidf" in model_name.lower():
            _info("使用本地 TF-IDF（零依賴）。更高品質：ollama pull nomic-embed-text")

    ok = 0
    with _Spinner("建立向量索引", total=len(pending)) as sp:
        for node in pending:
            text = f"{node['title']} {node['content']}"[:2000]
            vec  = emb.embed(text)
            if vec:
                db.add_vector(node['id'], vec, model=model_name)
                ok += 1
            sp.update(node.get('title', '')[:45])

    if not quiet:
        _ok(f"完成：{ok}/{len(pending)} 個節點已建立向量索引")
        _info("brain ask 現在使用混合搜尋（FTS5 × 0.4 + 向量 × 0.6）")


def _display_width(s: str) -> int:
    """Return terminal column width of s (CJK wide chars count as 2)."""
    import unicodedata
    w = 0
    for ch in s:
        eaw = unicodedata.east_asian_width(ch)
        w += 2 if eaw in ('W', 'F') else 1
    return w


def _trunc_display(s: str, max_cols: int) -> str:
    """Truncate s so its display width fits within max_cols columns."""
    import unicodedata
    w, out = 0, []
    for ch in s:
        eaw = unicodedata.east_asian_width(ch)
        cw = 2 if eaw in ('W', 'F') else 1
        if w + cw > max_cols:
            break
        out.append(ch)
        w += cw
    return ''.join(out)


def _build_confidence_prompt(kind: str, title: str, content: str) -> str:
    """Simplified English prompt for --ai-review confidence scoring.

    Asks only for a single confidence float — no recommendation/reason —
    to maximise JSON compliance on small local models (llama3.2, qwen2.5, etc.).
    English instructions improve instruction-following vs Chinese on these models.
    format="json" is already enforced by OllamaClient.messages.create().
    """
    return f"""You are a knowledge quality evaluator for a software engineering knowledge base.

Rate the confidence score for this single knowledge entry:

kind: {kind}
title: {title}
content: {content}

Respond with a JSON object only, no other text:
{{"confidence": 0.0}}

Scoring guide:
- 0.80-1.00: Clear, actionable, specific Rule/Pitfall/Decision with concrete context
- 0.50-0.79: Useful but vague, or context-dependent without enough detail
- 0.10-0.49: Too vague, off-topic, duplicated, or noise"""


def _ai_review_nodes(db, node_ids: list[str], ollama_url: str, ollama_model: str) -> int:
    """用 Ollama 審核指定節點，更新 confidence。回傳已更新筆數。

    改善項目（vs 舊版）：
    ① 獨立英文 prompt，只問 confidence（不要 recommendation/reason）
    ② index 對應取代 LLM echo id — BATCH=1 保證一對一，不依賴 LLM 回傳正確 id
    ③ clamp confidence 至 [0.05, 1.0]，超出範圍仍計數而不丟棄
    ④ format:"json" 已由 OllamaClient 內建，根治 JSON 格式錯誤
    """
    import json    as _json
    import sqlite3 as _sqlite3
    from ..krb_ai_assist import OllamaClient, _clean, MAX_CONTENT_PROMPT

    if not node_ids:
        return 0

    client = OllamaClient(base_url=ollama_url)

    try:
        client.list_models()
    except Exception as exc:
        print(f"  [ai-review] ⚠ 無法連線 Ollama（{ollama_url}）：{exc}，跳過 AI 審核")
        return 0

    # 用獨立連線讀取節點，確保看到 Phase 1 提交的新節點
    _read = _sqlite3.connect(str(db.db_path))
    rows = _read.execute(
        f"SELECT id, type, title, content FROM nodes"
        f" WHERE id IN ({','.join('?'*len(node_ids))})",
        node_ids,
    ).fetchall()
    _read.close()

    updated = 0
    n_total = len(rows)
    import shutil as _shutil
    term_w  = _shutil.get_terminal_size((80, 24)).columns

    for i, (nid, kind, title, content) in enumerate(rows):
        # ── progress line ───────────────────────────────────────────
        idx          = i + 1
        w_idx        = len(str(n_total))
        title_budget = term_w - w_idx * 2 - 10
        title_preview = _trunc_display(_clean(title), max(10, title_budget))
        pad = term_w - _display_width(title_preview) - w_idx * 2 - 10
        print(
            f"\r  [{idx:{w_idx}}/{n_total}] {title_preview}{' ' * max(0, pad)}",
            end="", flush=True,
        )
        # ② index 對應：不依賴 LLM echo id
        prompt = _build_confidence_prompt(
            kind    = kind,
            title   = _clean(title),
            content = _clean(content or "")[:MAX_CONTENT_PROMPT],
        )
        try:
            resp = client.messages.create(
                model      = ollama_model,
                max_tokens = 64,   # only {"confidence": 0.xx} needed
                messages   = [{"role": "user", "content": prompt}],
            )
            raw  = resp.content[0].text.strip()
            data = _json.loads(raw)
            if isinstance(data, list) and data:
                data = data[0]
            if not isinstance(data, dict):
                continue
            raw_conf = data.get("confidence", None)
            if raw_conf is None:
                continue
            # ③ clamp instead of reject
            conf = max(0.05, min(1.0, float(raw_conf)))
            db.conn.execute(
                "UPDATE nodes SET confidence=? WHERE id=?",
                (conf, nid),
            )
            updated += 1
        except Exception as exc:
            print(f"\r  ⚠ [{idx}/{n_total}] 失敗：{exc}{' ' * 20}")

    print(f"\r  {' ' * (term_w - 2)}\r", end="", flush=True)  # clear progress line
    db.conn.commit()
    return updated


def _cmd_backfill_git(args):
    """FEAT-07: 從 git 歷史回填知識節點（含正確 created_at 時間戳）。

    三階段處理：
    1. 掃描 git log，對尚未學習的 commit 呼叫 learn_from_commit()
    2. 補正 created_at 時間戳（用 valid_from）
    3. 可選：用 Ollama AI 審核新增節點的信心分數（--ai-review）
    """
    import re as _re
    import subprocess
    from ..brain_db import BrainDB

    workdir  = Path(_workdir(args)).resolve()
    brain_dir = workdir / ".brain"
    if not brain_dir.exists():
        print(f"[backfill-git] 找不到 .brain 目錄：{brain_dir}", file=sys.stderr)
        return 1

    dry_run    = getattr(args, "dry_run", False)
    limit      = getattr(args, "limit", 200)
    if limit == 0:
        limit = 999999  # FEAT-09: --limit 0 means no limit
    ai_review  = getattr(args, "ai_review", False)
    import os as _os
    ollama_url = getattr(args, "ollama_url", None) or \
                 _os.environ.get("BRAIN_OLLAMA_URL", "http://localhost:11434")
    ollama_model = getattr(args, "ollama_model", None) or \
                   _os.environ.get("BRAIN_OLLAMA_MODEL", "llama3.2")

    # ── 1. 取得 git 歷史 ─────────────────────────────────────────────
    try:
        result = subprocess.run(
            ["git", "-C", str(workdir), "log",
             f"--max-count={limit}", "--pretty=%H|%s|%aI"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print("[backfill-git] 找不到 git 歷史", file=sys.stderr)
            return 1
        all_commits: list[tuple[str, str, str]] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) >= 2:
                all_commits.append((
                    parts[0].strip(),
                    parts[1].strip(),
                    parts[2].strip() if len(parts) > 2 else "",
                ))
    except Exception as exc:
        print(f"[backfill-git] git log 失敗：{exc}", file=sys.stderr)
        return 1

    # ── 2. 找出已處理的 commit hash ──────────────────────────────────
    db = BrainDB(brain_dir)
    processed: set[str] = set()

    for row in db.conn.execute(
        "SELECT DISTINCT source_url FROM nodes WHERE source_url != ''"
    ).fetchall():
        url = (row[0] or "").strip()
        if url:
            processed.add(url)
            processed.add(url[:8])

    for row in db.conn.execute(
        "SELECT DISTINCT source FROM episodes WHERE source LIKE 'git-%'"
    ).fetchall():
        src = (row[0] or "").strip()
        if src.startswith("git-"):
            processed.add(src[4:])   # short hash stored by cmd_sync

    new_commits = [
        (h, msg, date) for h, msg, date in all_commits
        if h not in processed and h[:8] not in processed
    ]

    import shutil as _shutil
    term_w = _shutil.get_terminal_size((80, 24)).columns
    _BAR   = "─" * min(term_w, 60)
    _G, _R, _B, _D, _Y = "\033[92m", "\033[0m", "\033[1m", "\033[2m", "\033[93m"

    n_all  = len(all_commits)
    n_new  = len(new_commits)
    n_done = n_all - n_new

    print(f"{_B}[backfill-git]{_R} git 歷史 {n_all} 筆"
          f"  已處理 {n_done}  待回填 {_B}{n_new}{_R}")

    if dry_run:
        print(f"{_D}{_BAR}{_R}")
        for h, msg, date in new_commits:
            msg_trunc = _trunc_display(msg, term_w - 24)
            print(f"  {_D}[dry-run]{_R} {h[:8]}  {_D}({date[:10]}){_R}  {msg_trunc}")
        return 0

    phases_total = 2 + (1 if ai_review else 0)

    # ─── Phase 1: 學習 git 歷史 ──────────────────────────────────────
    print(f"\n{_D}{_BAR}{_R}")
    print(f" {_B}Phase 1/{phases_total}{_R}  學習 git 歷史")
    print(f"{_D}{_BAR}{_R}")

    if not new_commits:
        print(f"  {_G}✓{_R}  所有 commit 均已學習，無需回填\n")
        total_learned = 0
    else:
        from ..engine import ProjectBrain
        brain         = ProjectBrain(str(workdir))
        total_learned = 0
        n_total       = len(new_commits)
        w_idx         = len(str(n_total))
        # Columns: "  [xxx/xxx] xxxxxxxx  <msg>  +N"
        # fixed parts: 2 + 1 + w_idx + 1 + w_idx + 2 + 8 + 2 + 3 = ~20
        msg_budget = max(10, term_w - w_idx * 2 - 18)

        for i, (commit_hash, msg, _date) in enumerate(new_commits):
            msg_trunc = _trunc_display(msg, msg_budget)
            # right-pad with spaces so shorter msgs erase longer ones
            line_len  = _display_width(msg_trunc) + w_idx * 2 + 18
            pad       = max(0, term_w - line_len - 1)
            print(
                f"\r  [{i+1:{w_idx}}/{n_total}] {commit_hash[:8]}  {msg_trunc}{' ' * pad}",
                end="", flush=True,
            )
            try:
                learned = brain.learn_from_commit(commit_hash)
                total_learned += learned
            except Exception:
                pass

        print(f"\r  {' ' * (term_w - 2)}\r", end="", flush=True)  # clear line
        print(f"  {_G}✓{_R}  新增 {_B}{total_learned}{_R} 個知識節點"
              f"  {_D}（掃描 {n_total} 個 commit）{_R}\n")

    # ─── Phase 2: 時間戳補正 ─────────────────────────────────────────
    print(f"{_D}{_BAR}{_R}")
    print(f" {_B}Phase 2/{phases_total}{_R}  時間戳補正")
    print(f"{_D}{_BAR}{_R}")

    # valid_from 由 _store_chunk 從 commit date 寫入，是可靠的真實時間來源。
    # 格式：ISO 8601 "2026-04-01T16:13:00+08:00" → 正規化為 "2026-04-01 16:13:00"
    ts_updated = db.conn.execute("""
        UPDATE nodes
        SET created_at = replace(substr(valid_from, 1, 19), 'T', ' ')
        WHERE length(valid_from) > 0
          AND substr(valid_from, 1, 10) < substr(created_at, 1, 10)
    """).rowcount
    db.conn.commit()
    print(f"  {_G}✓{_R}  補正 {_B}{ts_updated}{_R} 個節點的 created_at\n")

    # ─── Phase 3: AI 審核（可選）─────────────────────────────────────
    reviewed   = 0
    review_ids: list = []
    if ai_review:
        import sqlite3 as _sqlite3
        _rconn = _sqlite3.connect(str(brain_dir / "brain.db"))
        review_ids = [
            r[0] for r in _rconn.execute(
                "SELECT id FROM nodes WHERE confidence = 0.5 ORDER BY created_at DESC"
            ).fetchall()
        ]
        _rconn.close()

        print(f"{_D}{_BAR}{_R}")
        print(f" {_B}Phase 3/{phases_total}{_R}  AI 信心審核"
              f"  {_D}（model={ollama_model}，{len(review_ids)} 個節點）{_R}")
        print(f"{_D}{_BAR}{_R}")

        if not review_ids:
            print(f"  {_D}--{_R}  無待審節點（所有節點 confidence ≠ 0.5）\n")
        else:
            reviewed = _ai_review_nodes(db, review_ids, ollama_url, ollama_model)
            print(f"  {_G}✓{_R}  已更新 {_B}{reviewed}/{len(review_ids)}{_R} 個節點的 confidence\n")

    # ─── 總結 ──────────────────────────────────────────────────────
    print(f"{_D}{_BAR}{_R}")
    parts = [f"新增知識節點 {total_learned}"]
    if ts_updated:
        parts.append(f"時間戳補正 {ts_updated}")
    if ai_review:
        parts.append(f"AI 審核 {reviewed}/{len(review_ids) if review_ids else 0}")
    print(f"  {_G}✅ 回填完成{_R}  {'  ·  '.join(parts)}")
    print(f"{_D}{_BAR}{_R}\n")

    return 0


def cmd_doctor(args):
    """系統健康檢查與自動修復（brain doctor [--fix]）"""
    import sqlite3, shutil, stat, json
    from project_brain import __version__

    fix   = getattr(args, 'fix', False)
    wd    = _workdir(args)
    bd    = Path(wd) / ".brain"

    ok_n = warn_n = err_n = 0
    fixes_applied = []

    def _ok2(msg):
        nonlocal ok_n; ok_n += 1
        print(f"  {G}✓{R}  {msg}")

    def _warn2(msg, hint=""):
        nonlocal warn_n; warn_n += 1
        print(f"  {Y}⚠{R}  {msg}")
        if hint:
            print(f"     {D}{hint}{R}")

    def _err2(msg, hint="", fix_desc=""):
        nonlocal err_n; err_n += 1
        print(f"  {RE}✗{R}  {msg}")
        if hint:
            print(f"     {D}{hint}{R}")
        if fix_desc:
            tag = f"{G}[已修復]{R}" if fix else f"{C}[--fix 可修復]{R}"
            print(f"     {tag} {fix_desc}")

    def _section(title):
        print(f"\n  {B}{C}{title}{R}")
        print(f"  {D}{'─' * 44}{R}")

    print(f"\n  {B}{P}🔍  brain doctor  —  系統健康檢查{R}  {D}v{__version__}{R}")

    _section("環境")

    import sys
    pv = sys.version_info
    if pv >= (3, 10):
        _ok2(f"Python {pv.major}.{pv.minor}.{pv.micro}")
    else:
        _err2(f"Python {pv.major}.{pv.minor}.{pv.micro}（需要 3.10+）",
              "請升級 Python")

    brain_bin = shutil.which("brain")
    if brain_bin:
        _ok2(f"brain 指令已安裝  {D}({brain_bin}){R}")
    else:
        _warn2("brain 指令不在 PATH 中", "執行：pip install -e . 或確認 PATH 設定")

    try:
        from project_brain.brain_config import load_config
        _cfg     = load_config(bd if bd.exists() else None)
        provider = _cfg.pipeline.llm.provider
        model    = _cfg.pipeline.llm.model
        base_url = _cfg.pipeline.llm.base_url
    except Exception:
        provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
        model    = os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5-20251001")
        base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if provider in ("ollama", "openai"):
        _ok2(f"本地 LLM 模式  {D}({model} @ {base_url}){R}")
    elif api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        _ok2(f"ANTHROPIC_API_KEY 已設定  {D}({masked}){R}")
    else:
        _warn2("ANTHROPIC_API_KEY 未設定，AI 提取功能不可用",
               "設定後可使用 brain scan / brain sync 自動提取知識\n"
               "     或改用本地 LLM：在 brain.toml 設定 provider='ollama'")

    env_wd = os.environ.get("BRAIN_WORKDIR", "")
    bd_found = Path(wd, ".brain").exists()
    if env_wd:
        _ok2(f"BRAIN_WORKDIR={env_wd}")
    elif bd_found:
        _ok2(f"工作目錄自動偵測：{wd}  （.brain/ 已找到，無需設定 BRAIN_WORKDIR）")
    else:
        _warn2(f"找不到 .brain/（當前目錄：{wd}）",
               "在專案根目錄執行 brain setup 初始化")

    _section("資料庫")

    if not bd.exists():
        _err2(".brain/ 目錄不存在", "執行：brain setup", "brain setup")
        if fix:
            import subprocess
            subprocess.run(["brain", "setup", "--workdir", wd], check=False)
            fixes_applied.append("執行 brain setup")
    else:
        _ok2(f".brain/ 目錄存在  {D}({bd}){R}")

        db_path = bd / "brain.db"
        if not db_path.exists():
            _err2("brain.db 不存在", "執行：brain setup")
        else:
            size_kb = db_path.stat().st_size // 1024
            try:
                conn = sqlite3.connect(str(db_path))
                conn.row_factory = sqlite3.Row

                wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                if wal == "wal":
                    _ok2(f"brain.db 正常  {D}({size_kb} KB, WAL 模式){R}")
                else:
                    _warn2(f"brain.db 未使用 WAL 模式（當前：{wal}）",
                           "多進程並發讀寫時建議 WAL 模式")

                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
                required = {"nodes", "edges", "episodes", "sessions"}
                missing  = required - tables
                if missing:
                    _err2(f"資料庫缺少表格：{', '.join(missing)}",
                          "Schema 可能需要遷移，執行：brain setup")
                else:
                    nodes    = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
                    edges    = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
                    episodes = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
                    _ok2(f"Schema 完整  {D}(節點 {nodes}  邊 {edges}  情節 {episodes}){R}")

                    deprecated = conn.execute(
                        "SELECT COUNT(*) FROM nodes WHERE confidence < 0.2"
                    ).fetchone()[0]
                    if deprecated:
                        _warn2(f"{deprecated} 個節點信心值 < 0.2（可能過時）",
                               "執行：brain status 查看詳情")
                    else:
                        _ok2("無過時知識（confidence ≥ 0.2）")

                    # FEAT-06: deprecated ratio warning (> 20% threshold)
                    if nodes > 0:
                        dep_ratio = deprecated / nodes
                        if dep_ratio > 0.20:
                            _warn2(
                                f"deprecated 比例過高：{deprecated}/{nodes} = {dep_ratio:.0%}（超過 20% 警戒線）",
                                "大量知識過時，建議更新或執行 brain doctor --fix 清理"
                            )

                    # FEAT-06: contradiction node ratio
                    try:
                        conflict_count = conn.execute(
                            "SELECT COUNT(*) FROM edges WHERE relation='CONFLICTS_WITH'"
                        ).fetchone()[0]
                        if conflict_count > 0:
                            _warn2(
                                f"偵測到 {conflict_count} 對矛盾知識（CONFLICTS_WITH 邊）",
                                "執行：brain report 查看詳情；可啟用 BRAIN_CONFLICT_RESOLVE=1 自動仲裁"
                            )
                        else:
                            _ok2("無矛盾知識節點")
                    except Exception as _cf_err:
                        logger.debug("conflict check failed: %s", _cf_err)

                    try:
                        fts_count = conn.execute(
                            "SELECT COUNT(*) FROM nodes_fts"
                        ).fetchone()[0]
                        if fts_count < nodes:
                            _err2(
                                f"FTS5 索引不完整：{fts_count}/{nodes} 個節點已建立索引",
                                "全文搜尋將遺漏未索引的節點",
                                "重建 FTS5 索引"
                            )
                            if fix:
                                conn.execute(
                                    "INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')"
                                )
                                conn.commit()
                                fixes_applied.append("重建 FTS5 全文搜尋索引")
                        else:
                            _ok2(f"FTS5 索引完整  {D}({fts_count}/{nodes} 個節點){R}")
                    except Exception as _fts_err:
                        _err2(
                            f"FTS5 索引損壞或不存在：{_fts_err}",
                            "全文搜尋功能不可用",
                            "重建 FTS5 索引"
                        )
                        if fix:
                            try:
                                conn.execute(
                                    "INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')"
                                )
                                conn.commit()
                                fixes_applied.append("重建損壞的 FTS5 索引")
                            except Exception:
                                _err2("FTS5 重建失敗，請執行：brain index")

                conn.close()
            except Exception as e:
                _err2(f"brain.db 讀取失敗：{e}")

        krb_path = bd / "review_board.db"
        if krb_path.exists():
            try:
                kc = sqlite3.connect(str(krb_path))
                pending = kc.execute(
                    "SELECT COUNT(*) FROM staged_nodes WHERE status='pending'"
                ).fetchone()[0]
                kc.close()
                if pending > 0:
                    _warn2(f"KRB 有 {pending} 筆待審知識",
                           "執行：brain review list")
                else:
                    _ok2("KRB 暫存區清空")
            except Exception as _e:
                logger.debug("KRB pending check failed", exc_info=True)

    _section("Git 整合")

    git_root = Path(wd)
    if not (git_root / ".git").exists():
        for p in git_root.parents:
            if (p / ".git").exists():
                git_root = p
                break

    if not (git_root / ".git").exists():
        _warn2("未偵測到 git repo",
               "brain 的自動學習功能需要 git")
    else:
        _ok2(f"git repo  {D}({git_root}){R}")

        hook_path = git_root / ".git" / "hooks" / "post-commit"
        if not hook_path.exists():
            _err2("post-commit hook 未安裝，commit 後不會自動學習",
                  "執行：brain setup",
                  "重新安裝 git hook")
            if fix:
                from project_brain.setup_wizard import run_setup
                run_setup(wd)
                fixes_applied.append("重新安裝 git hook")
        else:
            mode = hook_path.stat().st_mode
            if mode & stat.S_IXUSR:
                _ok2("post-commit hook 已安裝且可執行")
            else:
                _err2("post-commit hook 存在但不可執行",
                      "", "設定可執行權限")
                if fix:
                    hook_path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP)
                    fixes_applied.append("設定 hook 可執行權限")

            content = hook_path.read_text(errors="ignore")
            if "brain" in content or "project_brain" in content:
                _ok2("hook 內容有效（含 brain 指令）")
            else:
                _warn2("hook 存在但不含 brain 指令，可能是其他工具安裝的",
                       f"檢查：{hook_path}")

    _section("MCP 整合")

    try:
        import mcp  # noqa: F401
        _ok2("mcp 套件已安裝")
    except ImportError:
        _warn2("mcp 套件未安裝，MCP Server 不可用",
               "pip install mcp")

    claude_cfg = Path.home() / ".claude" / "settings.json"
    if claude_cfg.exists():
        try:
            data = json.loads(claude_cfg.read_text())
            servers = data.get("mcpServers", {})
            if "project-brain" in servers:
                cfg_wd = servers["project-brain"].get("env", {}).get("BRAIN_WORKDIR", "")
                if cfg_wd == wd:
                    _ok2(f"Claude Code MCP 設定正常  {D}(BRAIN_WORKDIR={cfg_wd}){R}")
                else:
                    _warn2(
                        f"Claude Code MCP 的 BRAIN_WORKDIR 指向不同目錄",
                        f"目前：{cfg_wd}\n     預期：{wd}\n"
                        "     執行：brain setup 更新設定"
                    )
            else:
                _err2("Claude Code settings.json 未設定 project-brain",
                      "", "加入 MCP 設定")
                if fix:
                    mcp_entry = {
                        "command": "python",
                        "args": ["-m", "project_brain.mcp_server"],
                        "env": {"BRAIN_WORKDIR": wd}
                    }
                    data.setdefault("mcpServers", {})
                    data["mcpServers"]["project-brain"] = mcp_entry
                    claude_cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                    fixes_applied.append("已寫入 Claude Code MCP 設定")
        except Exception as e:
            _warn2(f"Claude Code settings.json 讀取失敗：{e}")
    else:
        _warn2("未找到 Claude Code settings.json",
               "確認 Claude Code 已安裝，或手動設定 MCP")

    _section("相依套件")

    def _check_pkg(pkg, import_name=None, extra="", optional=False):
        name = import_name or pkg
        try:
            mod = __import__(name)
            ver = getattr(mod, "__version__", "")
            ver_str = f"  {D}({ver}){R}" if ver else ""
            _ok2(f"{pkg}{ver_str}")
        except ImportError:
            if optional:
                _warn2(f"{pkg} 未安裝（選填）", f"pip install {pkg}{extra}")
            else:
                _err2(f"{pkg} 未安裝", f"pip install {pkg}{extra}")

    _check_pkg("anthropic",   optional=True)
    _check_pkg("mcp",         optional=True)
    _check_pkg("openai",      optional=True, extra="  （Ollama / LM Studio）")

    _section("向量搜尋引擎")
    _verify_sqlite_vec()

    _section("知識庫健康")

    db_path = bd / "brain.db"
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            if nodes == 0:
                _warn2("知識庫是空的",
                       "執行：brain add \"第一條規則\"  或  brain scan")
            elif nodes < 5:
                _warn2(f"只有 {nodes} 個知識節點，效果有限",
                       "執行：brain scan --all 掃描歷史 commit")
            else:
                _ok2(f"{nodes} 個知識節點")

            try:
                vec_count = conn.execute(
                    "SELECT COUNT(*) FROM node_vectors"
                ).fetchone()[0]
                if nodes > 0:
                    pct = vec_count / nodes * 100
                    if pct >= 80:
                        _ok2(f"向量索引覆蓋率 {pct:.0f}%  {D}({vec_count}/{nodes}){R}")
                    elif pct > 0:
                        _warn2(f"向量索引覆蓋率 {pct:.0f}%  {D}({vec_count}/{nodes}){R}",
                               "執行：brain index 補齊索引")
                    else:
                        _warn2("尚未建立向量索引（僅使用 FTS5 關鍵字搜尋）",
                               "執行：brain index 啟用混合語意搜尋")
            except Exception:
                _warn2("向量索引表不存在（僅使用 FTS5 搜尋）",
                       "執行：brain index")

            scopes = conn.execute(
                "SELECT scope, COUNT(*) c FROM nodes GROUP BY scope ORDER BY c DESC LIMIT 5"
            ).fetchall()
            if scopes:
                scope_str = "  ".join(
                    f"{r['scope'] or 'global'}({r['c']})" for r in scopes
                )
                _ok2(f"Scope 分布  {D}{scope_str}{R}")

            conn.close()
        except Exception as e:
            _warn2(f"知識庫健康檢查失敗：{e}")
    else:
        _warn2("brain.db 不存在，跳過知識庫健康檢查")

    # REFACTOR-01: 吸收 health 的 MCP port 檢查（--mcp-port）
    mcp_port = getattr(args, 'mcp_port', None)
    if mcp_port is not None:
        import socket, time as _time
        _section("MCP Server")
        port = int(mcp_port or os.environ.get("BRAIN_MCP_PORT", "3000"))
        t0 = _time.monotonic()
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=2)
            s.close()
            ms = int((_time.monotonic() - t0) * 1000)
            _ok2(f"MCP server 回應  port={port}  latency={ms}ms")
        except OSError as e:
            _err2(f"MCP server 無回應  port={port}  ({e})",
                  "執行：brain serve --mcp 啟動 MCP server")

    print(f"\n  {D}{'─' * 44}{R}")
    parts = []
    if ok_n:   parts.append(f"{G}{ok_n} 通過{R}")
    if warn_n: parts.append(f"{Y}{warn_n} 警告{R}")
    if err_n:  parts.append(f"{RE}{err_n} 錯誤{R}")
    print(f"  {'  '.join(parts)}")

    if fixes_applied:
        print(f"\n  {G}已自動修復：{R}")
        for f_ in fixes_applied:
            print(f"    {G}✓{R}  {f_}")

    if err_n and not fix:
        print(f"\n  {D}執行 brain doctor --fix 嘗試自動修復{R}")

    print()
