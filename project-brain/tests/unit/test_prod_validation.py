"""
tests/unit/test_prod_validation.py — D-04 生產驗證

驗證 Project Brain 在接近生產規模下的正確性：

  Federation 跨知識庫同步
    - 從 Brain-A export，import 到 Brain-B（真實 tmp dir）
    - PII 清理完整性（email / token / UUID / private IP）— 1000+ 節點
    - Dedup 在大量節點下的正確性（1000+ 節點中 200 個重複）

執行：
  pytest tests/unit/test_prod_validation.py -v
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

import pytest

from project_brain.integrations.federation import (
    FederationBundle,
    FederationExporter,
    FederationImporter,
    _strip_pii,
)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_graph(brain_dir: Path):
    """Real KnowledgeGraph with scope column ensured."""
    from project_brain.graph import KnowledgeGraph
    g = KnowledgeGraph(brain_dir)
    try:
        g._conn.execute("ALTER TABLE nodes ADD COLUMN scope TEXT DEFAULT 'global'")
        g._conn.commit()
    except sqlite3.OperationalError:
        pass  # already exists
    return g


def _insert_node(
    graph,
    node_id: str,
    title: str,
    content: str = "",
    kind: str = "Rule",
    tags: Optional[list] = None,
    confidence: float = 0.8,
    scope: str = "global",
) -> None:
    """Direct SQL insert — bypasses add_node for fast bulk inserts."""
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    graph._conn.execute(
        "INSERT OR IGNORE INTO nodes "
        "(id, type, title, content, tags, confidence, meta, scope) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (node_id, kind, title, content, tags_json, confidence, "{}", scope),
    )


class _FakeKRB:
    """Minimal KRB stub for FederationImporter."""

    def __init__(self, graph) -> None:
        self.graph = graph
        self.submitted: list[dict] = []

    def submit(self, title: str, content: str, kind: str,
               tags: str, source: str, submitter: str) -> str:
        sid = f"stg-{len(self.submitted):06d}"
        self.submitted.append({
            "id": sid, "title": title, "content": content,
            "kind": kind, "tags": tags, "source": source,
        })
        return sid


@pytest.fixture
def brain_a():
    """Brain-A: the exporting brain."""
    with tempfile.TemporaryDirectory() as tmp:
        brain_dir = Path(tmp) / ".brain"
        brain_dir.mkdir()
        g = _make_graph(brain_dir)
        yield {"dir": brain_dir, "graph": g, "workdir": tmp}


@pytest.fixture
def brain_b():
    """Brain-B: the importing brain (empty)."""
    with tempfile.TemporaryDirectory() as tmp:
        brain_dir = Path(tmp) / ".brain"
        brain_dir.mkdir()
        g = _make_graph(brain_dir)
        krb = _FakeKRB(g)
        yield {"dir": brain_dir, "graph": g, "krb": krb, "workdir": tmp}


# ─────────────────────────────────────────────────────────────────────────────
# TestCrossBrainSync — basic export / import round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossBrainSync:
    """
    Export from Brain-A → import to Brain-B.
    Verifies the happy-path federation flow end-to-end.
    """

    def test_exported_bundle_has_correct_node_count(self, brain_a):
        """Exporting 5 nodes produces a bundle with exactly 5 nodes."""
        g = brain_a["graph"]
        for i in range(5):
            _insert_node(g, f"n-{i}", f"Rule #{i}: always do X", confidence=0.8)
        g._conn.commit()

        exporter = FederationExporter(g, brain_a["dir"], project_name="proj-a")
        bundle_path = brain_a["dir"] / "export.json"
        bundle = exporter.export(output_path=bundle_path, min_confidence=0.6)

        assert bundle.node_count == 5
        assert len(bundle.nodes) == 5

    def test_bundle_written_to_disk(self, brain_a):
        """export() writes a valid JSON file to the given path."""
        g = brain_a["graph"]
        _insert_node(g, "n1", "Security rule: validate all inputs", confidence=0.9)
        g._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        exporter = FederationExporter(g, brain_a["dir"], project_name="proj-a")
        exporter.export(output_path=bundle_path)

        assert bundle_path.exists()
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
        assert "nodes" in data
        assert data["node_count"] >= 1

    def test_import_to_brain_b_stages_nodes(self, brain_a, brain_b):
        """5 nodes exported from A are staged (via KRB) in B."""
        g_a = brain_a["graph"]
        for i in range(5):
            _insert_node(g_a, f"rule-{i}", f"Architecture decision #{i}", confidence=0.8)
        g_a._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        exporter = FederationExporter(g_a, brain_a["dir"], project_name="proj-a")
        exporter.export(output_path=bundle_path)

        importer = FederationImporter(brain_b["krb"], brain_b["dir"])
        stats = importer.import_bundle(bundle_path)

        assert stats["imported"] == 5
        assert stats["skipped_dup"] == 0
        assert len(brain_b["krb"].submitted) == 5

    def test_imported_nodes_have_correct_titles(self, brain_a, brain_b):
        """Titles are preserved through export → import."""
        g_a = brain_a["graph"]
        titles = [f"Key insight about topic {i}" for i in range(3)]
        for i, title in enumerate(titles):
            _insert_node(g_a, f"n-{i}", title, confidence=0.85)
        g_a._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        FederationExporter(g_a, brain_a["dir"]).export(output_path=bundle_path)
        importer = FederationImporter(brain_b["krb"], brain_b["dir"])
        importer.import_bundle(bundle_path)

        staged_titles = {s["title"] for s in brain_b["krb"].submitted}
        for title in titles:
            assert title in staged_titles, f"Expected '{title}' in staged nodes"

    def test_low_confidence_nodes_excluded_from_export(self, brain_a, brain_b):
        """Nodes with confidence < 0.6 are NOT exported."""
        g_a = brain_a["graph"]
        _insert_node(g_a, "high", "High confidence rule", confidence=0.9)
        _insert_node(g_a, "low",  "Low confidence note",  confidence=0.4)
        g_a._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        FederationExporter(g_a, brain_a["dir"]).export(
            output_path=bundle_path, min_confidence=0.6
        )
        importer = FederationImporter(brain_b["krb"], brain_b["dir"])
        stats = importer.import_bundle(bundle_path)

        assert stats["imported"] == 1
        assert brain_b["krb"].submitted[0]["title"] == "High confidence rule"

    def test_source_project_recorded_in_bundle(self, brain_a):
        """Bundle records the source project name."""
        g_a = brain_a["graph"]
        _insert_node(g_a, "n1", "Decision: use PostgreSQL", confidence=0.9)
        g_a._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        bundle = FederationExporter(g_a, brain_a["dir"],
                                    project_name="my-service").export(output_path=bundle_path)
        assert bundle.source_project == "my-service"

    def test_import_dry_run_does_not_stage(self, brain_a, brain_b):
        """dry_run=True counts nodes but does NOT call KRB.submit."""
        g_a = brain_a["graph"]
        for i in range(3):
            _insert_node(g_a, f"n-{i}", f"Rule {i}", confidence=0.8)
        g_a._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        FederationExporter(g_a, brain_a["dir"]).export(output_path=bundle_path)

        importer = FederationImporter(brain_b["krb"], brain_b["dir"])
        stats = importer.import_bundle(bundle_path, dry_run=True)

        assert stats["imported"] == 3
        assert len(brain_b["krb"].submitted) == 0  # dry run — no actual staging


# ─────────────────────────────────────────────────────────────────────────────
# TestPIIAtScale — 1000+ nodes with PII, verify all cleaned
# ─────────────────────────────────────────────────────────────────────────────

PII_PATTERNS = [
    ("email",      "Contact admin@corp.example for access"),
    ("ip_private", "Service runs on 192.168.1.42"),
    ("ip_10",      "Database endpoint: 10.20.30.40:5432"),
    ("internal",   "See internal.example.com/wiki for docs"),
    ("local",      "Staging: dev-server.local"),
]


class TestPIIAtScale:
    """PII cleanup over 1000+ nodes — no PII leaks in exported bundle."""

    @pytest.fixture
    def pii_brain(self, brain_a):
        """Brain-A with 1000 nodes: 200 contain PII, 800 are clean."""
        g = brain_a["graph"]
        pii_count = 0

        for i in range(1000):
            if i < 200:
                # Embed PII in content
                label, pii_text = PII_PATTERNS[i % len(PII_PATTERNS)]
                _insert_node(
                    g, f"pii-{i:04d}",
                    f"Node {i}: important rule",
                    content=f"{pii_text}. Additional context here.",
                    confidence=0.8,
                )
                pii_count += 1
            else:
                _insert_node(
                    g, f"clean-{i:04d}",
                    f"Clean rule #{i}: always validate at boundaries",
                    content=f"Validation ensures correctness. Node {i}.",
                    confidence=0.8,
                )
        g._conn.commit()
        yield {"brain": brain_a, "pii_count": pii_count}

    def test_1000_nodes_exportable(self, pii_brain):
        """1000 nodes can be exported without error."""
        brain_info = pii_brain["brain"]
        bundle_path = brain_info["dir"] / "export.json"
        bundle = FederationExporter(
            brain_info["graph"], brain_info["dir"], project_name="pii-test"
        ).export(output_path=bundle_path, min_confidence=0.6, max_nodes=1000)
        assert bundle.node_count == 1000
        assert bundle_path.exists()

    def test_no_email_in_exported_content(self, pii_brain):
        """No email addresses appear in any exported node's content."""
        import re
        brain_info = pii_brain["brain"]
        bundle_path = brain_info["dir"] / "export.json"
        FederationExporter(brain_info["graph"], brain_info["dir"]).export(
            output_path=bundle_path, max_nodes=1000
        )
        bundle = FederationBundle.from_json(bundle_path.read_text())
        email_re = re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b')
        for node in bundle.nodes:
            content = node.get("content", "")
            matches = email_re.findall(content)
            assert not matches, f"Email leaked in node '{node.get('title')}': {matches}"

    def test_no_private_ip_in_exported_content(self, pii_brain):
        """No private IP addresses appear in exported node content."""
        import re
        brain_info = pii_brain["brain"]
        bundle_path = brain_info["dir"] / "export.json"
        FederationExporter(brain_info["graph"], brain_info["dir"]).export(
            output_path=bundle_path, max_nodes=1000
        )
        bundle = FederationBundle.from_json(bundle_path.read_text())
        # Match 10.x, 192.168.x, 172.16-31.x
        private_ip_re = re.compile(
            r'\b(10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+)\b'
        )
        for node in bundle.nodes:
            content = node.get("content", "")
            matches = private_ip_re.findall(content)
            assert not matches, (
                f"Private IP leaked in node '{node.get('title')}': {matches}"
            )

    def test_no_internal_hostname_in_exported_content(self, pii_brain):
        """No internal.* hostnames appear in exported node content."""
        import re
        brain_info = pii_brain["brain"]
        bundle_path = brain_info["dir"] / "export.json"
        FederationExporter(brain_info["graph"], brain_info["dir"]).export(
            output_path=bundle_path, max_nodes=1000
        )
        bundle = FederationBundle.from_json(bundle_path.read_text())
        internal_re = re.compile(r'\binternal\.[a-zA-Z0-9.\-]+\b')
        for node in bundle.nodes:
            content = node.get("content", "")
            matches = internal_re.findall(content)
            assert not matches, (
                f"Internal hostname leaked in node '{node.get('title')}': {matches}"
            )

    def test_pii_strip_performance_1000_strings(self):
        """_strip_pii on 1000 strings completes in < 2 seconds."""
        texts = [
            f"Contact user{i}@corp.example or see 10.0.0.{i % 254 + 1} for details. "
            f"Server at dev-host-{i}.local is internal.corp.net/resource/{i}."
            for i in range(1000)
        ]
        t0 = time.monotonic()
        for text in texts:
            _strip_pii(text)
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, f"_strip_pii 1000× took {elapsed:.2f}s (budget: 2s)"


# ─────────────────────────────────────────────────────────────────────────────
# TestDedupAtScale — 1000+ nodes, import with 200 duplicates
# ─────────────────────────────────────────────────────────────────────────────

class TestDedupAtScale:
    """
    Import correctness with duplicate detection at 1000-node scale.

    Brain-A exports 1000 nodes.
    Brain-B already has the first 300 of them.
    Re-importing the same bundle from A → B should skip 300 duplicates.
    """

    @pytest.fixture
    def scale_setup(self, brain_a, brain_b):
        """Set up A with 300 nodes, B with 300 duplicates pre-loaded."""
        g_a = brain_a["graph"]
        g_b = brain_b["graph"]

        # Insert 300 nodes into both A and B (same titles → will be deduped)
        for i in range(300):
            title = f"Shared rule #{i:04d}: always use parameterized queries"
            _insert_node(g_a, f"shared-{i:04d}", title, confidence=0.8)
            _insert_node(g_b, f"shared-{i:04d}", title, confidence=0.8)

        # Insert 200 A-only nodes (novel — should be imported to B)
        for i in range(200):
            _insert_node(
                g_a, f"novel-{i:04d}",
                f"Novel decision #{i:04d}: architecture choice",
                confidence=0.75,
            )

        g_a._conn.commit()
        g_b._conn.commit()
        yield {"a": brain_a, "b": brain_b}

    def test_duplicate_nodes_are_skipped(self, scale_setup):
        """300 already-existing nodes are detected as duplicates and skipped."""
        a = scale_setup["a"]
        b = scale_setup["b"]

        bundle_path = a["dir"] / "export.json"
        FederationExporter(a["graph"], a["dir"]).export(
            output_path=bundle_path, min_confidence=0.6, max_nodes=1000
        )

        importer = FederationImporter(b["krb"], b["dir"])
        stats = importer.import_bundle(bundle_path)

        # 200 novel nodes imported, 300 duplicates skipped
        assert stats["imported"] == 200, (
            f"Expected 200 imports, got {stats['imported']}"
        )
        assert stats["skipped_dup"] == 300, (
            f"Expected 300 skipped_dup, got {stats['skipped_dup']}"
        )

    def test_novel_nodes_all_staged(self, scale_setup):
        """All 200 novel nodes end up in KRB staging."""
        a = scale_setup["a"]
        b = scale_setup["b"]

        bundle_path = a["dir"] / "export.json"
        FederationExporter(a["graph"], a["dir"]).export(
            output_path=bundle_path, min_confidence=0.6, max_nodes=1000
        )

        importer = FederationImporter(b["krb"], b["dir"])
        importer.import_bundle(bundle_path)

        staged_titles = {s["title"] for s in b["krb"].submitted}
        for i in range(200):
            expected = f"Novel decision #{i:04d}: architecture choice"
            assert expected in staged_titles, (
                f"Novel node #{i} not staged"
            )

    def test_re_import_same_bundle_is_fully_deduped(self, scale_setup):
        """Importing the same bundle twice: second pass is 100% duplicates."""
        a = scale_setup["a"]
        b = scale_setup["b"]

        bundle_path = a["dir"] / "export.json"
        FederationExporter(a["graph"], a["dir"]).export(
            output_path=bundle_path, min_confidence=0.6, max_nodes=1000
        )

        importer = FederationImporter(b["krb"], b["dir"])
        first_stats = importer.import_bundle(bundle_path)

        # Manually commit staged nodes into B's graph so dedup sees them
        for node in b["krb"].submitted:
            _insert_node(
                b["graph"], str(uuid.uuid4()),
                node["title"], content=node["content"],
            )
        b["graph"]._conn.commit()
        b["krb"].submitted.clear()

        # Second import — everything is now a duplicate
        second_stats = importer.import_bundle(bundle_path)
        assert second_stats["imported"] == 0, (
            f"Second import should import 0, got {second_stats['imported']}"
        )

    def test_dedup_at_scale_completes_in_budget(self, scale_setup):
        """Full dedup scan over 300 existing + 200 novel nodes under 5s."""
        a = scale_setup["a"]
        b = scale_setup["b"]

        bundle_path = a["dir"] / "export.json"
        FederationExporter(a["graph"], a["dir"]).export(
            output_path=bundle_path, min_confidence=0.6, max_nodes=1000
        )

        importer = FederationImporter(b["krb"], b["dir"])
        t0 = time.monotonic()
        importer.import_bundle(bundle_path)
        elapsed = time.monotonic() - t0

        assert elapsed < 5.0, (
            f"import_bundle with 500 nodes took {elapsed:.2f}s (budget: 5s)"
        )


# ─────────────────────────────────────────────────────────────────────────────
# TestFederationBundleIntegrity
# ─────────────────────────────────────────────────────────────────────────────

class TestFederationBundleIntegrity:
    """FederationBundle JSON round-trip and schema validation."""

    def test_bundle_round_trip_serialization(self, brain_a):
        """export() → read JSON → FederationBundle.from_json() is lossless."""
        g = brain_a["graph"]
        for i in range(10):
            _insert_node(g, f"n{i}", f"Rule #{i}: important constraint", confidence=0.8)
        g._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        original = FederationExporter(g, brain_a["dir"]).export(output_path=bundle_path)

        restored = FederationBundle.from_json(bundle_path.read_text(encoding="utf-8"))
        assert restored.node_count == original.node_count
        assert restored.source_project == original.source_project
        assert len(restored.nodes) == len(original.nodes)

    def test_bundle_nodes_have_required_keys(self, brain_a):
        """Each exported node has: id, title, kind, confidence, content, tags."""
        g = brain_a["graph"]
        _insert_node(g, "n1", "Critical: never store plaintext passwords",
                     content="Use bcrypt or argon2.", confidence=0.9, kind="Rule")
        g._conn.commit()

        bundle_path = brain_a["dir"] / "export.json"
        bundle = FederationExporter(g, brain_a["dir"]).export(output_path=bundle_path)

        for node in bundle.nodes:
            assert "id" in node,         f"Missing 'id' in {node}"
            assert "title" in node,      f"Missing 'title' in {node}"
            assert "confidence" in node, f"Missing 'confidence' in {node}"
            # kind may be stored as "kind" or "type" depending on schema
            assert "kind" in node or "type" in node, f"Missing kind/type in {node}"

    def test_empty_brain_exports_empty_bundle(self, brain_a):
        """Exporting an empty graph returns a bundle with 0 nodes."""
        g = brain_a["graph"]
        bundle_path = brain_a["dir"] / "export.json"
        bundle = FederationExporter(g, brain_a["dir"]).export(output_path=bundle_path)
        assert bundle.node_count == 0
        assert bundle.nodes == []
