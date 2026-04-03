"""
tests/integration/test_q2.py — Q2 新功能整合測試（PH1-04 / PH1-05 / PH1-06 / PH2-02）

無 Mock，直接呼叫真實 engine + SQLite DB。
"""

import argparse
import sys
import sqlite3
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── helpers ──────────────────────────────────────────────────────────────────

def _args(**kwargs) -> argparse.Namespace:
    defaults = {"workdir": None, "quiet": True, "yes": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.fixture
def seeded_dir(tmp_path):
    """init + 加入幾筆知識，供多個測試共用"""
    from project_brain.cli import cmd_init, cmd_add

    cmd_init(_args(workdir=str(tmp_path), name="test", local_only=False))
    seeds = [
        ("JWT 必須使用 RS256 簽名算法", "Rule"),
        ("_init_lock 持鎖時不可呼叫需要同一鎖的屬性，否則死鎖", "Pitfall"),
        ("SQLite WAL 模式可處理並發讀寫競爭", "Decision"),
    ]
    for text, kind in seeds:
        cmd_add(_args(
            workdir=str(tmp_path), text=[text], title=None, content=None,
            kind=kind, confidence=0.9, tags=[], scope="global", emotional_weight=0.5,
        ))
    return tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# PH1-04: KnowledgeExtractor.from_session_log()
# ══════════════════════════════════════════════════════════════════════════════

class TestFromSessionLog:
    def test_basic_extraction(self):
        from project_brain.extractor import KnowledgeExtractor
        ext = KnowledgeExtractor(".")
        result = ext.from_session_log(
            task_description="實作 JWT 認證模組",
            decisions=["選用 RS256 而非 HS256，因為 RS256 支援非對稱金鑰"],
            lessons=["PyJWT 的 decode() 預設不驗證 exp，需明確傳 options"],
            pitfalls=["HS256 在多服務環境中 secret 無法安全分享"],
        )
        assert "knowledge_chunks" in result
        chunks = result["knowledge_chunks"]
        assert len(chunks) == 3

    def test_decision_chunk_type(self):
        from project_brain.extractor import KnowledgeExtractor
        ext = KnowledgeExtractor(".")
        result = ext.from_session_log(
            task_description="測試任務",
            decisions=["選用 SQLite WAL 模式"],
            lessons=[],
            pitfalls=[],
        )
        chunk = result["knowledge_chunks"][0]
        assert chunk["type"] == "Decision"
        assert chunk["confidence"] == 0.85

    def test_pitfall_chunk_has_high_confidence(self):
        from project_brain.extractor import KnowledgeExtractor
        ext = KnowledgeExtractor(".")
        result = ext.from_session_log(
            task_description="測試任務",
            decisions=[],
            lessons=[],
            pitfalls=["在 _init_lock 內呼叫 context_engineer 屬性會造成死鎖"],
        )
        chunk = result["knowledge_chunks"][0]
        assert chunk["type"] == "Pitfall"
        assert chunk["confidence"] == 0.90  # pitfalls get highest confidence

    def test_lesson_chunk_type(self):
        from project_brain.extractor import KnowledgeExtractor
        ext = KnowledgeExtractor(".")
        result = ext.from_session_log(
            task_description="測試任務",
            decisions=[],
            lessons=["整合測試比 mock 測試更能發現真實問題"],
            pitfalls=[],
        )
        chunk = result["knowledge_chunks"][0]
        assert chunk["type"] == "Rule"

    def test_empty_inputs(self):
        from project_brain.extractor import KnowledgeExtractor
        ext = KnowledgeExtractor(".")
        result = ext.from_session_log(
            task_description="空任務",
            decisions=[], lessons=[], pitfalls=[],
        )
        assert result["knowledge_chunks"] == []

    def test_source_tag(self):
        from project_brain.extractor import KnowledgeExtractor
        ext = KnowledgeExtractor(".")
        result = ext.from_session_log(
            task_description="t",
            decisions=["d1"],
            lessons=[],
            pitfalls=[],
            source="session:2026-04-03",
        )
        assert result["knowledge_chunks"][0]["source"] == "session:2026-04-03"


# ══════════════════════════════════════════════════════════════════════════════
# PH1-05: AnalyticsEngine
# ══════════════════════════════════════════════════════════════════════════════

class TestAnalyticsEngine:
    @pytest.fixture
    def engine_conn(self, seeded_dir):
        bd = seeded_dir / ".brain"
        for name in ("brain.db", "knowledge_graph.db"):
            p = bd / name
            if p.exists():
                conn = sqlite3.connect(str(p))
                conn.row_factory = sqlite3.Row
                yield conn
                conn.close()
                return
        pytest.skip("找不到 brain.db")

    def test_roi_metrics_returns_dict(self, engine_conn):
        from project_brain.analytics_engine import AnalyticsEngine
        engine = AnalyticsEngine(engine_conn)
        metrics = engine.roi_metrics()
        assert isinstance(metrics, dict)
        assert "knowledge_roi_score" in metrics

    def test_roi_score_is_float(self, engine_conn):
        from project_brain.analytics_engine import AnalyticsEngine
        engine = AnalyticsEngine(engine_conn)
        score = engine.knowledge_roi_score()
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_generate_report_structure(self, engine_conn):
        from project_brain.analytics_engine import AnalyticsEngine
        engine = AnalyticsEngine(engine_conn)
        report = engine.generate_report(period_days=7)
        assert "roi" in report
        assert "usage" in report
        assert "summary" in report
        assert "generated_at" in report

    def test_usage_total_nodes_positive(self, engine_conn):
        from project_brain.analytics_engine import AnalyticsEngine
        engine = AnalyticsEngine(engine_conn)
        report = engine.generate_report()
        assert report["usage"]["total_nodes"] >= 3  # seeded_dir adds 3 nodes

    def test_pitfall_avoidance_none_when_no_access(self, engine_conn):
        from project_brain.analytics_engine import AnalyticsEngine
        engine = AnalyticsEngine(engine_conn)
        # No queries made → access_count = 0 → avoidance score = 0
        score = engine.pitfall_avoidance_score()
        assert score == 0.0 or score is None


# ══════════════════════════════════════════════════════════════════════════════
# PH1-06: brain report
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdReport:
    def test_report_text_output(self, seeded_dir, capsys):
        from project_brain.cli import cmd_report
        cmd_report(_args(workdir=str(seeded_dir), days=7, format="text", output=None))
        captured = capsys.readouterr()
        assert "Brain Report" in captured.out or "ROI" in captured.out

    def test_report_json_output(self, seeded_dir, capsys):
        from project_brain.cli import cmd_report
        import json
        cmd_report(_args(workdir=str(seeded_dir), days=7, format="json", output=None))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "roi" in data
        assert "usage" in data

    def test_report_save_to_file(self, seeded_dir, tmp_path):
        from project_brain.cli import cmd_report
        out = tmp_path / "report.json"
        cmd_report(_args(workdir=str(seeded_dir), days=7, format="json", output=str(out)))
        assert out.exists()
        import json
        data = json.loads(out.read_text())
        assert "roi" in data

    def test_report_without_brain_dir(self, tmp_path, capsys):
        from project_brain.cli import cmd_report
        cmd_report(_args(workdir=str(tmp_path), days=7, format="text", output=None))
        captured = capsys.readouterr()
        assert "✗" in captured.out or "初始化" in captured.out


# ══════════════════════════════════════════════════════════════════════════════
# PH2-02: brain search
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdSearch:
    def test_search_finds_seeded_node(self, seeded_dir, capsys):
        from project_brain.cli import cmd_search
        cmd_search(_args(
            workdir=str(seeded_dir), query=["JWT RS256"],
            limit=10, kind=None, scope=None, format="text",
        ))
        captured = capsys.readouterr()
        assert "RS256" in captured.out

    def test_search_no_results_prints_hint(self, seeded_dir, capsys):
        from project_brain.cli import cmd_search
        cmd_search(_args(
            workdir=str(seeded_dir), query=["量子糾纏超導體"],
            limit=10, kind=None, scope=None, format="text",
        ))
        captured = capsys.readouterr()
        assert "找不到" in captured.out or "brain add" in captured.out

    def test_search_json_format(self, seeded_dir, capsys):
        from project_brain.cli import cmd_search
        import json
        cmd_search(_args(
            workdir=str(seeded_dir), query=["WAL SQLite"],
            limit=10, kind=None, scope=None, format="json",
        ))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)

    def test_search_empty_query_prints_error(self, seeded_dir, capsys):
        from project_brain.cli import cmd_search
        cmd_search(_args(
            workdir=str(seeded_dir), query=[],
            limit=10, kind=None, scope=None, format="text",
        ))
        captured = capsys.readouterr()
        assert "✗" in captured.out or "Usage" in captured.out

    def test_search_without_brain_dir(self, tmp_path, capsys):
        from project_brain.cli import cmd_search
        cmd_search(_args(
            workdir=str(tmp_path), query=["test"],
            limit=10, kind=None, scope=None, format="text",
        ))
        captured = capsys.readouterr()
        assert "✗" in captured.out
