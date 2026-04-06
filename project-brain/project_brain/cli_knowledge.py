"""project_brain/cli_knowledge.py — Knowledge management CLI commands (CLI-01)"""
import sys
import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from project_brain.cli_utils import (
    R, B, D, G, Y, RE, C, P, GR, W,
    _workdir, _ok, _err, _info, _Spinner,
    _brain, _infer_scope,
)
from project_brain.constants import DEFAULT_SEARCH_LIMIT


def _cmd_add_interactive(args):
    """PH2-03: 互動式分步輸入（brain add 無參數時觸發）"""
    print(f"\n{C}{B}🧠  Brain Add — 互動模式{R}  {D}（Ctrl+C 取消）{R}\n")

    try:
        content_raw = input(f"  {C}內容{R}（必填，可以是規則/踩坑/決策）：").strip()
    except (KeyboardInterrupt, EOFError):
        print(); _info("已取消"); return None
    if not content_raw:
        _err("內容不可為空"); return None

    kinds = ["Pitfall", "Rule", "Decision", "ADR", "Note"]
    print(f"\n  {C}類型{R}：")
    for i, k in enumerate(kinds, 1):
        clr = {
            "Pitfall": RE, "Rule": C, "Decision": G,
            "ADR": P, "Note": Y,
        }.get(k, W)
        print(f"    {GR}{i}{R}. {clr}{k}{R}")
    try:
        choice = input(f"\n  選擇（1-{len(kinds)}，預設 1=Pitfall）：").strip()
    except (KeyboardInterrupt, EOFError):
        print(); _info("已取消"); return None
    kind = kinds[int(choice) - 1] if choice.isdigit() and 1 <= int(choice) <= len(kinds) else "Pitfall"

    try:
        scope_raw = input(f"\n  {C}Scope{R}（模組名，直接 Enter = 自動推導）：").strip()
    except (KeyboardInterrupt, EOFError):
        print(); _info("已取消"); return None
    scope = scope_raw or "global"

    try:
        conf_raw = input(f"\n  {C}信心值{R}（0.0~1.0，直接 Enter = 0.8）：").strip()
    except (KeyboardInterrupt, EOFError):
        print(); _info("已取消"); return None
    try:
        confidence = float(conf_raw) if conf_raw else 0.8
        confidence = max(0.0, min(1.0, confidence))
    except ValueError:
        confidence = 0.8

    title = content_raw[:60].strip()
    args.title     = [title]
    args.content   = content_raw
    args.kind      = kind
    args.scope     = scope
    args.confidence = confidence
    args.tags      = []
    args.emotional_weight = 0.5
    print()
    return args


def cmd_add(args):
    """手動加入一筆知識"""
    # PH2-03: 無參數時進入互動模式
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
    # STB-04: 若最終 scope 為 global，提示使用者
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
            logger.warning("emotional_weight update failed: %s", _e)
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
            logger.warning("near_duplicate event check failed: %s", _e)
        first_word = title.split()[0] if title.split() else title
        _info(f"查詢：{GR}brain ask \"{first_word}\"{R}")


def cmd_review(args):
    """審查 KRB Staging 中待核准的知識（brain review list / approve / reject）"""
    wd  = _workdir(args)
    sub = getattr(args, 'review_sub', None)
    bd  = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db    import BrainDB
    from project_brain.graph       import KnowledgeGraph
    from project_brain.review_board import KnowledgeReviewBoard
    graph = KnowledgeGraph(bd)
    krb   = KnowledgeReviewBoard(bd, graph)

    if sub == 'list' or sub is None:
        limit      = getattr(args, 'limit', 20)
        ai_pending = getattr(args, 'pending_ai', False)
        show_pend  = getattr(args, 'pending', False)

        if show_pend:
            # --pending: show human-review queue
            nodes = krb.list_pending(limit=limit)
            if ai_pending:
                nodes = [n for n in nodes if n.ai_recommendation == "review"]
            if not nodes:
                _info("KRB Staging 目前沒有待人工審查的知識 (KRB-01 自主模式已啟用)")
                return
            label = "待人工審查（AI 標記）" if ai_pending else f"待審知識 ({len(nodes)} 筆)"
            print(f"\n{B}{C}  KRB Staging — {label}{R}")
            print(f"{D}{'─'*68}{R}")
            for node in nodes:
                print(f"  {node.summary_line()}")
            print(f"\n{D}  brain review approve <id>          核准進入 L3{R}")
            print(f"{D}  brain review reject  <id>          拒絕並記錄原因{R}")
            print(f"{D}  brain review pre-screen            AI 預篩所有 pending 節點{R}\n")
        else:
            # default: show audit log (KRB-01 autonomous mode)
            nodes = krb.list_audit_log(limit=limit)
            stats = krb.stats()
            print(f"\n{B}{C}  KRB 審計記錄 — 最近 {len(nodes)} 筆{R}  "
                  f"{D}(pending={stats['pending']} approved={stats['approved']} "
                  f"rejected={stats['rejected']}){R}")
            print(f"{D}{'─'*68}{R}")
            if not nodes:
                _info("尚無審核記錄。執行 brain scan 或 brain sync 後自動填入。")
            for node in nodes:
                print(f"  {node.summary_line()}")
            print(f"\n{D}  brain review list --pending        查看待人工審查項目{R}")
            print(f"{D}  brain review pre-screen            AI 批次預篩{R}\n")

    elif sub == 'pre-screen':
        import os as _os
        api_key = _os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            _err("需要 ANTHROPIC_API_KEY 環境變數才能執行 AI 預篩"); return
        try:
            import anthropic
            from project_brain.krb_ai_assist import KRBAIAssistant
        except ImportError:
            _err("請安裝 anthropic 套件：pip install anthropic"); return

        limit  = getattr(args, 'limit', 50)
        aa     = getattr(args, 'auto_approve', None)
        ar     = getattr(args, 'auto_reject',  None)
        max_ap = getattr(args, 'max_api_calls', 20)

        client = anthropic.Anthropic(api_key=api_key)
        assist = KRBAIAssistant(krb, client)

        print(f"\n{B}{C}  🤖 AI KRB 預篩{R}  {D}limit={limit}{R}")
        if aa is not None:
            print(f"  {D}auto-approve 閾值：{aa}  （≥{aa} 且非 Pitfall 自動核准）{R}")
        if ar is not None:
            print(f"  {D}auto-reject  閾值：{ar}  （≥{ar} 且建議拒絕自動執行）{R}")
        print(f"{D}{'─'*54}{R}")

        summary = assist.pre_screen(
            limit                  = limit,
            auto_approve_threshold = aa,
            auto_reject_threshold  = ar,
            max_api_calls          = max_ap,
        )

        if summary["total"] == 0:
            _info("沒有需要預篩的 pending 節點（或全部已在 24 小時快取內）")
            return

        _ok(f"預篩完成：{summary['total']} 條")
        print(f"  ✅ 快速道（approve）：{summary['approve_lane']} 條")
        print(f"  ⚠️  人工道（review）： {summary['review_lane']} 條")
        print(f"  ❌ 丟棄道（reject）： {summary['reject_lane']} 條")
        if summary['auto_approved'] or summary['auto_rejected']:
            print()
            print(f"  🤖 已自動核准：{summary['auto_approved']} 條")
            print(f"  🤖 已自動拒絕：{summary['auto_rejected']} 條")
        print(f"\n  {D}API 呼叫：{summary['api_calls_used']} 次{R}")
        print(f"\n{D}  使用 brain review list --pending-ai 查看待人工審查項目{R}\n")

    elif sub == 'approve':
        sid = getattr(args, 'id', None)
        if not sid:
            _err("請提供 staged ID：brain review approve <id>"); return
        reviewer = getattr(args, 'reviewer', 'human')
        note     = getattr(args, 'note', '')
        l3_id = krb.approve(sid, reviewer=reviewer, note=note)
        if l3_id:
            _ok(f"已核准 → L3 節點：{l3_id}")
        else:
            _err(f"找不到 staging ID：{sid}")

    elif sub == 'reject':
        sid = getattr(args, 'id', None)
        if not sid:
            _err("請提供 staged ID：brain review reject <id>"); return
        reason = getattr(args, 'reason', '')
        if not reason:
            _err("請提供拒絕原因：--reason \"...\""); return
        ok = krb.reject(sid, reviewer=getattr(args, 'reviewer', 'human'), reason=reason)
        if ok:
            _ok(f"已拒絕 {sid}：{reason}")
        else:
            _err(f"找不到 staging ID：{sid}")

    else:
        _err(f"未知子命令：{sub}，可用：list / approve / reject / pre-screen")


def cmd_ask(args):
    """FEAT-08: Natural Language Query — 自然語言查詢知識庫。"""
    import re as _re
    wd    = _workdir(args)
    query = " ".join(args.query) if isinstance(args.query, list) else (args.query or "")
    if not query:
        _err("Usage: brain ask <question>"); return

    _stop_zh = {"的","是","在","有","了","不","我","你","他","她","它","這","那",
                "和","或","也","但","如果","因為","所以","為什麼","怎麼","什麼",
                "請問","可以","需要","應該","會","都","還","就","嗎","呢"}
    _stop_en = {"the","a","an","is","are","was","were","be","been","being","have",
                "has","had","do","does","did","will","would","shall","should","may",
                "might","can","could","to","of","in","for","on","with","at","by",
                "from","as","into","through","why","how","what","when","where","who"}
    tokens   = _re.findall(r"[a-zA-Z0-9_]{2,}|[\u4e00-\u9fff]+", query)
    keywords = []
    for t in tokens:
        if _re.match(r"[\u4e00-\u9fff]", t):
            for ch in t:
                if ch not in _stop_zh:
                    keywords.append(ch)
            for i in range(len(t)-1):
                keywords.append(t[i:i+2])
        else:
            if t.lower() not in _stop_en:
                keywords.append(t.lower())
    search_q = " ".join(dict.fromkeys(keywords))[:200] or query

    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    db   = BrainDB(bd)
    hits = db.search_nodes(search_q, limit=5)

    if getattr(args, 'json', False):
        import json as _j
        print(_j.dumps(hits, ensure_ascii=False, indent=2))
        return

    print(f"\n{C}{B}🧠  Brain Ask: {query}{R}\n{GR}{'─'*50}{R}")
    if not hits:
        print(f"{Y}⚠{R}  找不到相關知識")
        print(f"   可加入：{GR}brain add \"{query[:40]}\"{R}")
        return

    for n in hits:
        kind   = n.get("type","?")
        conf   = n.get("confidence", 0.8)
        conf_c = G if conf >= 0.7 else (Y if conf >= 0.4 else RE)
        print(f"  {C}{B}[{kind}]{R}  {n['title']}")
        if n.get("content"):
            excerpt = (n["content"] or "")[:200]
            print(f"  {D}  {excerpt}{R}")
        print(f"  {conf_c}  conf={conf:.2f}{R}  {GR}id={n['id'][:16]}{R}\n")
    print(f"{GR}{'─'*50}{R}")

    try:
        from project_brain.context import ContextEngineer
        from project_brain.graph   import KnowledgeGraph
        graph = KnowledgeGraph(bd)
        ce    = ContextEngineer(graph)
        ce._brain_db = db
        chain = ce._build_causal_chain([n["id"] for n in hits[:3]], db=db)
        if chain:
            print(chain)
    except Exception as _e:
        logger.warning("causal chain build failed in cmd_ask: %s", _e)


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
            logger.warning("nudge questions generation failed: %s", _e)
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


def cmd_sync(args):
    """Learn from the latest git commit (called by git hook)."""
    import pathlib, subprocess
    wd    = _workdir(args)
    quiet = getattr(args, "quiet", False)
    bd    = pathlib.Path(wd) / ".brain"
    if not bd.exists():
        if not quiet:
            _err("Brain not initialised -- run: brain setup")
        return
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=%H|%s|%an"],
            cwd=wd, capture_output=True, text=True
        )
        if result.returncode != 0 or not result.stdout.strip():
            if not quiet:
                _info("No git history found — nothing to sync")
            return
        parts   = result.stdout.strip().split("|", 2)
        commit  = parts[0][:8]
        message = parts[1] if len(parts) > 1 else ""
        author  = parts[2] if len(parts) > 2 else ""
        msg_words = len(message.split())
        low_q     = (len(message) < 10 or msg_words < 3 or
                     message.lower().strip() in {
                         "wip","fix","update","changes","misc",
                         "temp","test","debug","hack","hotfix"
                     })
        episode_confidence = 0.2 if low_q else 0.5
        if low_q and not quiet:
            _info(f"Low-quality commit (confidence=0.2): {message[:40]}")

        from project_brain.brain_db import BrainDB
        db = BrainDB(bd)
        ep = db.add_episode(
            content=f"{message} ({author})",
            source=f"git-{commit}",
            confidence=episode_confidence
        )
        try:
            linked = db.link_episode_to_nodes(ep, f"{message} {commit}")
            if linked > 0 and not quiet:
                _info(f"L2→L3 連結 {linked} 個相關知識節點")
        except Exception as _e:
            logger.warning("link_episode_to_nodes failed in sync: %s", _e)

        try:
            from project_brain.engine import ProjectBrain
            brain = ProjectBrain(wd)
            learned = brain.learn_from_commit("HEAD")
            if learned > 0 and not quiet:
                _info(f"L3 新增 {learned} 筆知識")
        except Exception as _e:
            logger.warning("learn_from_commit failed in sync: %s", _e)

        if not quiet:
            _ok(f"Synced commit {commit}: {message[:50]}")
    except Exception as e:
        if not quiet:
            _err(f"Sync failed: {e}")


def cmd_meta_knowledge(args):
    """設定知識節點的適用條件與失效條件（Meta-Knowledge，v7.0）"""
    wd      = _workdir(args)
    node_id = args.node_id
    ac      = args.applies_when    or ""
    ic      = args.invalidated_when or ""

    if not ac and not ic:
        _err("至少提供 --applies-when 或 --invalidated-when 其中一個")
        return

    b  = _brain(wd)
    ok = b.graph.set_meta_knowledge(node_id, ac, ic)
    if ok:
        _ok(f"節點 {C}{node_id}{R} Meta-Knowledge 已更新")
        if ac: print(f"  {Y}⚠ 適用條件{R}：{ac}")
        if ic: print(f"  {RE}🚫 失效條件{R}：{ic}")
    else:
        _err(f"找不到節點：{node_id}")


def cmd_timeline(args):
    """REFACTOR-01: 已整合至 history，保留供向後相容。"""
    print(f"  {Y}⚠ brain timeline 已整合至 brain history（支援 --diff）{R}")
    print(f"  {D}  請改用：brain history <node_id> [--diff]{R}")
    wd      = _workdir(args)
    query   = " ".join(args.node_ref) if isinstance(args.node_ref, list) else (args.node_ref or "")
    if not query:
        _err("用法：brain timeline <node_id_or_title>"); return
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)

    node = db.get_node(query)
    if not node:
        hits = db.search_nodes(query, limit=1)
        node = hits[0] if hits else None
    if not node:
        _err(f"找不到節點：{query}"); return

    history = db.get_node_history(node["id"])
    print(f"\n{C}{B}📜  版本歷史：{node['title']}{R}")
    print(f"  {GR}節點 ID：{node['id']}{R}")
    print(f"  {GR}{'─'*48}{R}")
    if not history:
        _info("尚無版本歷史（update_node 後才會記錄）")
        print(f"  {D}目前版本：conf={node.get('confidence',0.8):.2f}{R}\n")
        return
    for h in history:
        print(f"  {G}v{h['version']}{R}  {GR}{h.get('snapshot_at','')[:19]}{R}"
              f"  conf={h.get('confidence') or '?'}"
              f"  {D}{h.get('change_note') or ''}{R}")
        if h.get("title"):
            print(f"       標題：{h['title'][:60]}")
    print()


def cmd_history(args):
    """FEAT-01/FEAT-03: brain history <node_id|--at date> — 版本歷史 or 時間快照"""
    wd     = _workdir(args)
    query  = getattr(args, 'node_id', '') or ''
    at_str = getattr(args, 'at', None) or ''
    bd     = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化"); return

    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)

    # FEAT-03: --at mode — show knowledge snapshot at a given date
    if at_str:
        _at_snapshot(db, at_str, workdir=wd)
        return

    if not query:
        _err("用法：brain history <node_id_or_title>  或  brain history --at <date>"); return

    node = db.get_node(query)
    if not node:
        hits = db.search_nodes(query, limit=1)
        node = hits[0] if hits else None
    if not node:
        _err(f"找不到節點：{query}"); return

    history = db.get_node_history(node["id"])
    ver = node.get("version") or "?"
    show_diff = getattr(args, 'diff', False)
    print(f"\n{C}{B}📜  版本歷史：{node['title']}{R}  {GR}(current v{ver}){R}")
    print(f"  {GR}節點 ID：{node['id']}{R}")
    print(f"  {GR}{'─'*50}{R}")
    if not history:
        _info("尚無版本歷史（更新節點後才會記錄）")
        return
    for i, h in enumerate(history):
        ctype = h.get("change_type") or "update"
        print(f"  {G}v{h['version']}{R}  {GR}{(h.get('snapshot_at') or '')[:19]}{R}"
              f"  [{ctype}]  conf={h.get('confidence') or '?'}"
              f"  {D}{h.get('change_note') or ''}{R}")
        if h.get("title"):
            print(f"       標題：{h['title'][:60]}")
        # FEAT-04: --diff 顯示相鄰版本 unified diff
        if show_diff and i + 1 < len(history):
            import difflib
            old_c = (history[i + 1].get("content") or "").splitlines()
            new_c = (h.get("content") or "").splitlines()
            diff  = list(difflib.unified_diff(
                old_c, new_c,
                fromfile=f"v{history[i+1]['version']}",
                tofile=f"v{h['version']}",
                lineterm="",
            ))
            if diff:
                print(f"  {D}{'·'*46}{R}")
                for line in diff[:40]:
                    color = G if line.startswith("+") else (RE if line.startswith("-") else D)
                    print(f"  {color}{line}{R}")
                if len(diff) > 40:
                    print(f"  {D}  … 省略 {len(diff)-40} 行{R}")
                print(f"  {D}{'·'*46}{R}")
    print()


def _at_snapshot(db, at_str: str, workdir: str = "") -> None:
    """FEAT-03: Print a temporal snapshot — which nodes were valid at `at_str`."""
    import re as _re, subprocess as _sp

    # Try to resolve branch/tag name via git
    resolved = at_str.strip()
    if not _re.match(r'^\d{4}-\d{2}-\d{2}', resolved):
        if _re.match(r'^[a-zA-Z0-9._\-/]+$', resolved):
            try:
                r = _sp.run(
                    ["git", "log", "-1", "--pretty=%aI", resolved],
                    capture_output=True, text=True, cwd=workdir or ".", timeout=5,
                )
                if r.returncode == 0 and r.stdout.strip():
                    resolved = r.stdout.strip()
            except Exception as _e:
                logger.warning("git log date resolution failed: %s", _e)

    nodes = db.nodes_at_time(resolved, limit=50)
    print(f"\n{B}{C}  知識快照 — {resolved[:19]}{R}  {D}({len(nodes)} 個有效節點){R}")
    print(f"{D}{'─'*68}{R}")
    if not nodes:
        _info("該時間點尚無有效知識節點（valid_from 為 NULL 的節點不計入）")
        _info("提示：git sync 後才會記錄節點的 valid_from")
        return
    kind_icons = {"Rule": "📋", "Pitfall": "⚠️ ", "Decision": "🎯", "ADR": "📐"}
    for n in nodes:
        icon = kind_icons.get(n["type"], "•")
        vf   = (n.get("valid_from") or "")[:10]
        print(f"  {icon} {n['type']:<10} conf={n['confidence']:.2f}  {vf}  {n['title'][:50]}")
    print(f"\n{D}  brain history --at <date>  查看其他時間點{R}\n")


def cmd_restore(args):
    """REFACTOR-01: 已整合至 rollback，保留供向後相容。"""
    print(f"  {Y}⚠ brain restore 已整合至 brain rollback（--version 旗標亦可用）{R}")
    print(f"  {D}  請改用：brain rollback {getattr(args,'node_id','')} --version {getattr(args,'version','N')}{R}")
    wd      = _workdir(args)
    node_id = getattr(args, 'node_id', '')
    ver     = getattr(args, 'version', None)
    if not node_id or ver is None:
        _err("用法：brain restore <node_id> --version <N>"); return
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化"); return

    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)
    ok = db.rollback_node(node_id, int(ver))
    if ok:
        _ok(f"節點 {C}{node_id[:16]}{R} 已還原到版本 v{ver}")
    else:
        _err(f"找不到節點 {node_id} 的版本 v{ver}（可用 brain history {node_id} 查詢）")


def cmd_deprecated(args):
    """ARCH-05 + REFACTOR-01: brain deprecated list/mark/purge/info"""
    sub = getattr(args, 'deprecated_sub', 'list') or 'list'
    wd  = _workdir(args)
    bd  = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化"); return

    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)

    if sub == 'list':
        limit = getattr(args, 'limit', 50) or 50
        rows  = db.get_deprecated_nodes(limit=limit)
        if not rows:
            _info("目前無已棄用節點"); return
        print(f"\n{Y}{B}🗑  已棄用節點（{len(rows)} 筆）{R}")
        print(f"  {GR}{'─'*56}{R}")
        for r in rows:
            dep_at = (r.get("deprecated_at") or "")[:16]
            title  = (r.get("title") or "")[:44]
            print(f"  {RE}{r['id'][:16]}{R}  {GR}{dep_at}{R}  {title}")
            if r.get("replaced_by"):
                print(f"    取代者：{r['replaced_by']}")
        print()

    elif sub == 'purge':
        days = getattr(args, 'older_than', 90) or 90
        n    = db.purge_deprecated_nodes(older_than_days=int(days))
        if n:
            _ok(f"已刪除 {n} 個棄用超過 {days} 天的節點")
        else:
            _info(f"沒有棄用超過 {days} 天的節點")

    elif sub == 'mark':
        # REFACTOR-01: 整合自 cmd_deprecate
        nid = getattr(args, 'node_id', None) or ''
        if not nid:
            _err("用法：brain deprecated mark <node_id> [--reason <reason>] [--replaced-by <id>]")
            return
        ok = db.deprecate_node(
            nid,
            replaced_by=getattr(args, 'replaced_by', ''),
            reason=getattr(args, 'reason', ''),
        )
        if ok:
            _ok(f"節點 {nid} 已標記為棄用")
        else:
            _err(f"找不到節點：{nid}")

    elif sub == 'info':
        # REFACTOR-01: 整合自 cmd_lifecycle
        import json as _j
        nid = getattr(args, 'node_id', None) or ''
        if not nid:
            _err("用法：brain deprecated info <node_id>"); return
        lc = db.get_lifecycle(nid)
        if not lc:
            _err("找不到節點"); return
        status_icon = "🔴 deprecated" if lc["status"] == "deprecated" else "🟢 active"
        print(f"\n  節點: {B}{lc['title']}{R}")
        print(f"  狀態: {status_icon}")
        print(f"  信心: {lc['confidence']:.2f}  建立: {(lc['created_at'] or '')[:10]}  更新: {(lc['updated_at'] or '')[:10]}")
        if lc["replaced_by"]:
            print(f"  取代節點: {', '.join(lc['replaced_by'])}")
        if lc["history"]:
            print(f"\n  歷史版本 ({len(lc['history'])} 筆):")
            for h in lc["history"][:5]:
                print(f"    v{h.get('version','?')}  {(h.get('changed_at','') or '')[:16]}  {h.get('change_note','')[:40]}")
        print()

    else:
        _err(f"未知子命令：{sub}（可用：list, mark, purge, info）")


def cmd_deprecate(args):
    """REFACTOR-01: 已整合至 deprecated mark，保留供向後相容。"""
    nid = getattr(args, 'node_id', '')
    print(f"  {Y}⚠ brain deprecate 已整合至 brain deprecated mark{R}")
    print(f"  {D}  請改用：brain deprecated mark {nid} --reason \"...\"{R}")
    wd = _workdir(args)
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化"); return
    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)
    nid = getattr(args, 'node_id', '')
    ok  = db.deprecate_node(
        nid,
        replaced_by=getattr(args, 'replaced_by', ''),
        reason=getattr(args, 'reason', ''),
    )
    if ok:
        _ok(f"節點 {nid} 已標記為棄用")
    else:
        _err(f"找不到節點：{nid}")


def cmd_lifecycle(args):
    """REFACTOR-01: 已整合至 deprecated info，保留供向後相容。"""
    nid = getattr(args, 'node_id', '')
    print(f"  {Y}⚠ brain lifecycle 已整合至 brain deprecated info{R}")
    print(f"  {D}  請改用：brain deprecated info {nid}{R}")
    import json as _j
    wd = _workdir(args)
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化"); return
    from project_brain.brain_db import BrainDB
    db  = BrainDB(bd)
    lc  = db.get_lifecycle(getattr(args, 'node_id', ''))
    if not lc:
        _err(f"找不到節點"); return
    status_icon = "🔴 deprecated" if lc["status"] == "deprecated" else "🟢 active"
    print(f"\n  節點: {B}{lc['title']}{R}")
    print(f"  狀態: {status_icon}")
    print(f"  信心: {lc['confidence']:.2f}  建立: {(lc['created_at'] or '')[:10]}  更新: {(lc['updated_at'] or '')[:10]}")
    if lc["replaced_by"]:
        print(f"  取代節點: {', '.join(lc['replaced_by'])}")
    if lc["history"]:
        print(f"\n  歷史版本 ({len(lc['history'])} 筆):")
        for h in lc["history"][:5]:
            print(f"    v{h.get('version','?')}  {(h.get('changed_at','') or '')[:16]}  {h.get('change_note','')[:40]}")
    print()


def cmd_rollback(args):
    """FEAT-06 + REFACTOR-01: 恢復節點到指定版本（--to N 或 --version N）"""
    wd      = _workdir(args)
    node_id = args.node_id
    to_ver  = args.to  # parser 已將 --version 的 dest 設為 'to'
    if not node_id or to_ver is None:
        _err("用法：brain rollback <node_id> --to <N>  或  brain rollback <node_id> --version <N>")
        return
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    db = BrainDB(bd)
    ok = db.rollback_node(node_id, int(to_ver))
    if ok:
        _ok(f"節點 {C}{node_id[:16]}{R} 已恢復到版本 v{to_ver}")
    else:
        _err(f"找不到節點 {node_id} 的版本 v{to_ver}（可用 brain timeline {node_id} 查詢）")


def cmd_link_issue(args):
    """PH2-06: 連結 Brain 節點與 GitHub / Linear issue"""
    wd = _workdir(args)
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    import json as _j

    db      = BrainDB(bd)
    do_list = getattr(args, 'list', False)

    if do_list:
        rows = db.recent_events(event_type="issue_link", limit=50)
        if not rows:
            _info("尚未連結任何 issue。")
            _info("使用方法：brain link-issue --node-id <id> --url <issue-url>")
            return
        print(f"\n{C}{B}🔗  Linked Issues ({len(rows)} 筆){R}\n{GR}{'─'*54}{R}")
        for r in rows:
            try:
                raw = r.get("payload") or "{}"
                p = _j.loads(raw)
                if isinstance(p, str):
                    p = _j.loads(p)
            except Exception:
                p = {}
            nid   = p.get("node_id", "?")[:16]
            url   = p.get("issue_url", "?")
            title = p.get("node_title", "")
            kind  = p.get("node_kind", "")
            k_c   = {"Pitfall": RE, "Rule": C, "Decision": G}.get(kind, Y)
            print(f"  {k_c}[{kind}]{R} {B}{title[:45]}{R}")
            print(f"  {GR}id={nid}  →  {url}{R}\n")
        return

    node_id   = getattr(args, 'node_id', None)
    issue_url = getattr(args, 'url', None)

    if not node_id:
        _err("請提供 --node-id"); return
    if not issue_url:
        _err("請提供 --url（GitHub / Linear issue URL）"); return

    node = db.get_node(node_id)
    if not node:
        rows = db.conn.execute(
            "SELECT id, title, type FROM nodes WHERE id LIKE ? LIMIT 1",
            (node_id + "%",)
        ).fetchone()
        if rows:
            node = dict(rows)
            node_id = node["id"]
        else:
            _err(f"找不到節點：{node_id}"); return

    title = node.get("title", "")
    kind  = node.get("type") or node.get("kind", "Note")

    payload = _j.dumps({
        "node_id":    node_id,
        "node_title": title,
        "node_kind":  kind,
        "issue_url":  issue_url,
    }, ensure_ascii=False)
    db.emit("issue_link", payload)

    _ok(f"已連結：{C}{node_id[:16]}{R}  →  {issue_url}")
    _info(f"節點：[{kind}] {title}")
    _info("此連結將用於 brain report 的 ROI 歸因統計")


def cmd_search(args):
    """PH2-02: 純語意搜尋（brain search）"""
    wd    = _workdir(args)
    bd    = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    query = " ".join(args.query) if isinstance(args.query, list) else (args.query or "")
    if not query:
        _err("Usage: brain search <keywords>"); return

    limit  = getattr(args, 'limit', 10) or 10
    kind   = getattr(args, 'kind', None)
    scope  = getattr(args, 'scope', None)
    fmt    = getattr(args, 'format', 'text')

    from project_brain.brain_db import BrainDB
    db   = BrainDB(bd)
    hits = db.search_nodes(query, limit=limit)

    if kind:
        hits = [h for h in hits if (h.get("type") or h.get("kind","")).lower() == kind.lower()]
    if scope:
        hits = [h for h in hits if h.get("scope", "global").lower() == scope.lower()]

    if fmt == 'json':
        import json as _j
        print(_j.dumps(hits, ensure_ascii=False, indent=2))
        return

    print(f"\n{C}{B}🔍  Brain Search: {query}{R}  {GR}({len(hits)} 筆){R}\n{GR}{'─'*50}{R}")
    if not hits:
        print(f"{Y}⚠{R}  找不到相關知識")
        print(f"   可加入：{GR}brain add \"{query[:40]}\"{R}")
        return

    for n in hits:
        k      = n.get("type") or n.get("kind") or "Note"
        conf   = n.get("confidence", 0.8)
        conf_c = G if conf >= 0.7 else (Y if conf >= 0.4 else RE)
        k_c    = {"Pitfall": RE, "Decision": G, "Rule": C}.get(k, Y)
        print(f"  {k_c}{B}[{k}]{R}  {B}{n['title']}{R}")
        if n.get("content"):
            print(f"  {D}  {(n['content'] or '')[:160]}{R}")
        sc = n.get("scope", "global")
        print(f"  {conf_c}conf={conf:.2f}{R}  {GR}scope={sc}  id={n['id'][:16]}{R}\n")
    print(f"{GR}{'─'*50}{R}")


def cmd_counterfactual(args):
    """DEEP-03: 反事實推理（brain counterfactual "如果我們用 NoSQL"）"""
    wd         = _workdir(args)
    hypothesis = " ".join(args.hypothesis) if isinstance(args.hypothesis, list) else (args.hypothesis or "")
    if not hypothesis:
        _err("用法：brain counterfactual \"假設條件\""); return
    bd = Path(wd) / ".brain"
    if not bd.exists():
        _err("Brain 尚未初始化，請執行：brain setup"); return

    from project_brain.brain_db import BrainDB
    from project_brain.graph    import KnowledgeGraph
    import re as _re

    db    = BrainDB(bd)
    graph = KnowledgeGraph(bd)

    terms = _re.findall(r"[a-zA-Z0-9_]{3,}|[\u4e00-\u9fff]{2,}", hypothesis)
    search_q = " ".join(terms[:DEFAULT_SEARCH_LIMIT])
    hits = db.search_nodes(search_q, limit=DEFAULT_SEARCH_LIMIT)

    affected = []
    seen_ids = set()

    for n in hits:
        nid = n["id"]
        if nid in seen_ids:
            continue
        seen_ids.add(nid)
        affected.append(n)
        try:
            rows = graph._conn.execute(
                "SELECT n2.* FROM edges e JOIN nodes n2 ON e.target_id=n2.id "
                "WHERE e.source_id=? AND e.relation IN ('DEPENDS_ON','REQUIRES')",
                (nid,)
            ).fetchall()
            for r in rows:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    affected.append(dict(r))
        except Exception as _e:
            logger.warning("counterfactual edge query failed: %s", _e)

    print(f"\n{C}{B}🔮  反事實分析：{hypothesis}{R}\n{GR}{'─'*50}{R}")
    if not affected:
        print(f"{Y}⚠{R}  找不到相關知識節點")
        return

    print(f"\n  以下 {B}{len(affected)}{R} 個決策需要重新評估：\n")
    for n in affected:
        kind = n.get("type","?")
        conf = n.get("confidence",0.8)
        conf_c = G if conf >= 0.7 else (Y if conf >= 0.4 else RE)
        print(f"  {C}[{kind}]{R}  \"{n['title'][:60]}\"  {conf_c}conf={conf:.2f}{R}")
    print()
