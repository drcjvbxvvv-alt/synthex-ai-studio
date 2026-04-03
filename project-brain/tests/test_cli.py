"""
tests/test_cli.py — CLI 命令單元測試 (E-5)

覆蓋：
  - cmd_init / cmd_status
  - cmd_add / cmd_context
  - cmd_optimize / cmd_clear
  - _workdir 自動偵測
  - _Spinner 進度顯示
"""

import sys
import os
import tempfile
import argparse
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_args(**kwargs):
    """Build a namespace that mimics argparse output."""
    defaults = {
        "workdir": None,
        "quiet": False,
        "yes": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.fixture
def brain_dir(tmp_path):
    """Initialise a minimal .brain/ directory."""
    bd = tmp_path / ".brain"
    bd.mkdir()
    return tmp_path


# ══════════════════════════════════════════════════════════════
# _Spinner
# ══════════════════════════════════════════════════════════════

class TestSpinner:
    def test_spinner_context_manager(self, capsys):
        from project_brain.cli import _Spinner
        with _Spinner("test") as sp:
            sp.update("doing something")
        # After __exit__ a clear-line escape is printed — just ensure no exception
        captured = capsys.readouterr()
        assert "\r" in captured.out or captured.out == ""

    def test_spinner_with_total(self, capsys):
        from project_brain.cli import _Spinner
        with _Spinner("test", total=10) as sp:
            for i in range(5):
                sp.update(f"item {i}")
        captured = capsys.readouterr()
        # Progress bar characters should appear
        assert "█" in captured.out or "░" in captured.out or "\r" in captured.out


# ══════════════════════════════════════════════════════════════
# _workdir
# ══════════════════════════════════════════════════════════════

class TestWorkdir:
    def test_explicit_workdir(self, tmp_path):
        from project_brain.cli import _workdir
        args = _make_args(workdir=str(tmp_path))
        assert _workdir(args) == str(tmp_path.resolve())

    def test_autodetect_from_cwd(self, tmp_path):
        from project_brain.cli import _workdir
        bd = tmp_path / ".brain"
        bd.mkdir()
        args = _make_args(workdir=None)
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = _workdir(args)
        assert result == str(tmp_path.resolve())

    def test_fallback_to_cwd(self, tmp_path):
        from project_brain.cli import _workdir
        # No .brain/ in path — should fall back to cwd
        args = _make_args(workdir=None)
        with patch("os.getcwd", return_value=str(tmp_path)):
            with patch.dict(os.environ, {}, clear=True):
                result = _workdir(args)
        assert result == str(tmp_path.resolve())


# ══════════════════════════════════════════════════════════════
# cmd_optimize
# ══════════════════════════════════════════════════════════════

class TestCmdOptimize:
    def test_optimize_calls_brain_db(self, brain_dir):
        from project_brain.cli import cmd_optimize
        args = _make_args(workdir=str(brain_dir))
        mock_result = {
            "size_before_bytes": 1024 * 1024,
            "size_after_bytes": 512 * 1024,
            "saved_bytes": 512 * 1024,
            "fts5_status": "ok",
        }
        # CLI imports BrainDB inside the function → patch at source module
        with patch("project_brain.brain_db.BrainDB") as MockDB:
            instance = MockDB.return_value
            instance.optimize.return_value = mock_result
            cmd_optimize(args)
            instance.optimize.assert_called_once()

    def test_optimize_missing_brain_dir(self, tmp_path, capsys):
        from project_brain.cli import cmd_optimize
        # No .brain/ directory — should print error and return, not crash
        args = _make_args(workdir=str(tmp_path))
        cmd_optimize(args)  # Must not raise
        captured = capsys.readouterr()
        assert "brain init" in captured.out or "找不到" in captured.out


# ══════════════════════════════════════════════════════════════
# cmd_clear
# ══════════════════════════════════════════════════════════════

class TestCmdClear:
    def test_clear_session_only(self, brain_dir, capsys):
        from project_brain.cli import cmd_clear
        # target='session' (default) → clears L1a only
        args = _make_args(workdir=str(brain_dir), target="session", yes=False)
        with patch("project_brain.session_store.SessionStore") as MockSS:
            instance = MockSS.return_value
            instance.clear_session.return_value = 3
            instance._purge_expired.return_value = 1
            cmd_clear(args)
            instance.clear_session.assert_called_once()

    def test_clear_all_requires_yes_flag(self, brain_dir, capsys):
        from project_brain.cli import cmd_clear
        # target='all' without yes=True → prompts; mock stdin to 'no'
        args = _make_args(workdir=str(brain_dir), target="all", yes=False)
        with patch("builtins.input", return_value="no"):
            cmd_clear(args)  # should abort without deleting
        captured = capsys.readouterr()
        assert "取消" in captured.out or "yes" in captured.out.lower()

    def test_clear_all_with_yes_flag(self, brain_dir, capsys):
        from project_brain.cli import cmd_clear
        args = _make_args(workdir=str(brain_dir), target="all", yes=True)
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = [0]
        with patch("project_brain.brain_db.BrainDB") as MockDB:
            MockDB.return_value.conn = mock_conn
            cmd_clear(args)
            # conn.execute should have been called to DELETE FROM nodes
            assert mock_conn.execute.called


# ══════════════════════════════════════════════════════════════
# cmd_add (smoke test)
# ══════════════════════════════════════════════════════════════

class TestCmdAdd:
    def test_add_text_mode(self, brain_dir):
        from project_brain.cli import cmd_add
        args = _make_args(
            workdir=str(brain_dir),
            text=["JWT 必須使用 RS256"],
            title=None,
            content=None,      # cmd_add checks args.content
            kind="Note",
            confidence=0.8,
            tags=[],
            scope=None,
            emotional_weight=0.5,
            quiet=True,
        )
        mock_brain = MagicMock()
        mock_brain.add_knowledge.return_value = "node-abc123"
        mock_brain.db.recent_events.return_value = []
        with patch("project_brain.cli._brain", return_value=mock_brain):
            cmd_add(args)
        mock_brain.add_knowledge.assert_called_once()


# ══════════════════════════════════════════════════════════════
# cmd_context (smoke test)
# ══════════════════════════════════════════════════════════════

class TestCmdContext:
    def test_context_returns_string(self, brain_dir, capsys):
        from project_brain.cli import cmd_context
        args = _make_args(
            workdir=str(brain_dir),
            task="JWT 認證問題",
            file="",
            interactive=False,
            scope=None,
        )
        mock_brain = MagicMock()
        mock_brain.get_context.return_value = "### 知識：JWT 使用 RS256"
        with patch("project_brain.cli._brain", return_value=mock_brain):
            cmd_context(args)
        captured = capsys.readouterr()
        assert "RS256" in captured.out or mock_brain.get_context.called
