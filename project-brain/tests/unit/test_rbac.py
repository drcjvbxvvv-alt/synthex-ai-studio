"""
tests/unit/test_rbac.py — E-02 RBAC 測試

覆蓋：
  - has_permission 層級正確
  - store_api_key + resolve_api_key round-trip
  - expired key → None
  - revoked key → None
  - unknown key → None
  - schema migration v29
  - list_api_keys
  - invalid role rejected
"""
from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from project_brain.core.brain_db import BrainDB
from project_brain.rbac import (
    ROLE_HIERARCHY,
    TOOL_PERMISSIONS,
    VALID_ROLES,
    has_permission,
)


class TestHasPermission(unittest.TestCase):
    """has_permission 層級判斷。"""

    def test_admin_has_all_permissions(self):
        for role in ROLE_HIERARCHY:
            self.assertTrue(has_permission("admin", role))

    def test_reader_only_has_reader(self):
        self.assertTrue(has_permission("reader", "reader"))
        self.assertFalse(has_permission("reader", "contributor"))
        self.assertFalse(has_permission("reader", "maintainer"))
        self.assertFalse(has_permission("reader", "admin"))

    def test_contributor_has_reader_and_contributor(self):
        self.assertTrue(has_permission("contributor", "reader"))
        self.assertTrue(has_permission("contributor", "contributor"))
        self.assertFalse(has_permission("contributor", "maintainer"))

    def test_maintainer_hierarchy(self):
        self.assertTrue(has_permission("maintainer", "reader"))
        self.assertTrue(has_permission("maintainer", "contributor"))
        self.assertTrue(has_permission("maintainer", "maintainer"))
        self.assertFalse(has_permission("maintainer", "admin"))

    def test_unknown_role_denied(self):
        self.assertFalse(has_permission("hacker", "reader"))

    def test_unknown_required_role_denied(self):
        self.assertFalse(has_permission("admin", "superadmin"))

    def test_tool_permissions_are_valid_roles(self):
        for tool, role in TOOL_PERMISSIONS.items():
            self.assertIn(role, VALID_ROLES,
                          f"Tool {tool} requires unknown role {role}")


class TestAPIKeyStorage(unittest.TestCase):
    """API key store/resolve/revoke/list round-trip。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = BrainDB(Path(self._tmp.name))

    def tearDown(self):
        self.db.close()
        self._tmp.cleanup()

    def test_store_and_resolve_round_trip(self):
        kid = self.db.store_api_key("my-secret-key", "contributor", "Alice")
        self.assertGreater(kid, 0)
        info = self.db.resolve_api_key("my-secret-key")
        self.assertIsNotNone(info)
        self.assertEqual(info["role"], "contributor")
        self.assertEqual(info["name"], "Alice")
        self.assertEqual(info["key_id"], kid)

    def test_resolve_nonexistent_key_returns_none(self):
        self.assertIsNone(self.db.resolve_api_key("no-such-key"))

    def test_resolve_revoked_key_returns_none(self):
        kid = self.db.store_api_key("revoke-me", "reader", "Bob")
        self.assertTrue(self.db.revoke_api_key(kid))
        self.assertIsNone(self.db.resolve_api_key("revoke-me"))

    def test_revoke_nonexistent_returns_false(self):
        self.assertFalse(self.db.revoke_api_key(99999))

    def test_double_revoke_returns_false(self):
        kid = self.db.store_api_key("double-revoke", "reader")
        self.assertTrue(self.db.revoke_api_key(kid))
        self.assertFalse(self.db.revoke_api_key(kid))

    def test_resolve_expired_key_returns_none(self):
        kid = self.db.store_api_key("expired-key", "contributor", "Charlie")
        # Manually set expires_at to past
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        self.db._execute_write(
            "UPDATE api_keys SET expires_at = ? WHERE id = ?",
            (past, kid),
        )
        self.assertIsNone(self.db.resolve_api_key("expired-key"))

    def test_resolve_future_expiry_succeeds(self):
        kid = self.db.store_api_key("future-key", "admin", "Dave")
        future = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        self.db._execute_write(
            "UPDATE api_keys SET expires_at = ? WHERE id = ?",
            (future, kid),
        )
        info = self.db.resolve_api_key("future-key")
        self.assertIsNotNone(info)
        self.assertEqual(info["role"], "admin")

    def test_list_api_keys(self):
        self.db.store_api_key("k1", "reader", "Alice")
        self.db.store_api_key("k2", "contributor", "Bob")
        keys = self.db.list_api_keys()
        self.assertEqual(len(keys), 2)
        names = {k["name"] for k in keys}
        self.assertEqual(names, {"Alice", "Bob"})

    def test_invalid_role_raises(self):
        with self.assertRaises(ValueError):
            self.db.store_api_key("bad-role", "superadmin", "Eve")

    def test_different_tokens_different_hashes(self):
        self.db.store_api_key("token-a", "reader", "A")
        self.db.store_api_key("token-b", "contributor", "B")
        a = self.db.resolve_api_key("token-a")
        b = self.db.resolve_api_key("token-b")
        self.assertEqual(a["role"], "reader")
        self.assertEqual(b["role"], "contributor")


class TestSchemaV29Migration(unittest.TestCase):
    """Schema migration v29 creates api_keys table."""

    def test_api_keys_table_exists(self):
        with tempfile.TemporaryDirectory() as td:
            db = BrainDB(Path(td))
            tables = {r[0] for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}
            self.assertIn("api_keys", tables)
            db.close()

    def test_schema_version_is_29(self):
        with tempfile.TemporaryDirectory() as td:
            db = BrainDB(Path(td))
            row = db.conn.execute(
                "SELECT value FROM brain_meta WHERE key='schema_version'"
            ).fetchone()
            self.assertEqual(row[0], "29")
            db.close()


if __name__ == "__main__":
    unittest.main()
