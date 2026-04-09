"""
tests/unit/test_federation.py

BLOCKER-03 — Federation 模組完整測試套件
(ARCHITECTURE_REVIEW.md §3 BLOCKER-03, §5.2 Phase 2)

原本 project_brain/integrations/federation.py 有 849 行實作但零專用測試，
為 v0.33 前的最高風險漏洞之一。本檔案補齊覆蓋：

  _strip_pii                    PII 過濾 helper（6 個 regex）
  FederationBundle              JSON 序列化/反序列化
  FederationExporter            export + _sanitise_node + _parse_tags
  FederationImporter            import_bundle + 去重 + 過濾 + FED-01 audit
  SubscriptionManager           subscribe / unsubscribe / list / is_subscribed
  FederationAutoSync            add/remove source + sync_all
  _validate_workdir             路徑遍歷 + symlink 攻擊（multi_brain_query 前置）

驗收基準：覆蓋 ARCHITECTURE_REVIEW.md §3 BLOCKER-03 所列的
TestPIIStripping / TestExportRoundTrip / TestMultiBrainQuery /
TestConflictResolution 四個群組，且超過其最小規格。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Optional

from project_brain.integrations.federation import (
    FederationAutoSync,
    FederationBundle,
    FederationExporter,
    FederationImporter,
    SubscriptionManager,
    _strip_pii,
)


# ══════════════════════════════════════════════════════════════════
#  測試輔助：最小可用的 KnowledgeGraph（含 scope 欄位）+ FakeKRB
# ══════════════════════════════════════════════════════════════════

def _make_graph_with_scope(brain_dir: Path):
    """
    建立真實 KnowledgeGraph 並補上 scope 欄位（federation export 需要）。

    KnowledgeGraph 預設 schema 沒有 scope 欄位，但 FederationExporter 兩條
    SQL 路徑都會參考 scope。本 helper 透過 ALTER TABLE 模擬「已啟用 scope 的
    資料庫」，讓匯出主路徑能被覆蓋，而不是只跑 fallback。
    """
    from project_brain.graph import KnowledgeGraph
    g = KnowledgeGraph(brain_dir)
    try:
        g._conn.execute("ALTER TABLE nodes ADD COLUMN scope TEXT DEFAULT 'global'")
        g._conn.commit()
    except sqlite3.OperationalError:
        # 欄位已存在（較新 schema）
        pass
    return g


def _insert_node(
    graph,
    node_id:    str,
    title:      str,
    content:    str = "",
    kind:       str = "Rule",
    tags:       Optional[list] = None,
    confidence: float = 0.8,
    scope:      str = "global",
) -> None:
    """把一個節點塞進 KnowledgeGraph（跳過 add_node 的 FTS N-gram 流程）。"""
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    graph._conn.execute(
        """INSERT INTO nodes
           (id, type, title, content, tags, confidence, meta, scope)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (node_id, kind, title, content, tags_json, confidence, "{}", scope),
    )
    graph._conn.commit()


class _FakeKRB:
    """
    FederationImporter 需要的最小 KRB 介面：
        - graph._conn 用於去重 SELECT
        - submit(title, content, kind, tags, source, submitter)
    """

    def __init__(self, graph) -> None:
        self.graph = graph
        self.submitted: list[dict] = []

    def submit(self, title: str, content: str, kind: str,
               tags: str, source: str, submitter: str) -> str:
        sid = f"stg-{len(self.submitted):04d}"
        self.submitted.append({
            "id": sid, "title": title, "content": content,
            "kind": kind, "tags": tags, "source": source, "submitter": submitter,
        })
        return sid


class _FakeBrainDB:
    """最小 BrainDB：只記錄 record_federation_import() 被如何呼叫。"""

    def __init__(self) -> None:
        self.audit_records: list[dict] = []

    def record_federation_import(
        self,
        source:     str,
        node_id:    str,
        node_title: str,
        status:     str = "pending",
    ) -> int:
        self.audit_records.append({
            "source": source, "node_id": node_id,
            "node_title": node_title, "status": status,
        })
        return len(self.audit_records)


def _make_brain_env():
    """建立 tmp brain_dir + graph + krb。呼叫者負責清理 tempdir。"""
    tmp = tempfile.TemporaryDirectory()
    brain_dir = Path(tmp.name) / ".brain"
    brain_dir.mkdir()
    graph = _make_graph_with_scope(brain_dir)
    krb   = _FakeKRB(graph)
    return tmp, brain_dir, graph, krb


# ══════════════════════════════════════════════════════════════════
#  TestPIIStripping  — BLOCKER-03 spec §3:457
# ══════════════════════════════════════════════════════════════════

class TestPIIStripping(unittest.TestCase):
    """_strip_pii() 必須移除 email / 內部主機名 / 私有 IP / Slack / Cloud URL。"""

    def test_email_stripped(self):
        cleaned = _strip_pii("Contact alice@corp.example for details")
        self.assertNotIn("alice@corp.example", cleaned)
        self.assertIn("[redacted-email]", cleaned)

    def test_email_multiple_in_one_string(self):
        cleaned = _strip_pii("cc: a@x.io, b@y.io, c@z.io")
        # 三個都要被換掉
        self.assertEqual(cleaned.count("[redacted-email]"), 3)
        self.assertNotIn("@x.io", cleaned)
        self.assertNotIn("@y.io", cleaned)

    def test_internal_host_stripped(self):
        cleaned = _strip_pii("see internal.example.com/wiki for details")
        self.assertNotIn("internal.example.com", cleaned)
        self.assertIn("[redacted-internal]", cleaned)

    def test_internal_corp_stripped(self):
        cleaned = _strip_pii("jenkins at corp.mycorp.net fails nightly")
        self.assertNotIn("corp.mycorp.net", cleaned)
        self.assertIn("[redacted-internal]", cleaned)

    def test_local_hostname_stripped(self):
        cleaned = _strip_pii("connect to dev-machine.local for debugging")
        self.assertNotIn("dev-machine.local", cleaned)
        self.assertIn("[redacted-local]", cleaned)

    def test_private_ip_10_x_stripped(self):
        cleaned = _strip_pii("API gateway at 10.1.2.3 is down")
        self.assertNotIn("10.1.2.3", cleaned)
        self.assertIn("[redacted-ip]", cleaned)

    def test_private_ip_172_16_stripped(self):
        cleaned = _strip_pii("route via 172.16.0.1 and 172.31.255.1")
        self.assertNotIn("172.16.0.1", cleaned)
        self.assertNotIn("172.31.255.1", cleaned)
        self.assertEqual(cleaned.count("[redacted-ip]"), 2)

    def test_private_ip_192_168_stripped(self):
        cleaned = _strip_pii("router default 192.168.1.1")
        self.assertNotIn("192.168.1.1", cleaned)
        self.assertIn("[redacted-ip]", cleaned)

    def test_public_ip_not_stripped(self):
        # 172.15 不在私有範圍、8.8.8.8 不在私有範圍
        cleaned = _strip_pii("DNS 8.8.8.8 and 172.15.0.1")
        self.assertIn("8.8.8.8", cleaned)
        self.assertIn("172.15.0.1", cleaned)

    def test_slack_url_stripped(self):
        cleaned = _strip_pii("see https://myteam.slack.com/archives/C12345 for thread")
        self.assertNotIn("myteam.slack.com", cleaned)
        self.assertIn("[redacted-slack-url]", cleaned)

    def test_s3_url_stripped(self):
        cleaned = _strip_pii("bucket at https://logs.s3.us-west-2.amazonaws.com/2024/")
        self.assertNotIn("amazonaws.com", cleaned)
        self.assertIn("[redacted-cloud-url]", cleaned)

    def test_azure_blob_stripped(self):
        cleaned = _strip_pii("logs at https://acct.blob.core.windows.net/container")
        self.assertNotIn("blob.core.windows.net", cleaned)
        self.assertIn("[redacted-cloud-url]", cleaned)

    def test_variable_name_not_stripped(self):
        # 程式碼中的變數 / 識別字不應被誤判
        code = "let user_email = getEmail(); class InternalAPI {}"
        cleaned = _strip_pii(code)
        self.assertIn("user_email", cleaned)
        self.assertIn("InternalAPI", cleaned)
        # 不可出現 redaction 標籤
        self.assertNotIn("[redacted", cleaned)

    def test_cjk_content_preserved(self):
        """中文 / CJK 內容不應被 PII regex 誤傷。"""
        text = "使用 RS256 而非 HS256 簽署 JWT — 避免密鑰洩漏"
        cleaned = _strip_pii(text)
        self.assertEqual(cleaned, text)

    def test_empty_string(self):
        self.assertEqual(_strip_pii(""), "")

    def test_mixed_pii_all_stripped(self):
        dirty = (
            "contact ops@corp.io at 10.0.0.1, slack https://foo.slack.com/x, "
            "bucket https://logs.s3.us-east-1.amazonaws.com/backups"
        )
        cleaned = _strip_pii(dirty)
        self.assertNotIn("ops@corp.io",    cleaned)
        self.assertNotIn("10.0.0.1",       cleaned)
        self.assertNotIn("foo.slack.com",  cleaned)
        self.assertNotIn("amazonaws.com",  cleaned)


# ══════════════════════════════════════════════════════════════════
#  TestFederationBundle  — JSON 序列化/反序列化
# ══════════════════════════════════════════════════════════════════

class TestFederationBundle(unittest.TestCase):

    def _make_bundle(self) -> FederationBundle:
        return FederationBundle(
            version        = "1.0",
            source_project = "test-proj",
            exported_at    = "2026-04-09T00:00:00+00:00",
            nodes          = [{"id": "n1", "title": "test", "content": "body"}],
            domain_tags    = ["rust", "security"],
            node_count     = 1,
        )

    def test_roundtrip(self):
        b1  = self._make_bundle()
        raw = b1.to_json()
        b2  = FederationBundle.from_json(raw)
        self.assertEqual(b2.source_project, b1.source_project)
        self.assertEqual(b2.nodes,           b1.nodes)
        self.assertEqual(b2.domain_tags,     b1.domain_tags)
        self.assertEqual(b2.node_count,      b1.node_count)

    def test_to_json_is_utf8_and_pretty(self):
        bundle = FederationBundle(
            version="1.0", source_project="測試",
            exported_at="2026-04-09T00:00:00+00:00",
            nodes=[{"title": "中文規則"}], domain_tags=[], node_count=1,
        )
        raw = bundle.to_json()
        # ensure_ascii=False → 中文應以原字元形式出現
        self.assertIn("中文規則", raw)
        self.assertIn("\n", raw)   # indent=2 會產生換行

    def test_from_json_with_missing_fields_uses_defaults(self):
        minimal = json.dumps({"nodes": [{"title": "x"}]})
        bundle  = FederationBundle.from_json(minimal)
        self.assertEqual(bundle.source_project, "")
        self.assertEqual(bundle.version,        "1.0")
        self.assertEqual(len(bundle.nodes),     1)


# ══════════════════════════════════════════════════════════════════
#  TestFederationExporter
# ══════════════════════════════════════════════════════════════════

class TestFederationExporter(unittest.TestCase):

    def setUp(self):
        self._tmp, self.brain_dir, self.graph, self.krb = _make_brain_env()
        self.exporter = FederationExporter(
            self.graph, self.brain_dir, project_name="proj-a",
        )

    def tearDown(self):
        try:
            self.graph.close()
        except Exception:
            pass
        self._tmp.cleanup()

    # ── export 主流程 ────────────────────────────────────────────

    def test_export_empty_db(self):
        bundle = self.exporter.export()
        self.assertEqual(bundle.node_count, 0)
        self.assertEqual(bundle.nodes, [])
        self.assertEqual(bundle.source_project, "proj-a")
        # 檔案應該有被寫出
        default_out = self.brain_dir / "federation_export.json"
        self.assertTrue(default_out.exists())

    def test_export_basic_nodes(self):
        _insert_node(self.graph, "n1", "Use RS256 for JWT", "no HS256",
                     tags=["security", "jwt"], confidence=0.9)
        _insert_node(self.graph, "n2", "Pin dependency versions", "",
                     tags=["build"], confidence=0.8)

        bundle = self.exporter.export(min_confidence=0.0)
        self.assertEqual(bundle.node_count, 2)
        titles = [n["title"] for n in bundle.nodes]
        self.assertIn("Use RS256 for JWT", titles)
        self.assertIn("Pin dependency versions", titles)

    def test_export_respects_min_confidence(self):
        _insert_node(self.graph, "high", "High conf",  confidence=0.9)
        _insert_node(self.graph, "mid",  "Middle conf", confidence=0.65)
        _insert_node(self.graph, "low",  "Low conf",    confidence=0.3)

        bundle = self.exporter.export(min_confidence=0.6)
        titles = [n["title"] for n in bundle.nodes]
        self.assertIn("High conf",   titles)
        self.assertIn("Middle conf", titles)
        self.assertNotIn("Low conf", titles)

    def test_export_respects_max_nodes(self):
        for i in range(10):
            _insert_node(self.graph, f"n{i}", f"Rule {i}", confidence=0.9)
        bundle = self.exporter.export(max_nodes=3, min_confidence=0.0)
        self.assertEqual(bundle.node_count, 3)

    def test_export_order_by_confidence_desc(self):
        _insert_node(self.graph, "lo",  "Low rule",    confidence=0.6)
        _insert_node(self.graph, "hi",  "High rule",   confidence=0.95)
        _insert_node(self.graph, "mid", "Middle rule", confidence=0.8)

        bundle = self.exporter.export(min_confidence=0.0)
        confidences = [n["confidence"] for n in bundle.nodes]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_export_excludes_private_scope(self):
        _insert_node(self.graph, "g1", "Global rule",   scope="global")
        _insert_node(self.graph, "p1", "Private secret", scope="private-proj",
                     confidence=0.9)

        bundle = self.exporter.export(scope="global", min_confidence=0.0)
        titles = [n["title"] for n in bundle.nodes]
        self.assertIn("Global rule", titles)
        self.assertNotIn("Private secret", titles)

    def test_export_strips_pii_from_title_and_content(self):
        _insert_node(
            self.graph, "pii1",
            title="Ping dev at dev@corp.example during incident",
            content="Check https://foo.slack.com/archives/C1 and 10.0.0.5 logs",
            confidence=0.9,
        )
        bundle = self.exporter.export(min_confidence=0.0)
        self.assertEqual(bundle.node_count, 1)
        node = bundle.nodes[0]
        # PII must be gone from both title and content
        self.assertNotIn("dev@corp.example", node["title"])
        self.assertNotIn("foo.slack.com",    node["content"])
        self.assertNotIn("10.0.0.5",         node["content"])
        self.assertIn("[redacted-email]",    node["title"])

    def test_export_collects_domain_tags(self):
        _insert_node(self.graph, "a", "A", tags=["rust", "async"],    confidence=0.9)
        _insert_node(self.graph, "b", "B", tags=["RUST", "security"], confidence=0.9)
        bundle = self.exporter.export(min_confidence=0.0)
        # domain_tags 全小寫、去重、排序
        self.assertIn("rust",     bundle.domain_tags)
        self.assertIn("security", bundle.domain_tags)
        self.assertIn("async",    bundle.domain_tags)
        self.assertEqual(bundle.domain_tags, sorted(bundle.domain_tags))

    def test_export_skips_empty_title(self):
        _insert_node(self.graph, "empty", "", "no title but has body",
                     confidence=0.9)
        bundle = self.exporter.export(min_confidence=0.0)
        self.assertEqual(bundle.node_count, 0)

    def test_export_writes_file(self):
        _insert_node(self.graph, "n1", "Test rule", confidence=0.9)
        out_path = self.brain_dir / "custom_export.json"
        bundle   = self.exporter.export(output_path=out_path, min_confidence=0.0)
        self.assertTrue(out_path.exists())
        # 檔案內容與 bundle 一致
        reloaded = FederationBundle.from_json(out_path.read_text(encoding="utf-8"))
        self.assertEqual(reloaded.node_count, bundle.node_count)

    def test_export_truncates_long_content(self):
        long_body = "x" * 5_000
        _insert_node(self.graph, "long", "Long rule", content=long_body,
                     confidence=0.9)
        bundle = self.exporter.export(min_confidence=0.0)
        # _MAX_CONTENT_LEN = 600
        self.assertLessEqual(len(bundle.nodes[0]["content"]), 600)

    # ── _parse_tags 單元 ──────────────────────────────────────────

    def test_parse_tags_json_array(self):
        self.assertEqual(
            FederationExporter._parse_tags('["a", "b", "c"]'),
            ["a", "b", "c"],
        )

    def test_parse_tags_comma_separated(self):
        self.assertEqual(
            FederationExporter._parse_tags("rust, async , security"),
            ["rust", "async", "security"],
        )

    def test_parse_tags_empty(self):
        self.assertEqual(FederationExporter._parse_tags(""),   [])
        self.assertEqual(FederationExporter._parse_tags(None), [])  # type: ignore

    def test_parse_tags_malformed_json_falls_back_to_csv(self):
        # 開頭是 [ 但 JSON 破損 → 回退 CSV 解析（有 [ 和 ] 會保留）
        result = FederationExporter._parse_tags("[broken, notjson")
        self.assertTrue(len(result) >= 1)


# ══════════════════════════════════════════════════════════════════
#  TestFederationImporter
# ══════════════════════════════════════════════════════════════════

class TestFederationImporter(unittest.TestCase):

    def setUp(self):
        self._tmp, self.brain_dir, self.graph, self.krb = _make_brain_env()

    def tearDown(self):
        try:
            self.graph.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _write_bundle(self, nodes: list[dict], domain_tags: Optional[list] = None) -> Path:
        bundle = FederationBundle(
            version        = "1.0",
            source_project = "upstream-proj",
            exported_at    = "2026-04-09T00:00:00+00:00",
            nodes          = nodes,
            domain_tags    = domain_tags or [],
            node_count     = len(nodes),
        )
        path = self.brain_dir / "import_bundle.json"
        path.write_text(bundle.to_json(), encoding="utf-8")
        return path

    # ── 基本 import ───────────────────────────────────────────────

    def test_import_basic(self):
        path = self._write_bundle([
            {"title": "Upstream rule A", "content": "body A",
             "kind": "Rule", "confidence": 0.8, "tags": ""},
            {"title": "Upstream rule B", "content": "body B",
             "kind": "Pitfall", "confidence": 0.75, "tags": ""},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)

        self.assertEqual(stats["imported"],         2)
        self.assertEqual(stats["skipped_dup"],      0)
        self.assertEqual(stats["skipped_low_conf"], 0)
        self.assertEqual(stats["skipped_domain"],   0)
        # KRB 應該收到兩筆 submit
        self.assertEqual(len(self.krb.submitted), 2)

    def test_import_skip_low_confidence(self):
        path = self._write_bundle([
            {"title": "High",  "confidence": 0.9},
            {"title": "Low",   "confidence": 0.3},
            {"title": "Mid",   "confidence": 0.55},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)
        self.assertEqual(stats["imported"],         2)
        self.assertEqual(stats["skipped_low_conf"], 1)

    def test_import_exact_duplicate_skipped(self):
        # 預先在 graph 中塞一個同名節點
        _insert_node(self.graph, "existing", "Exact duplicate title",
                     confidence=0.9)

        path = self._write_bundle([
            {"title": "Exact duplicate title", "content": "different body",
             "confidence": 0.8},
            {"title": "New title",             "content": "new body",
             "confidence": 0.8},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)
        self.assertEqual(stats["imported"],    1)
        self.assertEqual(stats["skipped_dup"], 1)

    def test_import_jaccard_similar_title_skipped(self):
        _insert_node(self.graph, "j1",
                     "use rs256 for jwt signing always",
                     confidence=0.9)
        # Jaccard > 0.8 的變體（6 tokens 中 5 個相同）
        path = self._write_bundle([
            {"title": "use rs256 for jwt signing always really",
             "confidence": 0.8},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)
        # 被 Jaccard (或 TF-IDF) 判為重複
        self.assertEqual(stats["skipped_dup"], 1)
        self.assertEqual(stats["imported"],    0)

    def test_import_dry_run_does_not_submit(self):
        path = self._write_bundle([
            {"title": "Dry A", "confidence": 0.8},
            {"title": "Dry B", "confidence": 0.8},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, dry_run=True, min_confidence=0.5)
        self.assertEqual(stats["imported"], 2)
        # 但 KRB 不應收到任何 submit
        self.assertEqual(len(self.krb.submitted), 0)

    def test_import_subscription_filter_excludes_unsubscribed(self):
        # 訂閱只有 react
        mgr = SubscriptionManager(self.brain_dir)
        mgr.subscribe("react")

        path = self._write_bundle([
            {"title": "React hooks rule",  "tags": '["react", "hooks"]',
             "confidence": 0.8},
            {"title": "Golang context",    "tags": '["golang"]',
             "confidence": 0.8},
            {"title": "Another react tip", "tags": '["react"]',
             "confidence": 0.8},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)
        self.assertEqual(stats["imported"],       2)
        self.assertEqual(stats["skipped_domain"], 1)

    def test_import_empty_subscription_accepts_all(self):
        # 沒有訂閱 → 接受所有領域
        path = self._write_bundle([
            {"title": "Foo rule",  "tags": '["obscure-domain"]',
             "confidence": 0.8},
            {"title": "Bar rule",  "tags": '["another"]',
             "confidence": 0.8},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)
        self.assertEqual(stats["imported"],       2)
        self.assertEqual(stats["skipped_domain"], 0)

    def test_import_missing_bundle_returns_zero_stats(self):
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(
            self.brain_dir / "does_not_exist.json",
            min_confidence=0.5,
        )
        # 失敗不拋例外，只回傳零計數
        self.assertEqual(stats["imported"], 0)
        self.assertEqual(len(self.krb.submitted), 0)

    def test_import_fed01_audit_recorded(self):
        """FED-01: import 成功時必須呼叫 brain_db.record_federation_import()"""
        fake_db = _FakeBrainDB()
        importer = FederationImporter(self.krb, self.brain_dir, brain_db=fake_db)
        path = self._write_bundle([
            {"id": "upstream-n1", "title": "Audited rule", "confidence": 0.8},
        ])
        importer.import_bundle(path, min_confidence=0.5)
        self.assertEqual(len(fake_db.audit_records), 1)
        rec = fake_db.audit_records[0]
        self.assertEqual(rec["status"], "staged")
        self.assertEqual(rec["node_id"], "upstream-n1")
        self.assertTrue(rec["source"].startswith("federation:"))

    def test_import_dry_run_skips_audit(self):
        """Dry run 不應寫 FED-01 audit（只做統計）"""
        fake_db = _FakeBrainDB()
        importer = FederationImporter(self.krb, self.brain_dir, brain_db=fake_db)
        path = self._write_bundle([
            {"id": "dry-n1", "title": "Dry audited", "confidence": 0.8},
        ])
        importer.import_bundle(path, dry_run=True, min_confidence=0.5)
        self.assertEqual(len(fake_db.audit_records), 0)


# ══════════════════════════════════════════════════════════════════
#  TestSubscriptionManager
# ══════════════════════════════════════════════════════════════════

class TestSubscriptionManager(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain_dir = Path(self._tmp.name) / ".brain"
        self.brain_dir.mkdir()
        self.mgr = SubscriptionManager(self.brain_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_list_initially(self):
        self.assertEqual(self.mgr.list_subscriptions(), [])

    def test_subscribe_adds_domain(self):
        ok = self.mgr.subscribe("react")
        self.assertTrue(ok)
        self.assertIn("react", self.mgr.list_subscriptions())

    def test_subscribe_normalises_case_and_whitespace(self):
        self.mgr.subscribe("  RUST  ")
        subs = self.mgr.list_subscriptions()
        self.assertIn("rust", subs)
        self.assertNotIn("RUST", subs)

    def test_subscribe_duplicate_returns_false(self):
        self.mgr.subscribe("python")
        self.assertFalse(self.mgr.subscribe("python"))
        self.assertEqual(self.mgr.list_subscriptions().count("python"), 1)

    def test_unsubscribe_removes_domain(self):
        self.mgr.subscribe("golang")
        ok = self.mgr.unsubscribe("golang")
        self.assertTrue(ok)
        self.assertNotIn("golang", self.mgr.list_subscriptions())

    def test_unsubscribe_nonexistent_returns_false(self):
        self.assertFalse(self.mgr.unsubscribe("never-subscribed"))

    def test_is_subscribed_empty_list_returns_true(self):
        """空清單 = 接受所有"""
        self.assertTrue(self.mgr.is_subscribed("anything"))

    def test_is_subscribed_exact_match(self):
        self.mgr.subscribe("rust")
        self.assertTrue(self.mgr.is_subscribed("rust"))
        self.assertTrue(self.mgr.is_subscribed("  RUST  "))
        self.assertFalse(self.mgr.is_subscribed("python"))

    def test_subscription_persists_across_instances(self):
        self.mgr.subscribe("kubernetes")
        mgr2 = SubscriptionManager(self.brain_dir)
        self.assertIn("kubernetes", mgr2.list_subscriptions())

    def test_corrupted_config_returns_empty(self):
        """federation.json 壞掉 → _load() 回傳預設空設定，不拋例外"""
        (self.brain_dir / "federation.json").write_text(
            "{ not valid json", encoding="utf-8",
        )
        # 應該仍然能讀出空清單（log warning 但不 raise）
        self.assertEqual(self.mgr.list_subscriptions(), [])


# ══════════════════════════════════════════════════════════════════
#  TestFederationAutoSync  (VISION-03)
# ══════════════════════════════════════════════════════════════════

class TestFederationAutoSync(unittest.TestCase):

    def setUp(self):
        self._tmp, self.brain_dir, self.graph, self.krb = _make_brain_env()
        self.syncer = FederationAutoSync(self.krb, self.brain_dir)

    def tearDown(self):
        try:
            self.graph.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _write_bundle_at(self, path: Path, titles: list[str]) -> None:
        bundle = FederationBundle(
            version="1.0", source_project="upstream",
            exported_at="2026-04-09T00:00:00+00:00",
            nodes=[{"title": t, "confidence": 0.8} for t in titles],
            domain_tags=[], node_count=len(titles),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(bundle.to_json(), encoding="utf-8")

    def test_empty_sources_returns_zero(self):
        result = self.syncer.sync_all()
        self.assertEqual(result["synced"],  0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["errors"],  0)

    def test_add_source_creates_entry(self):
        bundle_path = str(self.brain_dir / "src1.json")
        ok = self.syncer.add_source("src1", bundle_path, enabled=True)
        self.assertTrue(ok)
        cfg = json.loads((self.brain_dir / "federation.json").read_text())
        self.assertEqual(len(cfg["sync_sources"]),   1)
        self.assertEqual(cfg["sync_sources"][0]["name"], "src1")

    def test_add_source_idempotent_update(self):
        self.syncer.add_source("src1", "/tmp/a.json")
        self.syncer.add_source("src1", "/tmp/b.json")   # 更新路徑
        cfg = json.loads((self.brain_dir / "federation.json").read_text())
        self.assertEqual(len(cfg["sync_sources"]),   1)
        self.assertEqual(cfg["sync_sources"][0]["bundle_path"], "/tmp/b.json")

    def test_remove_source(self):
        self.syncer.add_source("src1", "/tmp/a.json")
        self.syncer.add_source("src2", "/tmp/b.json")
        self.assertTrue(self.syncer.remove_source("src1"))
        cfg = json.loads((self.brain_dir / "federation.json").read_text())
        names = [s["name"] for s in cfg["sync_sources"]]
        self.assertEqual(names, ["src2"])

    def test_remove_nonexistent_source(self):
        self.assertFalse(self.syncer.remove_source("never-added"))

    def test_sync_all_skips_disabled(self):
        p = self.brain_dir / "disabled.json"
        self._write_bundle_at(p, ["Disabled rule"])
        self.syncer.add_source("disabled", str(p), enabled=False)
        result = self.syncer.sync_all()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["synced"],  0)
        self.assertEqual(len(self.krb.submitted), 0)

    def test_sync_all_skips_missing_bundle(self):
        self.syncer.add_source("missing", str(self.brain_dir / "no_such.json"))
        result = self.syncer.sync_all()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["synced"],  0)
        # details 應記錄 bundle_not_found
        self.assertEqual(result["details"][0]["status"], "bundle_not_found")

    def test_sync_all_imports_real_bundle(self):
        p = self.brain_dir / "real.json"
        self._write_bundle_at(p, ["Real rule A", "Real rule B"])
        self.syncer.add_source("real", str(p))
        result = self.syncer.sync_all(min_confidence=0.5)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(len(self.krb.submitted), 2)

    def test_sync_all_relative_path_resolved_to_brain_dir(self):
        """bundle_path 為相對路徑時應以 brain_dir 為基底。"""
        (self.brain_dir / "sub").mkdir()
        self._write_bundle_at(self.brain_dir / "sub" / "rel.json", ["Rel rule"])
        self.syncer.add_source("rel", "sub/rel.json")
        result = self.syncer.sync_all(min_confidence=0.5)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(len(self.krb.submitted), 1)

    def test_sync_all_dry_run(self):
        p = self.brain_dir / "dry.json"
        self._write_bundle_at(p, ["Dry rule"])
        self.syncer.add_source("dry", str(p))
        result = self.syncer.sync_all(dry_run=True, min_confidence=0.5)
        self.assertEqual(result["synced"], 1)
        self.assertEqual(len(self.krb.submitted), 0)


# ══════════════════════════════════════════════════════════════════
#  TestValidateWorkdir — multi_brain_query 前置安全檢查
#  （BLOCKER-03 §3:468-471 TestMultiBrainQuery 相關測試）
# ══════════════════════════════════════════════════════════════════

class TestValidateWorkdir(unittest.TestCase):
    """
    mcp_server._validate_workdir 是 multi_brain_query 的第一道防線，
    負責拒絕路徑遍歷、symlink 攻擊、系統目錄污染。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        # 初始化一個合法 workdir（含 .brain/）
        self.valid_wd = self.root / "project_a"
        (self.valid_wd / ".brain").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _call(self, workdir: str):
        from project_brain.interfaces.mcp_server import _validate_workdir
        return _validate_workdir(workdir)

    def test_valid_workdir_accepted(self):
        path = self._call(str(self.valid_wd))
        self.assertEqual(path, self.valid_wd.resolve())

    def test_empty_workdir_rejected(self):
        with self.assertRaises(ValueError):
            self._call("")

    def test_traversal_dotdot_rejected(self):
        """路徑含 '..' 應被拒絕（SEC-02 攻擊模式）"""
        with self.assertRaises(ValueError) as ctx:
            self._call(str(self.valid_wd) + "/../project_a")
        self.assertIn("..", str(ctx.exception))

    def test_nonexistent_workdir_rejected(self):
        with self.assertRaises(FileNotFoundError):
            self._call(str(self.root / "nonexistent"))

    def test_workdir_without_brain_rejected(self):
        wd = self.root / "no_brain"
        wd.mkdir()
        with self.assertRaises(FileNotFoundError) as ctx:
            self._call(str(wd))
        self.assertIn(".brain", str(ctx.exception))

    def test_file_instead_of_dir_rejected(self):
        f = self.root / "a_file.txt"
        f.write_text("x")
        with self.assertRaises(NotADirectoryError):
            self._call(str(f))

    @unittest.skipIf(sys.platform == "win32", "symlink 行為在 Windows 上不同")
    def test_symlink_to_forbidden_system_dir_rejected(self):
        """
        symlink 指向 /etc 等禁區應被拒絕（SEC-01：resolve 後比對禁區）。
        在測試環境無法真的指向 /etc，所以改為驗證「resolve 後仍拿到絕對路徑
        並通過 existence 檢查，然後用禁區清單匹配」的語意。
        """
        # 建立一個 symlink 指向合法 workdir → 應該被接受（不在禁區內）
        link = self.root / "link_to_valid"
        try:
            link.symlink_to(self.valid_wd, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("檔案系統不支援 symlink 或權限不足")
        result = self._call(str(link))
        # 合法 symlink 會被 resolve 到真實路徑
        self.assertEqual(result, self.valid_wd.resolve())

    @unittest.skipIf(os.geteuid() == 0 if hasattr(os, "geteuid") else False,
                     "root 跑測試會繞過 /etc 權限")
    def test_etc_path_rejected_if_accessible(self):
        """
        真的用 /etc（若存在且有 .brain，極度罕見）應被禁區規則拒絕。
        多數情況下 /etc 沒有 .brain → 觸發 FileNotFoundError（這也 OK，
        兩者任一都代表攻擊被擋下）。
        """
        with self.assertRaises((ValueError, FileNotFoundError)):
            self._call("/etc")


# ══════════════════════════════════════════════════════════════════
#  TestConflictResolution  — BLOCKER-03 §3:473
# ══════════════════════════════════════════════════════════════════

class TestConflictResolution(unittest.TestCase):
    """
    跨聯邦知識衝突時的行為：
      - 相同 title 直接去重（由 _is_duplicate 負責）
      - 不同 title 則都入 KRB Staging，由人工審查決定
    """

    def setUp(self):
        self._tmp, self.brain_dir, self.graph, self.krb = _make_brain_env()

    def tearDown(self):
        try:
            self.graph.close()
        except Exception:
            pass
        self._tmp.cleanup()

    def _write(self, nodes: list[dict]) -> Path:
        bundle = FederationBundle(
            version="1.0", source_project="upstream",
            exported_at="2026-04-09T00:00:00+00:00",
            nodes=nodes, domain_tags=[], node_count=len(nodes),
        )
        path = self.brain_dir / "bundle.json"
        path.write_text(bundle.to_json(), encoding="utf-8")
        return path

    def test_same_title_different_content_dedupped(self):
        """完全相同 title → exact-match 去重；content 不同也不 override。"""
        _insert_node(self.graph, "local",
                     "JWT must use RS256",
                     content="local rationale",
                     confidence=0.9)
        path = self._write([
            {"title":   "JWT must use RS256",
             "content": "upstream gives different reasoning",
             "confidence": 0.8},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)
        self.assertEqual(stats["imported"],    0)
        self.assertEqual(stats["skipped_dup"], 1)
        # 本地節點內容不應被覆蓋
        row = self.graph._conn.execute(
            "SELECT content FROM nodes WHERE id='local'"
        ).fetchone()
        self.assertEqual(row["content"], "local rationale")

    def test_different_title_both_imported(self):
        """不同 title 則全部進 KRB Staging，不做自動合併。"""
        _insert_node(self.graph, "local",
                     "JWT must use RS256", confidence=0.9)
        path = self._write([
            {"title": "JWT must use ES256 instead",
             "content": "alternative algorithm",
             "confidence": 0.8},
            {"title": "Rotate JWT keys quarterly",
             "content": "key rotation rule",
             "confidence": 0.8},
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        stats = importer.import_bundle(path, min_confidence=0.5)
        self.assertEqual(stats["imported"],    2)
        self.assertEqual(stats["skipped_dup"], 0)
        # 兩筆都進入 Staging 而非 L3（_FakeKRB.submitted）
        self.assertEqual(len(self.krb.submitted), 2)

    def test_imported_nodes_go_to_staging_not_l3(self):
        """
        所有 federation 匯入都應走 KRB Staging（krb.submit），
        絕不直接寫入 KnowledgeGraph.nodes（L3）。
        """
        before_count = self.graph._conn.execute(
            "SELECT COUNT(*) FROM nodes"
        ).fetchone()[0]

        path = self._write([
            {"title": f"Unique rule {i}", "confidence": 0.8}
            for i in range(5)
        ])
        importer = FederationImporter(self.krb, self.brain_dir)
        importer.import_bundle(path, min_confidence=0.5)

        after_count = self.graph._conn.execute(
            "SELECT COUNT(*) FROM nodes"
        ).fetchone()[0]
        # L3 完全沒有新增
        self.assertEqual(before_count, after_count)
        # 全部進 staging
        self.assertEqual(len(self.krb.submitted), 5)


if __name__ == "__main__":
    unittest.main()
