"""
Project Brain MCP Server (v1.3 — H-02 refactor)

BrainServer class + create_server() factory.
Tool implementations live in mcp_tools/ sub-modules.
"""

from __future__ import annotations

import os
import re
import sys
import time
import logging
import argparse
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 安全常數 ────────────────────────────────────────────────────
MAX_QUERY_LEN    = 500
MAX_CONTENT_LEN  = 2_000
MAX_TITLE_LEN    = 200
MAX_TAGS_COUNT   = 10
RATE_LIMIT_RPM   = int(os.environ.get("BRAIN_RATE_LIMIT_RPM", "60"))
_SESSION_TTL_SECS = 1800
_CLEANUP_DAEMON_INTERVAL = 300
_DECAY_DAEMON_INTERVAL = int(os.environ.get("BRAIN_DECAY_INTERVAL", str(24 * 3600)))

# Backward-compatible module-level state (used by legacy tests)
_call_times: list[float] = []
_rate_lock = threading.Lock()
_session_nodes: dict[str, list[str]] = {}
_snodes_lock = threading.Lock()
_session_served: dict[str, set[str]] = {}
_session_served_ts: dict[str, float] = {}
_sserved_lock = threading.Lock()
_cleanup_daemon_started = False
_cleanup_daemon_lock = threading.Lock()
_decay_daemon_started = False
_decay_daemon_lock = threading.Lock()
_pipeline_worker_started = False
_pipeline_worker_lock = threading.Lock()

# Maintenance logic extracted to mcp_tools/maintenance.py
from project_brain.interfaces.mcp_tools.maintenance import (
    adjust_signal_confidence as _adjust_signal_confidence,
    run_maintenance_cycle as _run_maintenance_cycle,
)


def _cleanup_expired_sessions() -> None:
    """MEM-03: backward-compatible module-level session cleanup."""
    now = time.monotonic()
    with _sserved_lock:
        expired = [k for k, ts in _session_served_ts.items()
                   if now - ts > _SESSION_TTL_SECS]
        for k in expired:
            _session_served.pop(k, None)
            _session_served_ts.pop(k, None)


def _rate_check() -> None:
    """滑動視窗 Rate Limiting（backward-compatible module-level version）."""
    now = time.monotonic()
    cutoff = now - 60.0
    with _rate_lock:
        _call_times[:] = [t for t in _call_times if t > cutoff]
        if len(_call_times) >= RATE_LIMIT_RPM:
            raise RuntimeError(f"Rate limit：每分鐘最多 {RATE_LIMIT_RPM} 次呼叫")
        _call_times.append(now)


def _safe_str(value: Any, max_len: int, field: str) -> str:
    """安全字串清理：型別檢查 + 長度限制 + 控制字元移除"""
    if not isinstance(value, str):
        raise TypeError(f"{field} 必須是字串，得到 {type(value).__name__}")
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', value)
    if len(cleaned) > max_len:
        raise ValueError(f"{field} 超過長度限制（{len(cleaned)} > {max_len}）")
    return cleaned


_FORBIDDEN_ROOTS: tuple[Path, ...] = tuple(
    Path(p) for p in ("/etc", "/sys", "/proc", "/dev", "/boot", "/run")
    if Path(p).exists()
)


def _validate_workdir(workdir: str) -> Path:
    """驗證工作目錄：存在、無路徑遍歷、已初始化"""
    if not workdir:
        raise ValueError("BRAIN_WORKDIR 未設定")

    # SEC-02: check for traversal BEFORE resolving symlinks
    raw = Path(workdir)
    if ".." in raw.parts:
        raise ValueError("工作目錄路徑不允許包含 ..")

    # SEC-01: resolve symlinks first, then validate resolved path
    path = raw.resolve()

    if not path.exists():
        raise FileNotFoundError(f"工作目錄不存在：{path}")

    if not path.is_dir():
        raise NotADirectoryError(f"工作目錄不是目錄：{path}")

    # SEC-01: block symlink-based traversal into forbidden system directories
    for forbidden in _FORBIDDEN_ROOTS:
        try:
            path.relative_to(forbidden)
            raise ValueError(f"工作目錄不允許位於系統目錄 {forbidden} 內")
        except ValueError as _ve:
            if "系統目錄" in str(_ve):
                raise

    # 確認已初始化
    brain_dir = path / ".brain"
    if not brain_dir.exists():
        raise FileNotFoundError(
            f".brain/ 不存在，請先執行：brain init"
        )

    return path


def _find_brain_root(start: str) -> Path | None:
    """從 start 往上找第一個含有 .brain/ 的目錄，找不到回傳 None"""
    p = Path(start).resolve()
    if p.is_file():
        p = p.parent
    for candidate in [p, *p.parents]:
        if (candidate / ".brain").is_dir():
            return candidate
    return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# SEC-04: LRU cache with max size to prevent DoS via unlimited workdir creation
_MAX_BRAIN_CACHE = int(os.environ.get("BRAIN_CACHE_SIZE", "32"))
_brain_cache: "OrderedDict[str, Any]" = OrderedDict()  # LRU: oldest entry at front
_cache_lock  = threading.Lock()                         # SEC-05: protect _brain_cache concurrent writes


# ── BrainServer class (B-05) ───────────────────────────────────


class BrainServer:
    """Encapsulates all mutable MCP server state into an instance (B-05).

    Each instance owns its own rate limiter, session tracking, daemon flags,
    and brain cache — parallel create_server() calls are fully isolated.
    """

    def __init__(self, workdir: str, *, mode: str = "standalone") -> None:
        self.work_path = _validate_workdir(workdir)
        self._mode = mode  # E-02: "standalone" or "central"

        # ── Rate limiter (was module-level _call_times / _rate_lock) ──
        self._call_times: list[float] = []
        self._rate_lock = threading.Lock()

        # ── Session node tracking (VISION-01) ──
        self._session_nodes: dict[str, list[str]] = {}
        self._snodes_lock = threading.Lock()

        # ── Session dedup (MEM-03) ──
        self._session_served: dict[str, set[str]] = {}
        self._session_served_ts: dict[str, float] = {}
        self._sserved_lock = threading.Lock()

        # ── Brain instance cache (SEC-04/05) ──
        self._brain_cache: "OrderedDict[str, Any]" = OrderedDict()
        self._cache_lock = threading.Lock()

        # ── Daemon flags (one set per server instance) ──
        self._cleanup_daemon_started = False
        self._cleanup_daemon_lock = threading.Lock()
        self._decay_daemon_started = False
        self._decay_daemon_lock = threading.Lock()
        self._pipeline_worker_started = False
        self._pipeline_worker_lock = threading.Lock()

        # ── Primary brain ──
        sys.path.insert(0, str(self.work_path.parent))
        from project_brain.engine import ProjectBrain
        _serialized = (mode == "central")
        self.brain = ProjectBrain(str(self.work_path), serialized_writes=_serialized)
        # E-02: expose brain_db ref for AuthMiddleware RBAC resolution
        self._brain_db_ref = self.brain.db if _serialized else None
        self._brain_cache[str(self.work_path)] = self.brain

        # ARCH-DEBT: optional embedder warmup
        if os.environ.get("BRAIN_EMBED_WARMUP", "") == "1":
            try:
                from project_brain.embedder import warmup_embedder
                warmup_embedder()
            except Exception:
                pass

    # ── Instance methods (previously module-level helpers) ──────────

    def rate_check(self) -> None:
        """Sliding-window rate limiter (instance-scoped, thread-safe)."""
        now = time.monotonic()
        cutoff = now - 60.0
        with self._rate_lock:
            self._call_times[:] = [t for t in self._call_times if t > cutoff]
            if len(self._call_times) >= RATE_LIMIT_RPM:
                raise RuntimeError(f"Rate limit：每分鐘最多 {RATE_LIMIT_RPM} 次呼叫")
            self._call_times.append(now)

    def cleanup_expired_sessions(self) -> None:
        """MEM-03: evict sessions that exceeded TTL."""
        now = time.monotonic()
        with self._sserved_lock:
            expired = [k for k, ts in self._session_served_ts.items()
                       if now - ts > _SESSION_TTL_SECS]
            for k in expired:
                self._session_served.pop(k, None)
                self._session_served_ts.pop(k, None)

    def resolve_brain(self, caller_workdir: str) -> Any:
        """Return the Brain instance for *caller_workdir*, with LRU caching."""
        if not caller_workdir:
            return self.brain
        root = _find_brain_root(caller_workdir)
        if root is None or root == self.work_path:
            return self.brain
        key = str(root)
        with self._cache_lock:
            if key not in self._brain_cache:
                if len(self._brain_cache) >= _MAX_BRAIN_CACHE:
                    oldest_key, _ = self._brain_cache.popitem(last=False)
                    logger.debug("SEC-04: evicted brain cache entry %s", oldest_key)
                try:
                    from project_brain.engine import ProjectBrain
                    self._brain_cache[key] = ProjectBrain(key)
                except Exception as _e:
                    logger.warning("ProjectBrain init failed for %s, falling back: %s", key, _e)
                    return self.brain
            else:
                self._brain_cache.move_to_end(key)
            return self._brain_cache[key]

    # ── C-04: Signal emission helper ─────────────────────────────

    def emit_signal(self, kind: str, workdir: str, summary: str,
                    raw_content: str = "", metadata: dict | None = None,
                    priority: int = 5) -> None:
        """Non-blocking signal emission to the pipeline queue."""
        try:
            from project_brain.pipeline.signal import Signal, SignalKind
            sig = Signal(
                kind=SignalKind(kind),
                workdir=workdir,
                summary=summary[:500],
                raw_content=raw_content[:10_000],
                metadata=metadata or {},
                priority=priority,
            )
            from project_brain.pipeline.signal import SignalQueue
            sq = SignalQueue(self.brain.db.conn)
            sq.enqueue(sig)
        except Exception as _e:
            logger.debug("C-04: signal emission failed (non-fatal): %s", _e)

    # ── Daemon startup (per-instance) ──────────────────────────────

    def _start_daemons(self) -> None:
        """Start background daemons for this server instance."""
        self._start_decay_daemon()
        self._start_cleanup_daemon()
        self._start_pipeline_worker()

    def _start_decay_daemon(self) -> None:
        brain = self.brain
        with self._decay_daemon_lock:
            if self._decay_daemon_started:
                return
            def _decay_daemon_fn():
                while True:
                    time.sleep(_DECAY_DAEMON_INTERVAL)
                    _run_maintenance_cycle(brain)
            _dt = threading.Thread(
                target=_decay_daemon_fn, daemon=True, name="brain-decay",
            )
            _dt.start()
            self._decay_daemon_started = True
            logger.debug("FEAT-01: decay daemon started (interval=%ds)", _DECAY_DAEMON_INTERVAL)

    def _start_cleanup_daemon(self) -> None:
        with self._cleanup_daemon_lock:
            if self._cleanup_daemon_started:
                return
            srv = self
            def _session_cleanup_daemon():
                while True:
                    time.sleep(_CLEANUP_DAEMON_INTERVAL)
                    try:
                        srv.cleanup_expired_sessions()
                    except Exception as _e:
                        logger.debug("session cleanup daemon error: %s", _e)
            _t = threading.Thread(
                target=_session_cleanup_daemon, daemon=True,
                name="brain-session-cleanup",
            )
            _t.start()
            self._cleanup_daemon_started = True
            logger.debug("BUG-04: session cleanup daemon started (interval=%ds)",
                         _CLEANUP_DAEMON_INTERVAL)

    def _start_pipeline_worker(self) -> None:
        with self._pipeline_worker_lock:
            if self._pipeline_worker_started:
                return
            try:
                from project_brain.pipeline_worker import start_global_worker
                _pw = start_global_worker(self.brain.db, brain_dir=self.brain.brain_dir)
                if _pw is not None:
                    self._pipeline_worker_started = True
            except Exception as _e:
                logger.debug("BLOCKER-01: pipeline worker bootstrap error: %s", _e)

    # ── MCP tool registration ─────────────────────────────────────

    def create_mcp_server(self) -> Any:
        """Build and return a FastMCP server with all tools registered."""
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError:
            raise ImportError("請安裝 mcp 套件：pip install mcp")

        # Alias instance attrs for closures
        srv = self
        brain = self.brain
        work_path = self.work_path

        # E-03: central brain overlay helper
        def _get_central_client():
            """Return a CentralBrainClient if team config enables it, else None."""
            try:
                from project_brain.brain_config import load_config
                cfg = load_config(work_path / ".brain" if (work_path / ".brain").exists() else None)
                if cfg.team.mode == "local-only" or not cfg.team.central_brain_url:
                    return None, cfg.team
                from project_brain.integrations.central_brain_client import CentralBrainClient
                client = CentralBrainClient(
                    url=cfg.team.central_brain_url,
                    api_key=cfg.team.central_brain_key,
                )
                return client, cfg.team
            except Exception as e:
                logger.debug("E-03: central brain client init failed: %s", e)
                return None, None

        # E-02: permission check helper
        def _check_permission(tool_name: str) -> dict | None:
            """Return an error dict if the current role lacks permission, else None."""
            from project_brain.interfaces.http_transport import current_role
            from project_brain.rbac import has_permission, TOOL_PERMISSIONS
            role = current_role.get("admin")
            required = TOOL_PERMISSIONS.get(tool_name)
            if required and not has_permission(role, required):
                return {
                    "error": "permission_denied",
                    "message": f"Role '{role}' cannot call {tool_name} (requires {required}+)",
                }
            return None

        # Minimal FastMCP init
        try:
            mcp = FastMCP(
                name        = "project-brain",
                description = "Project Brain — 專案知識記憶系統",
            )
        except TypeError:
            try:
                mcp = FastMCP(name="project-brain")
            except TypeError:
                mcp = FastMCP("project-brain")

        # ── Register all tool modules ──────────────────────────────
        helpers = {
            "_safe_str": _safe_str,
            "_check_permission": _check_permission,
            "_get_central_client": _get_central_client,
            "_find_brain_root": _find_brain_root,
            "_now_iso": _now_iso,
            "_FORBIDDEN_ROOTS": _FORBIDDEN_ROOTS,
            "_MAX_BRAIN_CACHE": _MAX_BRAIN_CACHE,
            "work_path": work_path,
            "brain": brain,
            "MAX_QUERY_LEN": MAX_QUERY_LEN,
            "MAX_CONTENT_LEN": MAX_CONTENT_LEN,
            "MAX_TITLE_LEN": MAX_TITLE_LEN,
            "MAX_TAGS_COUNT": MAX_TAGS_COUNT,
        }

        from project_brain.interfaces.mcp_tools import register_all_tools
        register_all_tools(mcp, srv, helpers)

        # ── Start background daemons ───────────────────────────────
        self._start_daemons()

        return mcp


# ── MCP Server 公開工廠函式 ────────────────────────────────────


def create_server(workdir: str) -> Any:
    """建立並回傳 MCP Server（公開 API，無 breaking change）。

    內部建立 BrainServer 實例，所有可變狀態封裝在該實例中。
    同一程序多次呼叫 create_server() 會建立獨立的狀態空間。
    """
    srv = BrainServer(workdir)
    return srv.create_mcp_server()


def create_http_server(
    workdir: str,
    *,
    bind: str = "127.0.0.1",
    port: int = 3000,
    auth_key: str | None = None,
    rate_limit_rpm: int = 60,
    allowed_origins: list[str] | None = None,
    transport: str = "streamable-http",
    mode: str = "standalone",
) -> "HTTPBrainServer":
    """E-01: 建立支援 HTTP/SSE 的 MCP Server（供遠端 Claude Code 連接）。"""
    from project_brain.interfaces.http_transport import HTTPBrainServer
    srv = BrainServer(workdir, mode=mode)
    return HTTPBrainServer(
        brain_server=srv,
        bind=bind,
        port=port,
        auth_key=auth_key,
        rate_limit_rpm=rate_limit_rpm,
        allowed_origins=allowed_origins,
        transport=transport,
        mode=mode,
    )


def main() -> None:
    """MCP Server 主入口"""
    logging.basicConfig(
        level  = logging.WARNING,
        format = "%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(description="Project Brain MCP Server")
    parser.add_argument(
        "--workdir", "-w",
        default = os.environ.get("BRAIN_WORKDIR", os.getcwd()),
        help    = "專案工作目錄（需要有 .brain/），預設使用 BRAIN_WORKDIR 環境變數",
    )
    parser.add_argument(
        "--transport",
        default = "stdio",
        choices = ["stdio", "sse", "streamable-http"],
        help    = "傳輸方式（stdio 供本地 Claude Code，sse/streamable-http 供遠端連接）",
    )
    parser.add_argument(
        "--bind",
        default = "127.0.0.1",
        help    = "HTTP 綁定地址（預設 127.0.0.1，遠端存取用 0.0.0.0）",
    )
    parser.add_argument(
        "--port",
        type    = int,
        default = 3000,
        help    = "HTTP 監聽 port（預設 3000）",
    )
    parser.add_argument(
        "--auth-key",
        dest    = "auth_key",
        default = os.environ.get("BRAIN_API_KEY"),
        help    = "API key for HTTP auth（或設 BRAIN_API_KEY 環境變數）",
    )
    parser.add_argument(
        "--rate-limit-rpm",
        dest    = "rate_limit_rpm",
        type    = int,
        default = int(os.environ.get("BRAIN_RATE_LIMIT_RPM", "60")),
        help    = "每 IP 每分鐘最大請求數（預設 60）",
    )
    parser.add_argument(
        "--allow-origin",
        dest    = "allow_origins",
        action  = "append",
        default = None,
        help    = "CORS 允許的 origin（可多次指定）",
    )
    args = parser.parse_args()

    try:
        if args.transport in ("sse", "streamable-http"):
            http = create_http_server(
                args.workdir,
                bind=args.bind,
                port=args.port,
                auth_key=args.auth_key,
                rate_limit_rpm=args.rate_limit_rpm,
                allowed_origins=args.allow_origins,
                transport=args.transport,
            )
            logger.warning(
                "Project Brain HTTP MCP Server 啟動（workdir: %s, %s:%d）",
                args.workdir, args.bind, args.port,
            )
            http.run()
        else:
            mcp = create_server(args.workdir)
            logger.warning("Project Brain MCP Server 啟動（workdir: %s）", args.workdir)
            mcp.run(transport=args.transport)
    except FileNotFoundError as e:
        print(f"[錯誤] {e}", file=sys.stderr)
        sys.exit(1)
    except ImportError as e:
        print(f"[錯誤] 缺少依賴：{e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        logger.warning("MCP Server 已停止")


if __name__ == "__main__":
    main()
