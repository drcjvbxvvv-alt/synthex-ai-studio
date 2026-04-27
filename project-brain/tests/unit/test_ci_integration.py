"""
D-03 CI 整合測試

驗證 CI pipeline 所依賴的所有函式在本地環境正確運作：
  - brain health --json：JSON 結構與欄位
  - brain validate --ci：CI 模式（無 LLM）通過空知識庫
  - pytest -m benchmark：benchmark marker 正常被收集
  - pyproject.toml coverage threshold 已設定

執行：
  pytest tests/unit/test_ci_integration.py -v
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


# ─────────────────────────────────────────────
# HealthChecker JSON 輸出格式
# ─────────────────────────────────────────────

class TestHealthCheckerJSON:
    """brain health --json 的 JSON 結構必須穩定，CI 解析依賴它。"""

    @pytest.fixture
    def report(self, tmp_path):
        from project_brain.health import HealthChecker
        bd = tmp_path / ".brain"
        bd.mkdir()
        # init a minimal brain.db so health checks have something to check
        from project_brain.core.brain_db import BrainDB
        BrainDB(bd).close()
        return HealthChecker(bd).run()

    def test_report_has_version_key(self, report):
        assert "version" in report

    def test_report_has_brain_dir_key(self, report):
        assert "brain_dir" in report

    def test_report_has_checks_list(self, report):
        assert "checks" in report
        assert isinstance(report["checks"], list)

    def test_report_has_summary(self, report):
        assert "summary" in report
        s = report["summary"]
        assert "overall" in s
        assert "ok" in s
        assert "warn" in s
        assert "error" in s

    def test_summary_overall_is_valid(self, report):
        assert report["summary"]["overall"] in ("ok", "warn", "error")

    def test_summary_counts_are_non_negative(self, report):
        s = report["summary"]
        assert s["ok"] >= 0
        assert s["warn"] >= 0
        assert s["error"] >= 0

    def test_summary_counts_sum_matches_checks_length(self, report):
        s = report["summary"]
        total = s["ok"] + s["warn"] + s["error"]
        assert total == len(report["checks"])

    def test_each_check_has_required_keys(self, report):
        for c in report["checks"]:
            assert "level" in c, f"Missing 'level' in check: {c}"
            assert "label" in c, f"Missing 'label' in check: {c}"
            assert "message" in c, f"Missing 'message' in check: {c}"

    def test_each_check_level_is_valid(self, report):
        for c in report["checks"]:
            assert c["level"] in ("ok", "warn", "error"), \
                f"Invalid level '{c['level']}' in check: {c['label']}"

    def test_report_is_json_serializable(self, report):
        """CI pipes this into json.dumps; must not raise."""
        result = json.dumps(report, ensure_ascii=False)
        assert isinstance(result, str)
        assert len(result) > 10

    def test_empty_brain_dir_does_not_raise(self, tmp_path):
        """health check on non-existent .brain dir must not crash."""
        from project_brain.health import HealthChecker
        bd = tmp_path / ".brain"
        # bd does NOT exist — checks should gracefully handle missing DB
        hc = HealthChecker(bd)
        report = hc.run()  # should not raise
        assert "summary" in report

    def test_health_ci_script_logic(self, report):
        """Simulate the CI exit-code logic used in ci.yml."""
        overall = report["summary"]["overall"]
        # CI accepts 'ok' or 'warn'; only 'error' fails the gate
        should_pass = overall in ("ok", "warn")
        # For a brain with only brain.db initialised, we expect ok or warn
        assert should_pass, f"Unexpected overall={overall} for fresh brain"


# ─────────────────────────────────────────────
# KnowledgeValidator CI mode
# ─────────────────────────────────────────────

class TestValidateCIMode:
    """brain validate --ci 在空知識庫上必須 passed=True 且不呼叫 LLM。"""

    @pytest.fixture
    def validator_result(self, tmp_path):
        from project_brain.core.brain_db import BrainDB
        from project_brain.graph import KnowledgeGraph
        from project_brain.engines.knowledge_validator import KnowledgeValidator
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        db.conn.commit()
        v = KnowledgeValidator(g, str(tmp_path), client=None, model="", brain_dir=bd)
        return v.run(max_api_calls=0, dry_run=True)

    def test_empty_brain_passes(self, validator_result):
        assert validator_result.invalidated_count == 0

    def test_to_dict_has_passed_key(self, validator_result):
        d = validator_result.to_dict()
        assert "passed" in d

    def test_to_dict_passed_true_on_empty(self, validator_result):
        d = validator_result.to_dict()
        assert d["passed"] is True

    def test_to_dict_has_total_checked(self, validator_result):
        d = validator_result.to_dict()
        assert "total_checked" in d
        assert isinstance(d["total_checked"], int)

    def test_no_api_calls_in_ci_mode(self, validator_result):
        assert validator_result.api_calls_used == 0

    def test_to_dict_is_json_serializable(self, validator_result):
        d = validator_result.to_dict()
        serialized = json.dumps(d, ensure_ascii=False)
        assert isinstance(serialized, str)

    def test_validate_ci_exit_logic(self, validator_result):
        """Simulate the CI exit-code logic used in ci.yml."""
        d = validator_result.to_dict()
        assert d["passed"] is True, "Empty brain should pass validation"

    def test_validate_with_nodes_passes(self, tmp_path):
        """Nodes with high confidence should pass Rule + Code stages."""
        from project_brain.core.brain_db import BrainDB
        from project_brain.graph import KnowledgeGraph
        from project_brain.engines.knowledge_validator import KnowledgeValidator
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        g.add_node("n1", "Rule", "JWT 必須驗證過期", content="exp claim 必須驗證",
                   meta={"confidence": 0.9})
        g.add_node("n2", "Decision", "選用 PostgreSQL", content="ACID 保證",
                   meta={"confidence": 0.85})
        db.conn.commit()
        v = KnowledgeValidator(g, str(tmp_path), client=None, model="", brain_dir=bd)
        report = v.run(max_api_calls=0, dry_run=True)
        assert report.to_dict()["passed"] is True


# ─────────────────────────────────────────────
# ValidationReport.to_dict() 結構
# ─────────────────────────────────────────────

class TestValidationReportDict:
    @pytest.fixture
    def empty_report(self, tmp_path):
        from project_brain.core.brain_db import BrainDB
        from project_brain.graph import KnowledgeGraph
        from project_brain.engines.knowledge_validator import KnowledgeValidator
        bd = tmp_path / ".brain"
        bd.mkdir()
        db = BrainDB(bd)
        g = KnowledgeGraph(bd, conn=db.conn)
        db.conn.commit()
        v = KnowledgeValidator(g, str(tmp_path), client=None, model="", brain_dir=bd)
        return v.run(max_api_calls=0, dry_run=True).to_dict()

    def test_has_run_id(self, empty_report):
        assert "run_id" in empty_report

    def test_has_passed(self, empty_report):
        assert "passed" in empty_report

    def test_has_total_checked(self, empty_report):
        assert "total_checked" in empty_report

    def test_has_valid(self, empty_report):
        assert "valid" in empty_report

    def test_has_flagged(self, empty_report):
        assert "flagged" in empty_report

    def test_has_invalidated(self, empty_report):
        assert "invalidated" in empty_report

    def test_has_api_calls_used(self, empty_report):
        assert "api_calls_used" in empty_report

    def test_has_elapsed_ms(self, empty_report):
        assert "elapsed_ms" in empty_report

    def test_has_results_list(self, empty_report):
        assert "results" in empty_report
        assert isinstance(empty_report["results"], list)


# ─────────────────────────────────────────────
# pyproject.toml CI 設定驗證
# ─────────────────────────────────────────────

class TestPyprojectCIConfig:
    """確認 pyproject.toml 中的 CI 相關設定正確。"""

    @pytest.fixture(scope="class")
    def pyproject(self):
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # Python 3.10 fallback
        path = PROJECT_ROOT / "pyproject.toml"
        return tomllib.loads(path.read_text(encoding="utf-8"))

    def test_dev_dependencies_include_pytest(self, pyproject):
        dev_deps = pyproject["project"]["optional-dependencies"]["dev"]
        assert any("pytest" in d for d in dev_deps)

    def test_coverage_fail_under_is_set(self, pyproject):
        """CI coverage gate must be explicitly configured."""
        threshold = pyproject["tool"]["coverage"]["report"]["fail_under"]
        assert threshold >= 45, f"Coverage threshold too low: {threshold}"

    def test_coverage_source_is_project_brain(self, pyproject):
        source = pyproject["tool"]["coverage"]["run"]["source"]
        assert "project_brain" in source

    def test_pytest_markers_include_benchmark(self, pyproject):
        markers = pyproject["tool"]["pytest"]["ini_options"]["markers"]
        assert any("benchmark" in m for m in markers)

    def test_pytest_markers_include_chaos(self, pyproject):
        markers = pyproject["tool"]["pytest"]["ini_options"]["markers"]
        assert any("chaos" in m for m in markers)

    def test_version_is_semver_format(self, pyproject):
        import re
        version = pyproject["project"]["version"]
        assert re.match(r"^\d+\.\d+\.\d+$", version), \
            f"Version '{version}' is not semver"


# ─────────────────────────────────────────────
# CI workflow 檔案存在性
# ─────────────────────────────────────────────

class TestCIWorkflowFile:
    """確認 GitHub Actions workflow 檔案存在且格式正確。"""

    @pytest.fixture(scope="class")
    def workflow_path(self):
        return PROJECT_ROOT / ".github" / "workflows" / "ci.yml"

    def test_workflow_file_exists(self, workflow_path):
        assert workflow_path.exists(), \
            f"CI workflow not found at {workflow_path}"

    def test_workflow_is_valid_yaml(self, workflow_path):
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed; skipping YAML validation")
        content = workflow_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert parsed is not None

    def test_workflow_has_on_section(self, workflow_path):
        content = workflow_path.read_text(encoding="utf-8")
        assert "on:" in content or "\"on\":" in content

    def test_workflow_has_jobs_section(self, workflow_path):
        content = workflow_path.read_text(encoding="utf-8")
        assert "jobs:" in content

    def test_workflow_has_unit_job(self, workflow_path):
        content = workflow_path.read_text(encoding="utf-8")
        assert "unit:" in content

    def test_workflow_has_coverage_job(self, workflow_path):
        content = workflow_path.read_text(encoding="utf-8")
        assert "coverage:" in content

    def test_workflow_has_health_job(self, workflow_path):
        content = workflow_path.read_text(encoding="utf-8")
        assert "health:" in content

    def test_workflow_has_validate_job(self, workflow_path):
        content = workflow_path.read_text(encoding="utf-8")
        assert "validate:" in content

    def test_workflow_uses_python_setup_action(self, workflow_path):
        content = workflow_path.read_text(encoding="utf-8")
        assert "actions/setup-python" in content

    def test_workflow_references_correct_summary_key(self, workflow_path):
        """CI health check must use d['summary']['overall'], not d['overall']."""
        content = workflow_path.read_text(encoding="utf-8")
        assert 'd["summary"]["overall"]' in content, \
            "health check must use d['summary']['overall'] not d['overall']"
