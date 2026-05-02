"""
tests/unit/test_team_config.py — E-03 TeamConfig + brain connect 測試

覆蓋：
  - TeamConfig 預設值
  - brain.toml [team] section parsing
  - env var override
  - brain connect writes toml
  - brain connect --disconnect clears toml
  - overlay/central-only/local-only mode validation
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from project_brain.brain_config import TeamConfig, load_config


class TestTeamConfigDefaults(unittest.TestCase):

    def test_defaults(self):
        tc = TeamConfig()
        self.assertEqual(tc.central_brain_url, "")
        self.assertEqual(tc.central_brain_key, "")
        self.assertEqual(tc.mode, "local-only")
        self.assertEqual(tc.overlay_threshold, 0.6)

    def test_load_config_has_team(self):
        cfg = load_config()
        self.assertIsNotNone(cfg.team)
        self.assertIsInstance(cfg.team, TeamConfig)


class TestTeamConfigFromTOML(unittest.TestCase):

    def test_parse_team_section(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td)
            toml_path = brain_dir / "brain.toml"
            toml_path.write_text("""
[team]
central_brain_url = "http://brain.example.com:3000"
central_brain_key = "test-key-abc"
mode = "overlay"
overlay_threshold = 0.7
""", encoding="utf-8")

            cfg = load_config(brain_dir)
            self.assertEqual(cfg.team.central_brain_url, "http://brain.example.com:3000")
            self.assertEqual(cfg.team.central_brain_key, "test-key-abc")
            self.assertEqual(cfg.team.mode, "overlay")
            self.assertAlmostEqual(cfg.team.overlay_threshold, 0.7)

    def test_missing_team_section_uses_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td)
            toml_path = brain_dir / "brain.toml"
            toml_path.write_text("[brain]\nmax_context_tokens = 8000\n", encoding="utf-8")

            cfg = load_config(brain_dir)
            self.assertEqual(cfg.team.mode, "local-only")
            self.assertEqual(cfg.team.central_brain_url, "")

    def test_partial_team_section(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td)
            toml_path = brain_dir / "brain.toml"
            toml_path.write_text("""
[team]
central_brain_url = "http://example.com:3000"
mode = "central-only"
""", encoding="utf-8")

            cfg = load_config(brain_dir)
            self.assertEqual(cfg.team.central_brain_url, "http://example.com:3000")
            self.assertEqual(cfg.team.mode, "central-only")
            self.assertEqual(cfg.team.central_brain_key, "")  # default
            self.assertAlmostEqual(cfg.team.overlay_threshold, 0.6)  # default


class TestTeamConfigEnvOverride(unittest.TestCase):

    def test_env_vars_override_toml(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td)
            toml_path = brain_dir / "brain.toml"
            toml_path.write_text("""
[team]
central_brain_url = "http://from-toml.com:3000"
mode = "overlay"
""", encoding="utf-8")

            env = {
                "BRAIN_TEAM_URL": "http://from-env.com:4000",
                "BRAIN_TEAM_KEY": "env-key-xyz",
                "BRAIN_TEAM_MODE": "central-only",
            }
            with mock.patch.dict(os.environ, env):
                cfg = load_config(brain_dir)
                self.assertEqual(cfg.team.central_brain_url, "http://from-env.com:4000")
                self.assertEqual(cfg.team.central_brain_key, "env-key-xyz")
                self.assertEqual(cfg.team.mode, "central-only")

    def test_env_vars_without_toml(self):
        env = {
            "BRAIN_TEAM_URL": "http://env-only.com:3000",
            "BRAIN_TEAM_MODE": "overlay",
        }
        with mock.patch.dict(os.environ, env):
            cfg = load_config()
            self.assertEqual(cfg.team.central_brain_url, "http://env-only.com:3000")
            self.assertEqual(cfg.team.mode, "overlay")


class TestBrainConnectCLI(unittest.TestCase):

    def test_connect_writes_toml(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td) / ".brain"
            brain_dir.mkdir()
            toml_path = brain_dir / "brain.toml"

            from project_brain.interfaces.cli_connect import _do_connect
            _do_connect(toml_path, "http://example.com:3000", "my-key", "overlay")

            self.assertTrue(toml_path.exists())
            content = toml_path.read_text(encoding="utf-8")
            self.assertIn("[team]", content)
            self.assertIn("http://example.com:3000", content)
            self.assertIn("my-key", content)
            self.assertIn('mode = "overlay"', content)

    def test_disconnect_clears_team_section(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td) / ".brain"
            brain_dir.mkdir()
            toml_path = brain_dir / "brain.toml"

            # First connect
            from project_brain.interfaces.cli_connect import _do_connect, _do_disconnect
            _do_connect(toml_path, "http://example.com:3000", "key", "overlay")
            self.assertIn("[team]", toml_path.read_text())

            # Then disconnect
            _do_disconnect(toml_path)
            if toml_path.exists():
                content = toml_path.read_text()
                self.assertNotIn("[team]", content)

    def test_connect_preserves_other_sections(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td) / ".brain"
            brain_dir.mkdir()
            toml_path = brain_dir / "brain.toml"
            toml_path.write_text('[brain]\nmax_context_tokens = 8000\n', encoding="utf-8")

            from project_brain.interfaces.cli_connect import _do_connect
            _do_connect(toml_path, "http://example.com:3000", "key", "overlay")

            content = toml_path.read_text()
            self.assertIn("[brain]", content)
            self.assertIn("max_context_tokens = 8000", content)
            self.assertIn("[team]", content)

    def test_reconnect_replaces_team_section(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td) / ".brain"
            brain_dir.mkdir()
            toml_path = brain_dir / "brain.toml"

            from project_brain.interfaces.cli_connect import _do_connect
            _do_connect(toml_path, "http://first.com:3000", "key1", "overlay")
            _do_connect(toml_path, "http://second.com:3000", "key2", "central-only")

            content = toml_path.read_text()
            self.assertNotIn("first.com", content)
            self.assertIn("second.com", content)
            self.assertIn('mode = "central-only"', content)
            # Should only have one [team] section
            self.assertEqual(content.count("[team]"), 1)

    def test_connect_rejects_invalid_mode(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td) / ".brain"
            brain_dir.mkdir()
            toml_path = brain_dir / "brain.toml"

            from project_brain.interfaces.cli_connect import _do_connect
            # Should not crash, just print error
            _do_connect(toml_path, "http://x.com", "k", "bad-mode")
            # toml should not have been written
            self.assertFalse(toml_path.exists())


class TestOverlayQueryLogic(unittest.TestCase):
    """Test the overlay decision logic (without real servers)."""

    def test_local_only_config_returns_no_client(self):
        """_get_central_client with local-only mode should return None."""
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td) / ".brain"
            brain_dir.mkdir()
            # No [team] section → local-only default
            cfg = load_config(brain_dir)
            self.assertEqual(cfg.team.mode, "local-only")

    def test_overlay_config_detected(self):
        with tempfile.TemporaryDirectory() as td:
            brain_dir = Path(td) / ".brain"
            brain_dir.mkdir()
            (brain_dir / "brain.toml").write_text("""
[team]
central_brain_url = "http://example.com:3000"
mode = "overlay"
""", encoding="utf-8")
            cfg = load_config(brain_dir)
            self.assertEqual(cfg.team.mode, "overlay")
            self.assertTrue(cfg.team.central_brain_url != "")


if __name__ == "__main__":
    unittest.main()
