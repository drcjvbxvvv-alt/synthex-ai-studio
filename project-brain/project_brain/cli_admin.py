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
    """初始化 Project Brain（建立 .brain/ 目錄 + 知識圖譜）"""
    wd         = _workdir(args)
    name       = getattr(args, 'name', '') or Path(wd).name
    local_only = getattr(args, 'local_only', False)

    if local_only:
        import os
        bd = Path(wd) / ".brain"
        bd.mkdir(exist_ok=True)
        env_path = bd / ".env"
        local_env = (
            "# Project Brain 本地模式（brain init --local-only）\n"
            "# 所有資料不離開本機\n"
            "BRAIN_LLM_PROVIDER=openai\n"
            "BRAIN_LLM_BASE_URL=http://localhost:11434/v1\n"
            "BRAIN_LLM_MODEL=llama3.1:8b\n"
            "BRAIN_LOCAL_ONLY=1\n"
            "# L2 時序記憶使用本地 SQLite（不需要 FalkorDB）\n"
            "GRAPHITI_DISABLED=1\n"
        )
        env_path.write_text(local_env)
        _ok(f"本地模式啟用：設定已寫入 {env_path}")
        _info("LLM：Ollama（需要先執行 ollama serve && ollama pull llama3.1:8b）")
        _info("L2：使用 SQLite 替代 FalkorDB（無需 Docker）")
        _info("所有資料完全離線，不呼叫任何外部 API")
        print()
        os.environ.setdefault("BRAIN_LLM_PROVIDER", "openai")
        os.environ.setdefault("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
        os.environ.setdefault("GRAPHITI_DISABLED", "1")

    b = _brain(wd)
    print(b.init(project_name=name))

    try:
        from project_brain.brain_db import BrainDB
        _bd = Path(wd) / '.brain'
        _db = BrainDB(_bd)
        _db.conn.execute(
            "INSERT OR REPLACE INTO brain_meta(key,value) VALUES('project_name',?)",
            (name,)
        )
        _db.conn.commit()
    except Exception as _e:
        logger.debug("project_name brain_meta write failed", exc_info=True)

    try:
        import json as _j
        _syn_path = Path(wd) / '.brain' / 'synonyms.json'
        if not _syn_path.exists():
            _default_synonyms = {
                "_comment": "PH2-05: 自訂同義詞設定檔。新增你的業務術語，會與內建同義詞合併。格式：{ '術語': ['同義詞1','同義詞2'] }",
                "範例術語": ["example_term", "sample"],
            }
            _syn_path.write_text(_j.dumps(_default_synonyms, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as _e:
        logger.debug("synonyms.json creation failed", exc_info=True)


def cmd_status(args):
    """查看知識庫狀態（L1/L2/L3 三層，彩色輸出）"""
    wd = _workdir(args)
    b  = _brain(wd)
    print(b.status())


def cmd_setup(args):
    """One-command setup (first-time use)."""
    wd = _workdir(args)
    from project_brain.setup_wizard import run_setup
    run_setup(workdir=wd)


def cmd_config(args):
    """顯示並驗證所有設定來源（brain config）"""
    wd = args.workdir or os.environ.get("BRAIN_WORKDIR") or os.getcwd()
    brain_dir = Path(wd) / ".brain"

    print(f"\n{B}⚙  Project Brain — 設定來源一覽{R}\n")

    cfg_path = brain_dir / "config.json"
    print(f"  {C}1. .brain/config.json{R}", f"{'✓' if cfg_path.exists() else '✗ 不存在'}")
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

    provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic")
    has_key  = bool(os.environ.get("ANTHROPIC_API_KEY") or
                    os.environ.get("OPENAI_API_KEY") or
                    provider == "openai")
    if not has_key:
        _err("找不到 API key，無法使用 LLM 模式")
        print(f"""
  選擇一種方式繼續：

  {G}1. 本機掃描（免費，無需 API）{R}
     brain scan --local

  {G}2. 本地 Ollama{R}
     ollama pull qwen2.5:7b
     export BRAIN_LLM_PROVIDER=openai
     export BRAIN_LLM_BASE_URL=http://localhost:11434/v1
     export BRAIN_LLM_MODEL=qwen2.5:7b
     brain scan --llm

  {G}3. Claude Haiku（約 $0.05 / 100 commits）{R}
     export ANTHROPIC_API_KEY=sk-ant-...
     brain scan --llm
""")
        return

    model_name = os.environ.get("BRAIN_LLM_MODEL", "claude-haiku-4-5-20251001")
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
    """FEAT-01: 知識庫健康度儀表板（brain health-report）"""
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

    if out:
        import json as _j
        out_path = Path(out)
        if out_path.is_dir():
            out_path = out_path / "brain_report.json"
        out_path.write_text(_j.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        _ok(f"詳細報告已儲存：{out_path}")


def cmd_analytics(args):
    """FEAT-03: 使用率分析報告（brain analytics）"""
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


def _cmd_backfill_git(args):
    """FEAT-07: 從 git 歷史回填知識節點（含正確 created_at 時間戳）。

    兩階段處理：
    1. 掃描 git log，對尚未學習的 commit 呼叫 learn_from_commit()
    2. 補正已存在節點中 source_url 可對應到 commit 的時間戳
    """
    import re as _re
    import subprocess
    from .brain_db import BrainDB

    workdir  = Path(_workdir(args)).resolve()
    brain_dir = workdir / ".brain"
    if not brain_dir.exists():
        print(f"[backfill-git] 找不到 .brain 目錄：{brain_dir}", file=sys.stderr)
        return 1

    dry_run = getattr(args, "dry_run", False)
    limit   = getattr(args, "limit", 200)

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

    print(
        f"[backfill-git] git 歷史 {len(all_commits)} 筆｜"
        f"已處理 {len(all_commits) - len(new_commits)}｜"
        f"待回填 {len(new_commits)}"
    )

    if dry_run:
        for h, msg, date in new_commits:
            print(f"  [dry-run] {h[:8]} ({date[:10]}): {msg[:70]}")
        return 0

    if not new_commits:
        print("[backfill-git] 所有 commit 均已學習，無需回填")
        # still run phase-2 timestamp fix on existing nodes
    else:
        # ── 3. 對每個未處理的 commit 呼叫 learn_from_commit ──────────
        from .engine import ProjectBrain
        brain = ProjectBrain(str(workdir))
        total_learned = 0
        for i, (commit_hash, msg, _date) in enumerate(new_commits):
            label = f"[{i+1}/{len(new_commits)}] {commit_hash[:8]}: {msg[:55]}"
            try:
                learned = brain.learn_from_commit(commit_hash)
                print(f"  ✓ {label} → {learned} 筆知識")
                total_learned += learned
            except Exception as exc:
                print(f"  ✗ {label} → 跳過（{exc}）")
        print(f"\n  共新增 {total_learned} 個知識節點\n")

    # ── 4. 補正 created_at：用 valid_from 覆蓋錯誤的 datetime('now') ────
    # valid_from 由 _store_chunk 從 commit date 寫入，是可靠的真實時間來源。
    # 格式：ISO 8601 "2026-04-01T16:13:00+08:00" → 正規化為 "2026-04-01 16:13:00"
    ts_updated = db.conn.execute("""
        UPDATE nodes
        SET created_at = replace(substr(valid_from, 1, 19), 'T', ' ')
        WHERE length(valid_from) > 0
          AND substr(valid_from, 1, 10) < substr(created_at, 1, 10)
    """).rowcount

    db.conn.commit()
    print(f"[backfill-git] 時間戳補正：{ts_updated} 個節點")
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

    provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
    api_key  = os.environ.get("ANTHROPIC_API_KEY", "")
    if provider == "openai":
        base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
        model    = os.environ.get("BRAIN_LLM_MODEL", "llama3.1:8b")
        _ok2(f"本地 LLM 模式  {D}({model} @ {base_url}){R}")
    elif api_key:
        masked = api_key[:8] + "..." + api_key[-4:]
        _ok2(f"ANTHROPIC_API_KEY 已設定  {D}({masked}){R}")
    else:
        _warn2("ANTHROPIC_API_KEY 未設定，AI 提取功能不可用",
               "設定後可使用 brain scan / brain sync 自動提取知識\n"
               "     或改用本地 LLM：export BRAIN_LLM_PROVIDER=openai")

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
