"""
tests/unit/test_admin_keys_cli.py — E-05 API Key 管理 CLI 測試

覆蓋：
  - create-key round-trip
  - list-keys
  - revoke-key
  - invalid role rejected
  - missing name rejected
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from types import SimpleNamespace

from project_brain.core.brain_db import BrainDB


class TestCreateKey(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name) / ".brain"
        self.brain_dir.mkdir()
        self.db = BrainDB(self.brain_dir)

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_create_key_stores_in_db(self):
        from project_brain.interfaces.cli_admin_keys import _do_create_key
        args = SimpleNamespace(
            workdir=str(self.brain_dir.parent),
            role="contributor", name="Alice",
        )
        _do_create_key(args)

        keys = self.db.list_api_keys()
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]["role"], "contributor")
        self.assertEqual(keys[0]["name"], "Alice")

    def test_create_key_invalid_role_rejected(self):
        from project_brain.interfaces.cli_admin_keys import _do_create_key
        args = SimpleNamespace(
            workdir=str(self.brain_dir.parent),
            role="superadmin", name="Eve",
        )
        # Should not crash, just print error
        _do_create_key(args)
        keys = self.db.list_api_keys()
        self.assertEqual(len(keys), 0)

    def test_create_key_missing_name_rejected(self):
        from project_brain.interfaces.cli_admin_keys import _do_create_key
        args = SimpleNamespace(
            workdir=str(self.brain_dir.parent),
            role="reader", name="",
        )
        _do_create_key(args)
        keys = self.db.list_api_keys()
        self.assertEqual(len(keys), 0)


class TestListKeys(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name) / ".brain"
        self.brain_dir.mkdir()
        self.db = BrainDB(self.brain_dir)
        self.db.store_api_key("key-1", "reader", "Alice")
        self.db.store_api_key("key-2", "admin", "Bob")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_list_keys_shows_all(self):
        from project_brain.interfaces.cli_admin_keys import _do_list_keys
        args = SimpleNamespace(workdir=str(self.brain_dir.parent))
        # Should not crash
        _do_list_keys(args)

    def test_list_keys_empty(self):
        with tempfile.TemporaryDirectory() as td:
            bd = Path(td) / ".brain"
            bd.mkdir()
            db2 = BrainDB(bd)
            db2.close()
            from project_brain.interfaces.cli_admin_keys import _do_list_keys
            args = SimpleNamespace(workdir=str(bd.parent))
            _do_list_keys(args)  # should not crash


class TestRevokeKey(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name) / ".brain"
        self.brain_dir.mkdir()
        self.db = BrainDB(self.brain_dir)
        self.key_id = self.db.store_api_key("revoke-me", "contributor", "Charlie")

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_revoke_key_succeeds(self):
        from project_brain.interfaces.cli_admin_keys import _do_revoke_key
        args = SimpleNamespace(
            workdir=str(self.brain_dir.parent),
            key_id=str(self.key_id),
        )
        _do_revoke_key(args)

        # Verify revoked
        info = self.db.resolve_api_key("revoke-me")
        self.assertIsNone(info)

    def test_revoke_nonexistent_key(self):
        from project_brain.interfaces.cli_admin_keys import _do_revoke_key
        args = SimpleNamespace(
            workdir=str(self.brain_dir.parent),
            key_id="99999",
        )
        _do_revoke_key(args)  # should not crash

    def test_revoke_invalid_id(self):
        from project_brain.interfaces.cli_admin_keys import _do_revoke_key
        args = SimpleNamespace(
            workdir=str(self.brain_dir.parent),
            key_id="not-a-number",
        )
        _do_revoke_key(args)  # should not crash


if __name__ == "__main__":
    unittest.main()
