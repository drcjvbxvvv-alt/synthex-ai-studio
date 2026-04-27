"""project_brain/health.py — B-03 brain health diagnostic engine.

Pure data-collection logic. Returns structured dicts so both CLI
(``cmd_health``) and MCP (``brain_status``) can consume the results
without duplicating query code.

Every check is independently try/except-guarded so one failure never
prevents the remaining checks from running.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Check result levels ────────────────────────────────────────
OK   = "ok"
WARN = "warn"
ERROR = "error"


def _check(level: str, label: str, message: str, detail: str = "") -> dict:
    """Build one check-result dict."""
    d: dict[str, Any] = {"level": level, "label": label, "message": message}
    if detail:
        d["detail"] = detail
    return d


class HealthChecker:
    """Run all health checks against a ``.brain/`` directory.

    Usage::

        hc = HealthChecker(brain_dir)
        report = hc.run()        # {"version": ..., "checks": [...], "summary": {...}}
        json.dumps(report)       # safe for --json output
    """

    def __init__(self, brain_dir: Path) -> None:
        self.brain_dir = brain_dir

    # ── Public API ─────────────────────────────────────────────

    def run(self) -> dict:
        """Execute all checks and return a structured report."""
        checks: list[dict] = []

        checks.extend(self._check_db_access())
        checks.extend(self._check_kg_braindb_sync())
        checks.extend(self._check_krb_staging())
        checks.extend(self._check_schema_version())
        checks.extend(self._check_signal_queue())
        checks.extend(self._check_benchmark_age())

        ok_n   = sum(1 for c in checks if c["level"] == OK)
        warn_n = sum(1 for c in checks if c["level"] == WARN)
        err_n  = sum(1 for c in checks if c["level"] == ERROR)

        if err_n:
            overall = ERROR
        elif warn_n:
            overall = WARN
        else:
            overall = OK

        try:
            from project_brain import __version__
            version = __version__
        except Exception:
            version = "unknown"

        return {
            "version": version,
            "brain_dir": str(self.brain_dir),
            "checks": checks,
            "summary": {
                "overall": overall,
                "ok": ok_n,
                "warn": warn_n,
                "error": err_n,
            },
        }

    # ── Individual checks ──────────────────────────────────────

    def _check_db_access(self) -> list[dict]:
        """Check brain.db accessibility + node/edge counts (C-01: unified DB)."""
        results: list[dict] = []

        db_path = self.brain_dir / "brain.db"
        if not db_path.exists():
            results.append(_check(ERROR, "brain.db", "not found",
                                  "Run: brain init"))
            return results

        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = 0
            try:
                edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            except Exception:
                pass
            fts = 0
            try:
                fts = conn.execute("SELECT COUNT(*) FROM nodes_fts").fetchone()[0]
            except Exception:
                pass
            conn.close()
            results.append(_check(
                OK, "brain.db",
                f"accessible ({nodes} nodes, {edges} edges, {fts} FTS5 indexed) — single DB mode"
            ))
        except Exception as e:
            results.append(_check(ERROR, "brain.db", f"read failed: {e}"))

        # C-01: check if legacy knowledge_graph.db still exists (migration pending)
        kg_path = self.brain_dir / "knowledge_graph.db"
        if kg_path.exists():
            results.append(_check(WARN, "knowledge_graph.db",
                                  "legacy file still exists — migration may be pending",
                                  "Will auto-migrate on next brain startup"))
        kg_bak = self.brain_dir / "knowledge_graph.db.bak"
        if kg_bak.exists():
            results.append(_check(OK, "KG migration",
                                  "knowledge_graph.db.bak present (migration completed)"))

        return results

    def _check_kg_braindb_sync(self) -> list[dict]:
        """C-01: No longer relevant — single unified DB. Kept as no-op for compat."""
        return []

    def _check_krb_staging(self) -> list[dict]:
        """Check KRB staging: pending count + stale detection."""
        krb_path = self.brain_dir / "review_board.db"
        if not krb_path.exists():
            return [_check(OK, "KRB staging", "no review_board.db (KRB not initialized)")]

        try:
            conn = sqlite3.connect(str(krb_path))
            conn.row_factory = sqlite3.Row

            pending = conn.execute(
                "SELECT COUNT(*) FROM staged_nodes WHERE status='pending'"
            ).fetchone()[0]

            # Find oldest pending
            oldest_row = conn.execute(
                "SELECT created_at FROM staged_nodes WHERE status='pending' "
                "ORDER BY created_at ASC LIMIT 1"
            ).fetchone()

            now = datetime.now(timezone.utc)
            oldest_age_days = 0
            if oldest_row and oldest_row["created_at"]:
                try:
                    created = datetime.fromisoformat(
                        oldest_row["created_at"].replace("Z", "+00:00")
                    )
                    if created.tzinfo is None:
                        created = created.replace(tzinfo=timezone.utc)
                    oldest_age_days = (now - created).days
                except Exception:
                    pass

            # Stale = pending older than 30 days
            stale_cutoff = (now - timedelta(days=30)).isoformat()
            stale = conn.execute(
                "SELECT COUNT(*) FROM staged_nodes "
                "WHERE status='pending' AND created_at < ?",
                (stale_cutoff,)
            ).fetchone()[0]

            conn.close()

            if stale > 0:
                return [_check(WARN, "KRB staging",
                               f"{pending} pending ({stale} stale, oldest: {oldest_age_days}d)",
                               "Run: brain review list; stale items will be auto-cleaned by daemon")]
            elif pending > 0:
                return [_check(OK, "KRB staging",
                               f"{pending} pending (oldest: {oldest_age_days}d)")]
            else:
                return [_check(OK, "KRB staging", "0 pending")]
        except Exception as e:
            return [_check(ERROR, "KRB staging", f"check failed: {e}")]

    def _check_schema_version(self) -> list[dict]:
        """Check if schema is up to date."""
        db_path = self.brain_dir / "brain.db"
        if not db_path.exists():
            return []  # already reported by _check_db_access

        try:
            from project_brain.core.brain_db import SCHEMA_VERSION
            conn = sqlite3.connect(str(db_path))
            row = conn.execute(
                "SELECT value FROM brain_meta WHERE key='schema_version'"
            ).fetchone()
            conn.close()

            if row is None:
                return [_check(WARN, "schema", "schema_version not found in brain_meta")]

            current = int(row[0])
            if current >= SCHEMA_VERSION:
                return [_check(OK, "schema", f"v{current} (latest: v{SCHEMA_VERSION})")]
            else:
                return [_check(WARN, "schema",
                               f"v{current} behind latest v{SCHEMA_VERSION}",
                               "Schema will auto-migrate on next brain startup")]
        except Exception as e:
            return [_check(ERROR, "schema", f"check failed: {e}")]

    def _check_signal_queue(self) -> list[dict]:
        """Check signal_queue pending count."""
        db_path = self.brain_dir / "brain.db"
        if not db_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(db_path))
            # signal_queue may not exist yet (schema < v23)
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            if "signal_queue" not in tables:
                conn.close()
                return [_check(OK, "signal queue", "table not created yet (pre-v23 schema)")]

            pending = conn.execute(
                "SELECT COUNT(*) FROM signal_queue WHERE status='pending'"
            ).fetchone()[0]
            failed = conn.execute(
                "SELECT COUNT(*) FROM signal_queue WHERE status='failed'"
            ).fetchone()[0]
            conn.close()

            if failed > 0:
                return [_check(WARN, "signal queue",
                               f"{pending} pending, {failed} failed",
                               "Failed signals may need manual retry")]
            return [_check(OK, "signal queue", f"{pending} pending")]
        except Exception as e:
            return [_check(ERROR, "signal queue", f"check failed: {e}")]

    def _check_benchmark_age(self) -> list[dict]:
        """Check if baseline.json is recent."""
        baseline = self.brain_dir / "baseline.json"
        if not baseline.exists():
            return [_check(OK, "benchmark", "no baseline.json (benchmarks not configured)")]

        try:
            mtime = datetime.fromtimestamp(baseline.stat().st_mtime, tz=timezone.utc)
            age_days = (datetime.now(timezone.utc) - mtime).days
            if age_days > 14:
                return [_check(WARN, "benchmark",
                               f"baseline.json last updated {age_days}d ago",
                               "Recommend: re-run update_baseline.py")]
            return [_check(OK, "benchmark", f"baseline.json updated {age_days}d ago")]
        except Exception as e:
            return [_check(ERROR, "benchmark", f"check failed: {e}")]
