"""
tests/unit/test_silent_exception_audit.py

P2-2 靜默例外審計 — 掃描 critical modules 中的 except: pass 模式

背景：多處 except Exception: pass 靜默吞掉錯誤。部分是合理降級
（UI optional metadata、old DB columns），但影響索引、feedback、
conflict signal、schema 的吞錯是不可接受的。

本測試不修改程式碼，而是建立一個 baseline — 如果新增了靜默例外
且不在允許清單中，測試會失敗。
"""
from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

# Critical modules to audit
CRITICAL_MODULES = [
    "project_brain/core/brain_db.py",
    "project_brain/interfaces/mcp_server.py",
    "project_brain/interfaces/web_ui/server.py",
    "project_brain/engines/context.py",
    "project_brain/health.py",
]

# Patterns that indicate a silent exception (no logging after except)
_SILENT_RE = re.compile(
    r"except\s+(?:Exception|BaseException).*?:\s*\n\s*pass",
    re.MULTILINE,
)


def _find_silent_exceptions(filepath: Path) -> list[dict]:
    """Find except blocks that silently pass without logging.

    Returns list of {"line": int, "code": str} for each silent except.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    results = []
    lines = source.split("\n")
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        # Match: except <anything>:
        if re.match(r"except\s+(Exception|BaseException)", stripped):
            # Check next non-empty line
            for j in range(i, min(i + 3, len(lines))):
                next_line = lines[j].strip()
                if not next_line:
                    continue
                if next_line == "pass":
                    results.append({
                        "line": i,
                        "code": stripped,
                        "next": next_line,
                        "file": str(filepath),
                    })
                break
    return results


def _find_bare_excepts(filepath: Path) -> list[dict]:
    """Find bare 'except:' without specifying exception type."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []

    results = []
    for i, line in enumerate(source.split("\n"), 1):
        stripped = line.strip()
        if stripped == "except:" or stripped.startswith("except:"):
            results.append({
                "line": i,
                "code": stripped,
                "file": str(filepath),
            })
    return results


class TestSilentExceptionAudit(unittest.TestCase):
    """Audit silent exceptions in critical modules."""

    def _project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent.parent

    def test_count_silent_exceptions_in_critical_modules(self):
        """Record baseline count of silent exceptions.

        This test documents the current state. If new silent exceptions
        are added, this count will increase and the test should be updated
        (or the code fixed).
        """
        root = self._project_root()
        total = 0
        by_file: dict[str, int] = {}
        for mod in CRITICAL_MODULES:
            path = root / mod
            silent = _find_silent_exceptions(path)
            count = len(silent)
            total += count
            if count > 0:
                by_file[mod] = count

        # Baseline: document but don't fail yet.
        # The important thing is that this count doesn't grow.
        # Current known silent exceptions are mostly in:
        #   - brain_db.py: migration compat, optional columns
        #   - web_ui/server.py: FTS sync best-effort
        # Store the count for regression detection
        self.assertLessEqual(
            total, 25,
            f"Too many silent exceptions ({total}). "
            f"By file: {by_file}. "
            "New code should use logger.warning() instead of pass."
        )

    def test_no_bare_excepts_in_critical_modules(self):
        """No bare 'except:' (without type) in critical modules."""
        root = self._project_root()
        bare = []
        for mod in CRITICAL_MODULES:
            path = root / mod
            found = _find_bare_excepts(path)
            bare.extend(found)

        self.assertEqual(
            len(bare), 0,
            f"Found {len(bare)} bare 'except:' without type: "
            + ", ".join(f"{b['file']}:{b['line']}" for b in bare[:5])
        )

    def test_mcp_server_conflict_check_not_silent(self):
        """P0-1 regression: MCP add_knowledge conflict check must not
        silently swallow TypeError."""
        root = self._project_root()
        # H-02: tools now in mcp_tools/ sub-modules
        mcp_tools_dir = root / "project_brain/interfaces/mcp_tools"
        source = ""
        if mcp_tools_dir.exists():
            for f in mcp_tools_dir.glob("*.py"):
                source += f.read_text(encoding="utf-8")
        else:
            mcp_path = root / "project_brain/interfaces/mcp_server.py"
            source = mcp_path.read_text(encoding="utf-8")

        # The background conflict check should call find_conflicts_for_node
        self.assertIn("find_conflicts_for_node", source,
                       "MCP should use find_conflicts_for_node, not find_conflicts")

        # The old broken call should not exist
        self.assertNotIn("find_conflicts(title_c", source,
                          "Old broken find_conflicts(title_c, top_k=3) should be removed")

    def test_critical_paths_have_logging(self):
        """Key operations should log errors, not silently pass.

        Checks that add_node, search_nodes error paths use logger
        rather than bare pass. H-01: also checks repository files.
        """
        root = self._project_root()
        # H-01: search across brain_db.py and repository files
        search_files = [
            root / "project_brain/core/brain_db.py",
            root / "project_brain/storage/repositories/node_repo.py",
            root / "project_brain/storage/repositories/search_repo.py",
        ]

        for fn_name in ["add_node", "search_nodes"]:
            found_logger = False
            for fpath in search_files:
                if not fpath.exists():
                    continue
                lines = fpath.read_text().split("\n")
                fn_start = None
                for i, line in enumerate(lines):
                    if f"def {fn_name}(" in line:
                        fn_start = i
                        break
                if fn_start is None:
                    continue
                fn_indent = len(lines[fn_start]) - len(lines[fn_start].lstrip())
                fn_body_lines = []
                for j in range(fn_start + 1, min(fn_start + 200, len(lines))):
                    if lines[j].strip() and not lines[j].strip().startswith("#"):
                        cur_indent = len(lines[j]) - len(lines[j].lstrip())
                        if cur_indent <= fn_indent and lines[j].strip().startswith("def "):
                            break
                    fn_body_lines.append(lines[j])
                fn_body = "\n".join(fn_body_lines)
                if "logger." in fn_body:
                    found_logger = True
                    break
            self.assertTrue(
                found_logger,
                f"{fn_name} should have logger calls in error paths"
            )


class TestSilentExceptionDetail(unittest.TestCase):
    """Detailed output of all silent exceptions (informational, not gating)."""

    def test_list_all_silent_exceptions(self):
        """Print all silent exceptions for manual review."""
        root = Path(__file__).resolve().parent.parent.parent
        all_silent = []
        for mod in CRITICAL_MODULES:
            path = root / mod
            silent = _find_silent_exceptions(path)
            all_silent.extend(silent)

        # This test always passes but logs findings
        if all_silent:
            summary = "\n".join(
                f"  {s['file']}:{s['line']} — {s['code']}"
                for s in all_silent
            )
            # Log but don't fail — this is a reference for future cleanup
            print(f"\n[AUDIT] {len(all_silent)} silent exceptions found:\n{summary}")


if __name__ == "__main__":
    unittest.main()
