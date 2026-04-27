"""
C-03: KnowledgeValidator CI Integration Tests

Verifies:
- brain validate --ci runs without LLM (Rule + Code stages only)
- JSON output is parseable and has required fields
- to_dict() produces stable, serializable output
- CI mode with nodes produces valid report
- CI mode with rule violations sets passed=false
- _ValidatorLLMAdapter correctly wraps LLMClient
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from project_brain.brain_db import BrainDB
from project_brain.graph import KnowledgeGraph
from project_brain.engines.knowledge_validator import (
    KnowledgeValidator,
    ValidationReport,
    ValidationResult,
)


def _init_brain_with_nodes(tmp_path: Path, node_count: int = 5) -> Path:
    """Create .brain/ with BrainDB + KG and some test nodes."""
    bd = tmp_path / ".brain"
    bd.mkdir(exist_ok=True)
    db = BrainDB(bd)
    g = KnowledgeGraph(bd, conn=db.conn)
    for i in range(node_count):
        g.add_node(
            f"val-{i}", "Rule", f"Validation Rule {i}",
            content=f"This is a rule about component-{i} that should be validated.",
        )
    return bd


# ════════════════════════════════════════════════════════════════
# ValidationReport.to_dict()
# ════════════════════════════════════════════════════════════════


class TestValidationReportToDict:
    """to_dict() produces JSON-serializable dict with required fields."""

    def test_empty_report_to_dict(self):
        report = ValidationReport(
            run_id="test-001",
            total_checked=0,
            valid_count=0,
            flagged_count=0,
            invalidated_count=0,
            api_calls_used=0,
            elapsed_ms=0,
        )
        d = report.to_dict()
        assert d["run_id"] == "test-001"
        assert d["passed"] is True  # no invalidated = passed
        assert d["total_checked"] == 0
        assert d["results"] == []

    def test_to_dict_json_serializable(self):
        results = [
            ValidationResult(
                node_id="n1", title="Test", kind="Rule",
                original_conf=0.8, new_conf=0.8,
                is_valid=True, validator="rule",
                action="keep", reason="ok",
            ),
        ]
        report = ValidationReport(
            run_id="test-002",
            total_checked=1, valid_count=1, flagged_count=0,
            invalidated_count=0, api_calls_used=0, elapsed_ms=10,
            results=results,
        )
        d = report.to_dict()
        # Must be JSON-serializable
        serialized = json.dumps(d, ensure_ascii=False)
        parsed = json.loads(serialized)
        assert parsed["run_id"] == "test-002"
        assert parsed["passed"] is True
        assert len(parsed["results"]) == 1
        assert parsed["results"][0]["node_id"] == "n1"

    def test_to_dict_passed_false_when_invalidated(self):
        results = [
            ValidationResult(
                node_id="n1", title="Bad Node", kind="Rule",
                original_conf=0.8, new_conf=0.2,
                is_valid=False, validator="rule",
                action="invalidate", reason="empty content",
            ),
        ]
        report = ValidationReport(
            run_id="test-003",
            total_checked=1, valid_count=0, flagged_count=0,
            invalidated_count=1, api_calls_used=0, elapsed_ms=5,
            results=results,
        )
        d = report.to_dict()
        assert d["passed"] is False
        assert d["invalidated"] == 1

    def test_to_dict_has_all_required_keys(self):
        report = ValidationReport(
            run_id="k", total_checked=0, valid_count=0,
            flagged_count=0, invalidated_count=0,
            api_calls_used=0, elapsed_ms=0,
        )
        d = report.to_dict()
        for key in ("run_id", "passed", "total_checked", "valid",
                     "flagged", "invalidated", "api_calls_used",
                     "elapsed_ms", "results"):
            assert key in d, f"Missing key: {key}"


# ════════════════════════════════════════════════════════════════
# KnowledgeValidator CI mode (no LLM)
# ════════════════════════════════════════════════════════════════


class TestValidatorCIMode:
    """KnowledgeValidator.run(max_api_calls=0) works without LLM."""

    def test_ci_run_no_crash_empty_db(self, tmp_path):
        """Empty DB produces valid report."""
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        v = KnowledgeValidator(g, str(tmp_path), brain_dir=bd)
        report = v.run(max_api_calls=0, dry_run=True)
        assert report.total_checked == 0
        assert report.to_dict()["passed"] is True
        db.close()

    def test_ci_run_with_nodes(self, tmp_path):
        """DB with valid nodes → all pass rule validation."""
        bd = _init_brain_with_nodes(tmp_path, 5)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        v = KnowledgeValidator(g, str(tmp_path), brain_dir=bd)
        report = v.run(max_api_calls=0, dry_run=True)
        assert report.total_checked == 5
        d = report.to_dict()
        assert d["api_calls_used"] == 0
        # All results should use "rule" or "code" validator, never "claude"
        for r in d["results"]:
            assert r["validator"] in ("rule", "code")
        db.close()

    def test_ci_mode_zero_api_calls(self, tmp_path):
        """max_api_calls=0 guarantees no LLM calls."""
        bd = _init_brain_with_nodes(tmp_path, 3)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        v = KnowledgeValidator(g, str(tmp_path), client=None, brain_dir=bd)
        report = v.run(max_api_calls=0, dry_run=True)
        assert report.api_calls_used == 0
        db.close()

    def test_json_output_parseable(self, tmp_path):
        """Report JSON can be parsed by json.loads."""
        bd = _init_brain_with_nodes(tmp_path, 3)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        v = KnowledgeValidator(g, str(tmp_path), brain_dir=bd)
        report = v.run(max_api_calls=0, dry_run=True)
        json_str = json.dumps(report.to_dict(), ensure_ascii=False)
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "passed" in parsed
        db.close()

    def test_report_to_file(self, tmp_path):
        """Report can be written to file."""
        bd = _init_brain_with_nodes(tmp_path, 2)
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        v = KnowledgeValidator(g, str(tmp_path), brain_dir=bd)
        report = v.run(max_api_calls=0, dry_run=True)
        out_path = tmp_path / "report.json"
        out_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        loaded = json.loads(out_path.read_text(encoding="utf-8"))
        assert loaded["total_checked"] == 2
        db.close()


# ════════════════════════════════════════════════════════════════
# _ValidatorLLMAdapter
# ════════════════════════════════════════════════════════════════


class TestValidatorLLMAdapter:
    """Adapter bridges LLMClient.complete() to duck-typed messages.create()."""

    def test_adapter_wraps_llm_client(self):
        from unittest.mock import MagicMock
        from project_brain.interfaces.cli_admin import _ValidatorLLMAdapter

        mock_llm = MagicMock()
        mock_llm.complete.return_value = "LLM response text"

        adapter = _ValidatorLLMAdapter(mock_llm)
        resp = adapter.messages.create(
            model="test", max_tokens=256,
            messages=[{"role": "user", "content": "test prompt"}],
        )
        assert resp.content[0].text == "LLM response text"
        mock_llm.complete.assert_called_once_with("test prompt", max_tokens=256)

    def test_adapter_empty_messages(self):
        from unittest.mock import MagicMock
        from project_brain.interfaces.cli_admin import _ValidatorLLMAdapter

        mock_llm = MagicMock()
        mock_llm.complete.return_value = ""

        adapter = _ValidatorLLMAdapter(mock_llm)
        resp = adapter.messages.create(model="t", max_tokens=100, messages=[])
        assert resp.content[0].text == ""
