"""
tests/unit/test_docs_accuracy.py — D-05 文件準確性測試

驗證文件內容與程式碼的一致性：
  - COMMANDS.md 列出的命令實際存在於 CLI
  - 版本號碼在 COMMANDS.md / CHANGELOG.md / README.md 中一致
  - INSTALL.md 有必要章節
  - TEST_PLAN.md 有必要章節與目錄
  - README.md 有快速開始與架構說明

執行：
  pytest tests/unit/test_docs_accuracy.py -v
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _read(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _cli_commands() -> set[str]:
    """Return the set of registered CLI subcommand names by running --help."""
    result = subprocess.run(
        [sys.executable, "-m", "project_brain.interfaces.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    # Parse lines like "    init          ..." from the positional arguments section
    commands = set()
    in_commands = False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("<command>"):
            in_commands = True
            continue
        if in_commands:
            if stripped.startswith("-") or stripped == "options:":
                break
            if stripped and not stripped.startswith("(") and not stripped.startswith("{"):
                cmd = stripped.split()[0]
                if cmd:
                    commands.add(cmd)
    return commands


def _pyproject_version() -> str:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["version"]


# ─────────────────────────────────────────────────────────────────────────────
# TestCommandsDocAccuracy
# ─────────────────────────────────────────────────────────────────────────────

class TestCommandsDocAccuracy:
    """COMMANDS.md listed commands should exist in the CLI."""

    @pytest.fixture(scope="class")
    def cli_commands(self):
        return _cli_commands()

    @pytest.fixture(scope="class")
    def commands_md(self):
        return _read("COMMANDS.md")

    def test_commands_md_exists(self):
        assert (PROJECT_ROOT / "COMMANDS.md").exists()

    def test_commands_md_has_version_header(self, commands_md):
        """COMMANDS.md should show the current version."""
        assert "v1.0" in commands_md

    def test_brain_health_documented(self, commands_md):
        assert "brain health" in commands_md

    def test_brain_validate_documented(self, commands_md):
        assert "brain validate" in commands_md

    def test_brain_pipeline_stats_documented(self, commands_md):
        assert "brain pipeline-stats" in commands_md

    def test_brain_webui_documented(self, commands_md):
        assert "brain webui" in commands_md

    def test_brain_setup_documented(self, commands_md):
        assert "brain setup" in commands_md

    def test_brain_add_documented(self, commands_md):
        assert "brain add" in commands_md

    def test_brain_ask_documented(self, commands_md):
        assert "brain ask" in commands_md

    def test_brain_doctor_documented(self, commands_md):
        assert "brain doctor" in commands_md

    def test_health_cli_command_exists(self, cli_commands):
        """CLI must actually have a 'health' subcommand."""
        assert "health" in cli_commands, (
            f"'health' not in CLI commands: {sorted(cli_commands)}"
        )

    def test_validate_cli_command_exists(self, cli_commands):
        assert "validate" in cli_commands, (
            f"'validate' not in CLI commands: {sorted(cli_commands)}"
        )

    def test_pipeline_stats_cli_command_exists(self, cli_commands):
        assert "pipeline-stats" in cli_commands, (
            f"'pipeline-stats' not in CLI commands: {sorted(cli_commands)}"
        )

    def test_health_json_key_documented_correctly(self, commands_md):
        """COMMANDS.md must document d['summary']['overall'], not d['overall']."""
        assert 'd["summary"]["overall"]' in commands_md, (
            "COMMANDS.md health section must use d[\"summary\"][\"overall\"] "
            "(not d[\"overall\"])"
        )

    def test_validate_passed_key_documented(self, commands_md):
        """COMMANDS.md must document d['passed'] for validate output."""
        assert "d['passed']" in commands_md or 'd["passed"]' in commands_md


# ─────────────────────────────────────────────────────────────────────────────
# TestVersionConsistency
# ─────────────────────────────────────────────────────────────────────────────

class TestVersionConsistency:
    """Version numbers are consistent across key files."""

    @pytest.fixture(scope="class")
    def version(self):
        return _pyproject_version()

    def test_pyproject_version_is_semver(self, version):
        assert re.match(r"^\d+\.\d+\.\d+$", version), (
            f"pyproject.toml version '{version}' is not semver"
        )

    def test_changelog_has_current_version(self, version):
        """CHANGELOG.md must have an entry for the current version."""
        changelog = _read("CHANGELOG.md")
        assert f"v{version}" in changelog, (
            f"CHANGELOG.md missing entry for v{version}"
        )

    def test_commands_md_references_version(self):
        """COMMANDS.md should reference v1.0 (the stable doc version)."""
        commands = _read("COMMANDS.md")
        assert "v1.0" in commands

    def test_readme_exists(self):
        assert (PROJECT_ROOT / "README.md").exists()

    def test_readme_has_version_reference(self, version):
        readme = _read("README.md")
        # README should mention the current major.minor version
        major_minor = ".".join(version.split(".")[:2])
        assert major_minor in readme, (
            f"README.md doesn't reference version {major_minor}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestInstallDocStructure
# ─────────────────────────────────────────────────────────────────────────────

class TestInstallDocStructure:
    """INSTALL.md has the required sections."""

    @pytest.fixture(scope="class")
    def install_md(self):
        return _read("INSTALL.md")

    def test_install_md_exists(self):
        assert (PROJECT_ROOT / "INSTALL.md").exists()

    def test_has_performance_comparison_section(self, install_md):
        assert "效能配置對比" in install_md or "Embedding 後端" in install_md

    def test_has_recommended_install_steps(self, install_md):
        assert "推薦安裝步驟" in install_md

    def test_has_basic_install_section(self, install_md):
        assert "基本安裝" in install_md

    def test_has_mcp_config_section(self, install_md):
        assert "MCP" in install_md

    def test_has_env_variables_section(self, install_md):
        assert "環境變數" in install_md or "BRAIN_WORKDIR" in install_md

    def test_has_gpu_section(self, install_md):
        """INSTALL.md must document GPU/LoRA environment (D-01)."""
        assert "GPU" in install_md

    def test_has_lora_section(self, install_md):
        """INSTALL.md must document LoRA distillation setup."""
        assert "LoRA" in install_md

    def test_has_colab_section(self, install_md):
        """INSTALL.md should mention Google Colab as GPU alternative."""
        assert "Colab" in install_md or "colab" in install_md.lower()

    def test_has_cuda_install_command(self, install_md):
        assert "pip install torch" in install_md

    def test_install_pip_command_present(self, install_md):
        assert "pip install" in install_md and "project-brain" in install_md


# ─────────────────────────────────────────────────────────────────────────────
# TestTestPlanStructure
# ─────────────────────────────────────────────────────────────────────────────

class TestTestPlanStructure:
    """TEST_PLAN.md has required v1.0 structure."""

    @pytest.fixture(scope="class")
    def test_plan(self):
        return _read("tests/TEST_PLAN.md")

    def test_test_plan_exists(self):
        assert (PROJECT_ROOT / "tests" / "TEST_PLAN.md").exists()

    def test_test_plan_is_v1(self, test_plan):
        assert "v1.0" in test_plan

    def test_has_unit_test_section(self, test_plan):
        assert "單元測試" in test_plan or "Unit" in test_plan

    def test_has_e2e_section(self, test_plan):
        assert "E2E" in test_plan or "e2e" in test_plan

    def test_has_benchmark_section(self, test_plan):
        assert "基準測試" in test_plan or "Benchmark" in test_plan

    def test_has_coverage_threshold(self, test_plan):
        assert "45%" in test_plan or "coverage" in test_plan.lower()

    def test_has_execution_commands(self, test_plan):
        assert "pytest" in test_plan

    def test_mentions_d04_tests(self, test_plan):
        """TEST_PLAN.md should reference D-04 prod validation tests."""
        assert "D-04" in test_plan or "prod_validation" in test_plan

    def test_mentions_ci_integration_tests(self, test_plan):
        """TEST_PLAN.md should reference D-03 CI integration tests."""
        assert "D-03" in test_plan or "ci_integration" in test_plan


# ─────────────────────────────────────────────────────────────────────────────
# TestREADMEStructure
# ─────────────────────────────────────────────────────────────────────────────

class TestREADMEStructure:
    """README.md has quick-start and architecture sections."""

    @pytest.fixture(scope="class")
    def readme(self):
        return _read("README.md")

    def test_readme_exists(self):
        assert (PROJECT_ROOT / "README.md").exists()

    def test_has_quick_start(self, readme):
        assert "快速開始" in readme or "Quick Start" in readme or "brain setup" in readme

    def test_has_architecture_section(self, readme):
        assert "架構" in readme or "Architecture" in readme or "三層" in readme

    def test_has_install_command(self, readme):
        assert "pip install" in readme

    def test_has_key_commands(self, readme):
        """README should show at least the most important commands."""
        assert "brain setup" in readme
        assert "brain add" in readme
        assert "brain ask" in readme

    def test_has_health_command(self, readme):
        assert "brain health" in readme

    def test_has_link_to_commands_md(self, readme):
        assert "COMMANDS.md" in readme

    def test_has_link_to_install_md(self, readme):
        assert "INSTALL.md" in readme

    def test_has_performance_numbers(self, readme):
        """README should mention performance metrics."""
        assert "300ms" in readme or "nodes/s" in readme

    def test_three_layer_memory_described(self, readme):
        """README must describe the 3-layer memory architecture."""
        assert "L1" in readme or "L2" in readme or "L3" in readme

    def test_knowledge_types_listed(self, readme):
        """README should mention the core node types."""
        assert "Rule" in readme
        assert "Decision" in readme
        assert "Pitfall" in readme
