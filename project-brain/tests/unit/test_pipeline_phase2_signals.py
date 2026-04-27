"""
C-04: Pipeline Phase 2 Signal Tests

Verifies:
- KNOWLEDGE_CONFLICT SignalKind exists and is valid
- All Phase 2 SignalKind values are backward-compatible strings
- Signal can be created with each new kind
- Signal-specific prompt hints are applied in _build_prompt
- SignalQueue accepts Phase 2 signals
- BrainServer.emit_signal works (mocked queue)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from project_brain.pipeline.signal import Signal, SignalKind, SignalQueue
from project_brain.brain_db import BrainDB


# ════════════════════════════════════════════════════════════════
# SignalKind definitions
# ════════════════════════════════════════════════════════════════


class TestPhase2SignalKinds:
    """All Phase 2 SignalKind values exist and are valid strings."""

    def test_mcp_tool_call_exists(self):
        assert SignalKind.MCP_TOOL_CALL.value == "mcp_tool_call"

    def test_test_failure_exists(self):
        assert SignalKind.TEST_FAILURE.value == "test_failure"

    def test_knowledge_conflict_exists(self):
        assert SignalKind.KNOWLEDGE_CONFLICT.value == "knowledge_conflict"

    def test_all_phase2_are_str_enum(self):
        for kind in (SignalKind.MCP_TOOL_CALL, SignalKind.TEST_FAILURE,
                     SignalKind.KNOWLEDGE_CONFLICT):
            assert isinstance(kind.value, str)
            assert isinstance(kind, str)  # str Enum

    def test_backward_compat_phase1_unchanged(self):
        """Phase 1 kinds still exist with same values."""
        assert SignalKind.GIT_COMMIT.value == "git_commit"
        assert SignalKind.TASK_COMPLETE.value == "task_complete"


# ════════════════════════════════════════════════════════════════
# Signal creation
# ════════════════════════════════════════════════════════════════


class TestPhase2SignalCreation:
    """Signal objects can be created with each Phase 2 kind."""

    def test_create_mcp_tool_call_signal(self):
        s = Signal(
            kind=SignalKind.MCP_TOOL_CALL,
            workdir="/test",
            summary="add_knowledge kind=Pitfall",
            raw_content="title: test\ncontent: test content",
        )
        assert s.kind == SignalKind.MCP_TOOL_CALL
        row = s.to_row()
        assert row[1] == "mcp_tool_call"

    def test_create_test_failure_signal(self):
        s = Signal(
            kind=SignalKind.TEST_FAILURE,
            workdir="/test",
            summary="test_auth_flow failed",
            raw_content="AssertionError: expected 200, got 401",
        )
        assert s.kind == SignalKind.TEST_FAILURE

    def test_create_knowledge_conflict_signal(self):
        s = Signal(
            kind=SignalKind.KNOWLEDGE_CONFLICT,
            workdir="/test",
            summary="conflict: JWT RS256 vs HS256",
            raw_content="Node A says RS256, Node B says HS256",
        )
        assert s.kind == SignalKind.KNOWLEDGE_CONFLICT

    def test_from_row_round_trip(self, tmp_path):
        """Signal → to_row → DB → from_row preserves kind."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        sq = SignalQueue(db.conn)

        s = Signal(
            kind=SignalKind.KNOWLEDGE_CONFLICT,
            workdir=str(tmp_path),
            summary="test conflict",
            raw_content="content",
        )
        sq.enqueue(s)
        batch = sq.dequeue_batch(1)
        assert len(batch) == 1
        assert batch[0].kind == SignalKind.KNOWLEDGE_CONFLICT
        db.close()


# ════════════════════════════════════════════════════════════════
# Signal-specific prompt hints
# ════════════════════════════════════════════════════════════════


class TestPromptHints:
    """_build_prompt includes signal-specific hints for Phase 2 kinds."""

    def _build(self, kind_str: str) -> str:
        from project_brain.pipeline.llm_judgment import LLMJudgmentEngine
        engine = LLMJudgmentEngine(client=MagicMock(), model="test")
        signal = Signal(
            kind=SignalKind(kind_str),
            workdir="/test",
            summary="test summary",
            raw_content="test content",
        )
        return engine._build_prompt(signal, [])

    def test_mcp_tool_call_hint_present(self):
        prompt = self._build("mcp_tool_call")
        assert "MCP_TOOL_CALL" in prompt
        assert "USAGE PATTERNS" in prompt

    def test_test_failure_hint_present(self):
        prompt = self._build("test_failure")
        assert "TEST_FAILURE" in prompt
        assert "ROOT CAUSE" in prompt

    def test_knowledge_conflict_hint_present(self):
        prompt = self._build("knowledge_conflict")
        assert "KNOWLEDGE_CONFLICT" in prompt
        assert "contradict" in prompt

    def test_git_commit_no_extra_hint(self):
        """Phase 1 kinds should have no extra hint section."""
        prompt = self._build("git_commit")
        assert "Signal-specific guidance" not in prompt

    def test_prompt_always_has_json_schema(self):
        """All prompts include the JSON output schema."""
        for kind_str in ("mcp_tool_call", "test_failure", "knowledge_conflict"):
            prompt = self._build(kind_str)
            assert '"action"' in prompt
            assert '"add" | "skip"' in prompt


# ════════════════════════════════════════════════════════════════
# SignalQueue acceptance
# ════════════════════════════════════════════════════════════════


class TestSignalQueueAcceptance:
    """SignalQueue correctly stores and retrieves Phase 2 signals."""

    def test_enqueue_mcp_tool_call(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        sq = SignalQueue(db.conn)
        s = Signal(
            kind=SignalKind.MCP_TOOL_CALL,
            workdir=str(tmp_path),
            summary="add_knowledge test",
            raw_content="test",
        )
        assert sq.enqueue(s) is True
        assert sq.pending_count() == 1
        db.close()

    def test_enqueue_knowledge_conflict(self, tmp_path):
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        sq = SignalQueue(db.conn)
        s = Signal(
            kind=SignalKind.KNOWLEDGE_CONFLICT,
            workdir=str(tmp_path),
            summary="conflict test",
            raw_content="test",
        )
        assert sq.enqueue(s) is True
        db.close()

    def test_dedup_same_kind_summary(self, tmp_path):
        """Same kind+workdir+summary should be deduped."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        sq = SignalQueue(db.conn)
        for _ in range(3):
            sq.enqueue(Signal(
                kind=SignalKind.TEST_FAILURE,
                workdir=str(tmp_path),
                summary="same failure",
                raw_content="content",
            ))
        assert sq.pending_count() == 1
        db.close()


# ════════════════════════════════════════════════════════════════
# BrainServer.emit_signal
# ════════════════════════════════════════════════════════════════


class TestBrainServerEmitSignal:
    """BrainServer.emit_signal enqueues to signal_queue."""

    def test_emit_signal_enqueues(self, tmp_path):
        (tmp_path / ".brain").mkdir()
        BrainDB(tmp_path / ".brain")  # init DB
        from project_brain.interfaces.mcp_server import BrainServer
        srv = BrainServer(str(tmp_path))
        srv.emit_signal(
            "mcp_tool_call", str(tmp_path),
            "test emission", raw_content="test",
        )
        # Verify signal landed in queue
        count = srv.brain.db.conn.execute(
            "SELECT COUNT(*) FROM signal_queue WHERE kind='mcp_tool_call'"
        ).fetchone()[0]
        assert count >= 1

    def test_emit_signal_invalid_kind_no_crash(self, tmp_path):
        """Invalid kind should not crash (logged as debug)."""
        (tmp_path / ".brain").mkdir()
        BrainDB(tmp_path / ".brain")
        from project_brain.interfaces.mcp_server import BrainServer
        srv = BrainServer(str(tmp_path))
        srv.emit_signal(
            "nonexistent_kind", str(tmp_path),
            "should not crash",
        )
        # No exception raised — just silently failed

    def test_emit_signal_priority(self, tmp_path):
        (tmp_path / ".brain").mkdir()
        BrainDB(tmp_path / ".brain")
        from project_brain.interfaces.mcp_server import BrainServer
        srv = BrainServer(str(tmp_path))
        srv.emit_signal(
            "test_failure", str(tmp_path),
            "high priority test", priority=2,
        )
        row = srv.brain.db.conn.execute(
            "SELECT priority FROM signal_queue WHERE kind='test_failure'"
        ).fetchone()
        assert row is not None
        assert row[0] == 2
