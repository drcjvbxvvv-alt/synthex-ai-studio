"""
tests/unit/test_version_consistency.py

P0-2 修復驗收 — __version__ 與 pyproject.toml 一致性

背景：importlib.metadata 優先讀取 installed distribution，
導致 dev/editable 環境下 __version__ 回報舊版本。
修復後 pyproject.toml 優先。
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


class TestVersionConsistency(unittest.TestCase):
    """驗證 project_brain.__version__ == pyproject.toml version。"""

    def _read_pyproject_version(self) -> str:
        toml_path = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
        self.assertTrue(toml_path.is_file(), f"pyproject.toml not found: {toml_path}")
        text = toml_path.read_text(encoding="utf-8")
        m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
        self.assertIsNotNone(m, "version not found in pyproject.toml")
        return m.group(1)

    def test_version_matches_pyproject(self):
        """__version__ must match pyproject.toml version exactly."""
        import project_brain
        expected = self._read_pyproject_version()
        self.assertEqual(
            project_brain.__version__, expected,
            f"__version__={project_brain.__version__!r} != "
            f"pyproject.toml={expected!r}. "
            "This usually means importlib.metadata is reading a stale "
            "installed distribution."
        )

    def test_version_is_semver(self):
        """__version__ should be a valid semver-ish string."""
        import project_brain
        self.assertRegex(
            project_brain.__version__,
            r"^\d+\.\d+\.\d+",
            "__version__ should start with X.Y.Z"
        )

    def test_version_not_fallback(self):
        """__version__ should not be the hardcoded fallback."""
        import project_brain
        self.assertNotEqual(project_brain.__version__, "0.0.0",
                            "__version__ hit the last-resort fallback")
        self.assertNotEqual(project_brain.__version__, "0.22.0",
                            "__version__ hit the old hardcoded fallback")


if __name__ == "__main__":
    unittest.main()
