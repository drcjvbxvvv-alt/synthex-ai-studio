"""
B-05: BrainServer 實例隔離測試

驗證 create_server() 回傳的 MCP server 各自持有獨立的可變狀態：
  - Rate limiter（_call_times / _rate_lock）
  - Session node tracking（_session_nodes / _snodes_lock）
  - Session dedup（_session_served / _sserved_lock）
  - Daemon flags（cleanup / decay / pipeline）
  - Brain cache（_brain_cache / _cache_lock）

同時驗證 BrainServer 公開 API 與原有 module-level 函式行為一致。
"""

from __future__ import annotations

import threading
import time

import pytest

from project_brain.engine import ProjectBrain


def _make_brain_dir(tmp_path):
    """建立最小可用的 .brain/ 目錄。"""
    brain_dir = tmp_path / ".brain"
    brain_dir.mkdir(exist_ok=True)
    ProjectBrain(str(tmp_path))
    return tmp_path


# ═══════════════════════════════════════════════════════════════════
# BrainServer 建構測試
# ═══════════════════════════════════════════════════════════════════


class TestBrainServerConstruction:
    """BrainServer 基本建構與屬性初始化。"""

    def test_brain_server_importable(self):
        """BrainServer class 可正常 import。"""
        from project_brain.interfaces.mcp_server import BrainServer
        assert BrainServer is not None

    def test_brain_server_has_instance_state(self, tmp_path):
        """BrainServer 實例應有所有必要的 instance 屬性。"""
        from project_brain.interfaces.mcp_server import BrainServer
        wd = _make_brain_dir(tmp_path)
        srv = BrainServer(str(wd))

        # Rate limiter
        assert isinstance(srv._call_times, list)
        assert isinstance(srv._rate_lock, type(threading.Lock()))

        # Session tracking
        assert isinstance(srv._session_nodes, dict)
        assert isinstance(srv._snodes_lock, type(threading.Lock()))

        # Session dedup
        assert isinstance(srv._session_served, dict)
        assert isinstance(srv._session_served_ts, dict)
        assert isinstance(srv._sserved_lock, type(threading.Lock()))

        # Brain cache
        assert isinstance(srv._brain_cache, dict)
        assert isinstance(srv._cache_lock, type(threading.Lock()))

        # Daemon flags
        assert isinstance(srv._cleanup_daemon_started, bool)
        assert isinstance(srv._decay_daemon_started, bool)
        assert isinstance(srv._pipeline_worker_started, bool)

        # Brain instance
        assert srv.brain is not None

    def test_brain_server_brain_cached(self, tmp_path):
        """BrainServer 初始化後，primary brain 在 cache 中。"""
        from project_brain.interfaces.mcp_server import BrainServer
        wd = _make_brain_dir(tmp_path)
        srv = BrainServer(str(wd))
        assert str(wd.resolve()) in srv._brain_cache or str(wd) in srv._brain_cache


# ═══════════════════════════════════════════════════════════════════
# 狀態隔離測試
# ═══════════════════════════════════════════════════════════════════


class TestRateLimiterIsolation:
    """兩個 BrainServer 實例的 rate limiter 互不干擾。"""

    def test_rate_state_independent(self, tmp_path):
        """srv_a 的 rate 狀態不影響 srv_b。"""
        from project_brain.interfaces.mcp_server import BrainServer

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        _make_brain_dir(dir_a)

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        _make_brain_dir(dir_b)

        srv_a = BrainServer(str(dir_a))
        srv_b = BrainServer(str(dir_b))

        # Fill srv_a's rate limiter
        now = time.monotonic()
        for _ in range(10):
            srv_a._call_times.append(now)

        # srv_b should be unaffected
        assert len(srv_b._call_times) == 0
        srv_b.rate_check()  # should not raise
        assert len(srv_b._call_times) == 1

    def test_rate_check_enforces_limit(self, tmp_path):
        """rate_check 在超過 RPM 時拋出 RuntimeError。"""
        from project_brain.interfaces.mcp_server import BrainServer, RATE_LIMIT_RPM

        wd = _make_brain_dir(tmp_path)
        srv = BrainServer(str(wd))

        now = time.monotonic()
        for _ in range(RATE_LIMIT_RPM):
            srv._call_times.append(now)

        with pytest.raises(RuntimeError, match="Rate limit"):
            srv.rate_check()

    def test_rate_check_expires_old_timestamps(self, tmp_path):
        """超過 60 秒的舊 timestamp 應被清除。"""
        from project_brain.interfaces.mcp_server import BrainServer, RATE_LIMIT_RPM

        wd = _make_brain_dir(tmp_path)
        srv = BrainServer(str(wd))

        old_time = time.monotonic() - 120
        for _ in range(RATE_LIMIT_RPM):
            srv._call_times.append(old_time)

        srv.rate_check()  # should pass — old entries expired
        assert len(srv._call_times) == 1


class TestSessionIsolation:
    """兩個 BrainServer 實例的 session 狀態互不干擾。"""

    def test_session_nodes_independent(self, tmp_path):
        """srv_a 的 _session_nodes 不出現在 srv_b 中。"""
        from project_brain.interfaces.mcp_server import BrainServer

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        _make_brain_dir(dir_a)

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        _make_brain_dir(dir_b)

        srv_a = BrainServer(str(dir_a))
        srv_b = BrainServer(str(dir_b))

        srv_a._session_nodes["test_wk"] = ["node1", "node2"]
        assert "test_wk" not in srv_b._session_nodes

    def test_session_served_independent(self, tmp_path):
        """srv_a 的 _session_served 不影響 srv_b。"""
        from project_brain.interfaces.mcp_server import BrainServer

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        _make_brain_dir(dir_a)

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        _make_brain_dir(dir_b)

        srv_a = BrainServer(str(dir_a))
        srv_b = BrainServer(str(dir_b))

        srv_a._session_served["wk"] = {"n1"}
        srv_a._session_served_ts["wk"] = time.monotonic()

        assert "wk" not in srv_b._session_served

    def test_cleanup_expired_sessions_instance_scoped(self, tmp_path):
        """cleanup_expired_sessions 只清理自己實例的 session。"""
        from project_brain.interfaces.mcp_server import BrainServer, _SESSION_TTL_SECS

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        _make_brain_dir(dir_a)

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        _make_brain_dir(dir_b)

        srv_a = BrainServer(str(dir_a))
        srv_b = BrainServer(str(dir_b))

        now = time.monotonic()
        # Add expired session to srv_a
        srv_a._session_served["expired"] = {"node1"}
        srv_a._session_served_ts["expired"] = now - _SESSION_TTL_SECS - 10
        # Add fresh session to srv_b
        srv_b._session_served["fresh"] = {"node2"}
        srv_b._session_served_ts["fresh"] = now

        srv_a.cleanup_expired_sessions()

        # srv_a cleaned up
        assert "expired" not in srv_a._session_served
        # srv_b untouched
        assert "fresh" in srv_b._session_served


class TestDaemonFlagIsolation:
    """每個 BrainServer 有獨立的 daemon started flag。"""

    def test_daemon_flags_independent(self, tmp_path):
        """srv_a 的 daemon 啟動不影響 srv_b 的 flag。"""
        from project_brain.interfaces.mcp_server import BrainServer

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        _make_brain_dir(dir_a)

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        _make_brain_dir(dir_b)

        srv_a = BrainServer(str(dir_a))
        srv_b = BrainServer(str(dir_b))

        # Manually set flags on srv_a
        srv_a._cleanup_daemon_started = True
        srv_a._decay_daemon_started = True
        srv_a._pipeline_worker_started = True

        # srv_b should still have defaults
        assert srv_b._cleanup_daemon_started is False
        assert srv_b._decay_daemon_started is False
        assert srv_b._pipeline_worker_started is False


class TestBrainCacheIsolation:
    """兩個 BrainServer 實例的 brain cache 互不干擾。"""

    def test_brain_cache_independent(self, tmp_path):
        """srv_a 的 _brain_cache 與 srv_b 不共享。"""
        from project_brain.interfaces.mcp_server import BrainServer

        dir_a = tmp_path / "a"
        dir_a.mkdir()
        _make_brain_dir(dir_a)

        dir_b = tmp_path / "b"
        dir_b.mkdir()
        _make_brain_dir(dir_b)

        srv_a = BrainServer(str(dir_a))
        srv_b = BrainServer(str(dir_b))

        assert len(srv_a._brain_cache) == 1  # only primary
        assert len(srv_b._brain_cache) == 1  # only primary

        # Keys should be different
        a_keys = set(srv_a._brain_cache.keys())
        b_keys = set(srv_b._brain_cache.keys())
        assert a_keys != b_keys


# ═══════════════════════════════════════════════════════════════════
# 公開 API 相容性
# ═══════════════════════════════════════════════════════════════════


class TestCreateServerCompat:
    """create_server() 工廠函式的 backward compatibility。"""

    def test_create_server_returns_mcp_object(self, tmp_path):
        """create_server() 回傳可用的 MCP server 物件。"""
        from project_brain.interfaces.mcp_server import create_server
        wd = _make_brain_dir(tmp_path)
        mcp = create_server(str(wd))
        assert mcp is not None
        # FastMCP has a 'name' attribute
        assert hasattr(mcp, 'name') or hasattr(mcp, 'run')

    def test_module_level_compat_variables_exist(self):
        """模組層級的 backward-compat 變數仍然存在。"""
        import project_brain.mcp_server as ms
        assert hasattr(ms, '_call_times')
        assert hasattr(ms, '_rate_lock')
        assert hasattr(ms, '_session_nodes')
        assert hasattr(ms, '_snodes_lock')
        assert hasattr(ms, '_session_served')
        assert hasattr(ms, '_sserved_lock')
        assert hasattr(ms, '_cleanup_daemon_started')
        assert hasattr(ms, '_decay_daemon_started')
        assert hasattr(ms, '_pipeline_worker_started')
        assert hasattr(ms, '_brain_cache')
        assert hasattr(ms, '_cache_lock')

    def test_module_level_functions_exist(self):
        """模組層級的 backward-compat 函式仍然存在。"""
        import project_brain.mcp_server as ms
        assert callable(getattr(ms, '_rate_check', None))
        assert callable(getattr(ms, '_cleanup_expired_sessions', None))
        assert callable(getattr(ms, '_safe_str', None))
        assert callable(getattr(ms, '_validate_workdir', None))
        assert callable(getattr(ms, '_find_brain_root', None))
        assert callable(getattr(ms, '_run_maintenance_cycle', None))

    def test_brain_server_class_exported(self):
        """BrainServer class 可從模組 import。"""
        import project_brain.mcp_server as ms
        assert hasattr(ms, 'BrainServer')


# ═══════════════════════════════════════════════════════════════════
# 並發安全
# ═══════════════════════════════════════════════════════════════════


class TestConcurrentRateCheck:
    """BrainServer.rate_check 在並發下正確序列化。"""

    def test_concurrent_rate_check_does_not_exceed_limit(self, tmp_path):
        """多 threads 並發呼叫 rate_check，成功數不超過 RPM。"""
        from project_brain.interfaces.mcp_server import BrainServer, RATE_LIMIT_RPM

        wd = _make_brain_dir(tmp_path)
        srv = BrainServer(str(wd))

        successes = []
        errors = []

        def _try():
            try:
                srv.rate_check()
                successes.append(1)
            except RuntimeError:
                errors.append(1)

        threads = [threading.Thread(target=_try) for _ in range(RATE_LIMIT_RPM + 10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) <= RATE_LIMIT_RPM
        assert len(errors) >= 10


class TestResolveBrain:
    """BrainServer.resolve_brain 使用實例 cache。"""

    def test_resolve_empty_returns_primary(self, tmp_path):
        """空 workdir 回傳 primary brain。"""
        from project_brain.interfaces.mcp_server import BrainServer
        wd = _make_brain_dir(tmp_path)
        srv = BrainServer(str(wd))
        b = srv.resolve_brain("")
        assert b is srv.brain

    def test_resolve_same_dir_returns_primary(self, tmp_path):
        """相同 workdir 回傳 primary brain。"""
        from project_brain.interfaces.mcp_server import BrainServer
        wd = _make_brain_dir(tmp_path)
        srv = BrainServer(str(wd))
        b = srv.resolve_brain(str(wd))
        assert b is srv.brain
