"""
Federation tools: federation_sync, multi_brain_query, push_to_central.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def register(mcp: Any, srv: Any, helpers: dict) -> None:
    """Register federation/multi-brain MCP tools."""

    _safe_str = helpers["_safe_str"]
    _check_permission = helpers["_check_permission"]
    _find_brain_root = helpers["_find_brain_root"]
    _FORBIDDEN_ROOTS = helpers["_FORBIDDEN_ROOTS"]
    _MAX_BRAIN_CACHE = helpers["_MAX_BRAIN_CACHE"]
    work_path = helpers["work_path"]

    MAX_QUERY_LEN = helpers["MAX_QUERY_LEN"]

    # ── Tool: push_to_central ──────────────────────────────────────

    @mcp.tool()
    def push_to_central(
        node_ids: "list[str] | None" = None,
        kind: str = "",
        min_confidence: float = 0.8,
        max_nodes: int = 50,
        target_url: str = "",
        api_key: str = "",
        workdir: str = "",
    ) -> dict:
        """
        推送本地知識到 Central Brain。

        可指定 node_ids 推送特定節點,或用 kind/min_confidence 篩選。
        推送的知識進入 Central Brain 的 KRB Staging 待審。

        Args:
            node_ids:       指定推送的節點 ID(None = 使用 kind/confidence 篩選)
            kind:           節點類型篩選(Pitfall/Rule/Decision,空 = 全部)
            min_confidence: 最低信心度(預設 0.8)
            max_nodes:      最大推送數(預設 50)
            target_url:     Central Brain URL(空 = 從 brain.toml [team] 讀取)
            api_key:        API key(空 = 從 brain.toml [team] 或 BRAIN_API_KEY 讀取)
            workdir:        專案工作目錄

        Returns:
            {"ok": True, "pushed": N, "failed": M, "errors": [...]}
        """
        perm_err = _check_permission("push_to_central")
        if perm_err:
            return perm_err
        srv.rate_check()

        wd_str = _safe_str(workdir or os.environ.get("BRAIN_WORKDIR", ""), 500, "workdir") or workdir
        b = srv.resolve_brain(wd_str)

        _url = _safe_str(target_url, 500, "target_url")
        _key = _safe_str(api_key, 500, "api_key")
        if not _url:
            try:
                from project_brain.brain_config import load_config
                _cfg = load_config(b.brain_dir)
                _url = _cfg.team.central_brain_url
                if not _key:
                    _key = _cfg.team.central_brain_key
            except Exception:
                pass
        if not _url:
            return {"ok": False, "error": "No target URL — set via argument or brain.toml [team]"}

        from project_brain.integrations.push_central import PushTransport
        from project_brain.integrations.central_brain_client import CentralBrainClient

        transport = PushTransport()
        client = CentralBrainClient(url=_url, api_key=_key)

        if node_ids:
            nodes = [b.db.get_node(nid) for nid in node_ids]
            nodes = [n for n in nodes if n is not None]
        else:
            nodes = transport.select_nodes(
                b.db, kind=kind, min_confidence=min_confidence, max_nodes=max_nodes,
            )

        sanitized = transport.sanitize_nodes(nodes)
        result = transport.push(client, sanitized, source_label="mcp:push")

        return {
            "ok": result.pushed_fail == 0,
            "pushed": result.pushed_ok,
            "failed": result.pushed_fail,
            "total_selected": result.total_selected,
            "errors": result.errors[:10],
        }

    # ── Tool: multi_brain_query ────────────────────────────────────

    @mcp.tool()
    def multi_brain_query(
        task: str,
        extra_brain_dirs: list[str] | None = None,
        top_k: int = 5,
        workdir: str = "",
    ) -> str:
        """
        Query multiple .brain/ directories simultaneously — for monorepo scenarios.

        Merges knowledge from the primary Brain plus any additional Brain instances,
        ranks all results by confidence, and labels each result with its source project.

        Configure additional brains permanently via environment variable:
          BRAIN_EXTRA_DIRS=/path/to/project-a:/path/to/project-b

        Args:
            task:             Task description for context retrieval.
            extra_brain_dirs: Additional project directories containing .brain/
                              (overrides BRAIN_EXTRA_DIRS env var when provided).
            top_k:            Max results to return per brain (default 5).
            workdir:          Primary project directory (optional).

        Returns:
            Merged context string with [source: project-name] labels per result.
            Empty string if no results found.
        """
        srv.rate_check()
        task_clean = _safe_str(task, MAX_QUERY_LEN, "task")
        top_k = max(1, min(20, int(top_k)))

        dirs_to_query: list[str] = []

        # 1. Primary brain
        primary_b = srv.resolve_brain(workdir)
        dirs_to_query.append(str(primary_b.workdir))

        # 2. Extra dirs from argument
        if extra_brain_dirs:
            for d in extra_brain_dirs[:10]:
                try:
                    d_clean = _safe_str(str(d), 500, "extra_brain_dirs[i]")
                    if not d_clean:
                        continue
                    _raw = Path(d_clean)
                    if ".." in _raw.parts:
                        logger.warning("multi_brain_query: skipping traversal path %s", d_clean)
                        continue
                    _resolved = _raw.resolve()
                    _blocked = False
                    for _fr in _FORBIDDEN_ROOTS:
                        try:
                            _resolved.relative_to(_fr)
                            logger.warning(
                                "multi_brain_query: skipping forbidden root path %s", d_clean
                            )
                            _blocked = True
                            break
                        except ValueError:
                            pass
                    if not _blocked:
                        dirs_to_query.append(d_clean)
                except Exception as _e:
                    logger.debug("extra_brain_dirs entry parse failed", exc_info=True)
        else:
            # 3. Fall back to BRAIN_EXTRA_DIRS env var
            env_extra = os.environ.get("BRAIN_EXTRA_DIRS", "")
            if env_extra:
                for d in env_extra.split(":"):
                    d = d.strip()
                    if not d or ".." in Path(d).parts:
                        continue
                    _resolved = Path(d).resolve()
                    _blocked = False
                    for _fr in _FORBIDDEN_ROOTS:
                        try:
                            _resolved.relative_to(_fr)
                            _blocked = True
                            break
                        except ValueError:
                            pass
                    if not _blocked:
                        dirs_to_query.append(d)

        # Deduplicate
        seen: set[str] = set()
        unique_dirs: list[str] = []
        for d in dirs_to_query:
            resolved = str(Path(d).resolve())
            if resolved not in seen:
                seen.add(resolved)
                unique_dirs.append(d)

        if len(unique_dirs) <= 1:
            try:
                return primary_b.get_context(task_clean) or ""
            except Exception as _e:
                logger.debug("single brain get_context failed", exc_info=True)
                return ""

        # Query each brain
        all_results: list[dict] = []
        for d in unique_dirs:
            root = _find_brain_root(d)
            if root is None:
                continue
            try:
                key = str(root)
                with srv._cache_lock:
                    if key not in srv._brain_cache:
                        if len(srv._brain_cache) >= _MAX_BRAIN_CACHE:
                            oldest_key, _ = srv._brain_cache.popitem(last=False)
                            logger.debug("SEC-04: evicted brain cache entry %s", oldest_key)
                        from project_brain.engine import ProjectBrain as _PB
                        srv._brain_cache[key] = _PB(key)
                    else:
                        srv._brain_cache.move_to_end(key)
                    b_inst = srv._brain_cache[key]
                project_name = root.name
                raw = b_inst.graph.search_nodes(task_clean, limit=top_k)
                for node in raw:
                    all_results.append({
                        "source": project_name,
                        "title": node.get("title", ""),
                        "content": (node.get("content", "") or "")[:400],
                        "kind": node.get("type", ""),
                        "confidence": float(node.get("confidence", 0.5) or 0.5),
                    })
            except Exception as _me:
                logger.debug("multi_brain_query: skipping %s — %s", d, _me)

        if not all_results:
            return ""

        all_results.sort(key=lambda x: x["confidence"], reverse=True)
        seen_titles: set[str] = set()
        deduped: list[dict] = []
        for r in all_results:
            t = r["title"].lower().strip()
            if t and t not in seen_titles:
                seen_titles.add(t)
                deduped.append(r)

        lines = [f"## 🔗 Multi-Brain Query: {task_clean!r} ({len(unique_dirs)} projects)\n"]
        for r in deduped[:top_k * len(unique_dirs)]:
            conf_str = f"conf={r['confidence']:.2f}"
            lines.append(
                f"**[{r['source']}]** [{r['kind']}] {r['title']}  ({conf_str})\n"
                f"{r['content'][:200]}\n"
            )

        return "\n".join(lines)

    # ── Tool: federation_sync ──────────────────────────────────────

    @mcp.tool()
    def federation_sync(
        dry_run: bool = False,
        min_confidence: float = 0.5,
        workdir: str = "",
    ) -> dict:
        """
        Sync knowledge from all configured federation sync_sources into KRB Staging.

        Reads sync_sources from .brain/federation.json and imports each enabled bundle
        file into the KRB Staging queue for human review before promotion to L3.

        To add a sync source permanently, use the CLI:
          brain fed sync --add-source "project-a:/path/to/federation_export.json"

        Args:
            dry_run:        Preview only — do not write to KRB Staging.
            min_confidence: Skip nodes below this confidence (default 0.5).
            workdir:        Project directory (auto-detected if omitted).

        Returns:
            {"synced": int, "skipped": int, "errors": int, "details": list}
        """
        srv.rate_check()
        try:
            _b = srv.resolve_brain(workdir)
            from project_brain.review_board import KnowledgeReviewBoard as _KRB_FED
            from project_brain.federation import FederationAutoSync
            _krb_f = _KRB_FED(_b.db, _b.graph)
            syncer = FederationAutoSync(_krb_f, _b.brain_dir)
            stats = syncer.sync_all(dry_run=dry_run, min_confidence=min_confidence)
            logger.info(
                "federation_sync: synced=%d skipped=%d errors=%d",
                stats["synced"], stats["skipped"], stats["errors"],
            )
            return stats
        except Exception as e:
            logger.error("federation_sync 內部錯誤：%s", e)
            return {"error": str(e), "synced": 0, "skipped": 0, "errors": 1, "details": []}
