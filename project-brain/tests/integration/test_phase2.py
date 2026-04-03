"""
tests/integration/test_phase2.py — Phase 2 剩餘項目整合測試
PH2-03 / PH2-04 / PH2-05 / PH2-06 / PH2-07
無 Mock，直接呼叫真實 engine + SQLite DB。
"""

import argparse
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _args(**kwargs) -> argparse.Namespace:
    defaults = {"workdir": None, "quiet": True, "yes": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


@pytest.fixture
def seeded_dir(tmp_path):
    from project_brain.cli import cmd_init, cmd_add
    cmd_init(_args(workdir=str(tmp_path), name="test", local_only=False))
    cmd_add(_args(
        workdir=str(tmp_path), text=["RS256 簽名算法必須使用"],
        title=None, content=None, kind="Rule",
        confidence=0.9, tags=[], scope="global", emotional_weight=0.5,
    ))
    cmd_add(_args(
        workdir=str(tmp_path), text=["WAL 模式避免寫入競爭"],
        title=None, content=None, kind="Decision",
        confidence=0.85, tags=[], scope="global", emotional_weight=0.5,
    ))
    return tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# PH2-03: brain add 互動模式
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdAddInteractive:
    def test_interactive_mode_triggered_when_no_args(self, seeded_dir, capsys):
        """無 text/title 時應觸發互動模式，而非報錯"""
        from project_brain.cli import cmd_add
        # 模擬使用者輸入：內容 / 選 Pitfall / scope global / confidence 0.9
        inputs = iter(["部署前必須跑 db migrate", "1", "global", "0.9"])
        with patch("builtins.input", side_effect=inputs):
            cmd_add(_args(workdir=str(seeded_dir), text=[], title=None,
                          content=None, kind=None, confidence=None,
                          tags=[], scope=None, emotional_weight=0.5))
        captured = capsys.readouterr()
        assert "✓" in captured.out or "知識已加入" in captured.out

    def test_interactive_writes_to_db(self, seeded_dir):
        from project_brain.cli import cmd_add
        from project_brain.brain_db import BrainDB
        inputs = iter(["互動模式測試知識節點", "2", "", ""])  # kind=Rule
        with patch("builtins.input", side_effect=inputs):
            cmd_add(_args(workdir=str(seeded_dir), text=[], title=None,
                          content=None, kind=None, confidence=None,
                          tags=[], scope=None, emotional_weight=0.5))
        db = BrainDB(seeded_dir / ".brain")
        hits = db.search_nodes("互動模式測試", limit=5)
        assert any("互動" in (h.get("title", "") + h.get("content", "")) for h in hits)

    def test_interactive_cancel_on_empty_content(self, seeded_dir, capsys):
        """空內容應中止，不崩潰"""
        from project_brain.cli import cmd_add
        with patch("builtins.input", return_value=""):
            cmd_add(_args(workdir=str(seeded_dir), text=[], title=None,
                          content=None, kind=None, confidence=None,
                          tags=[], scope=None, emotional_weight=0.5))
        captured = capsys.readouterr()
        assert "✓" not in captured.out  # should not have added anything


# ══════════════════════════════════════════════════════════════════════════════
# PH2-04: brain export --format markdown（已存在，驗證正常運作）
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdExportMarkdown:
    def test_export_markdown_creates_file(self, seeded_dir, tmp_path):
        from project_brain.cli import cmd_export
        out = tmp_path / "export.md"
        cmd_export(_args(workdir=str(seeded_dir), format="markdown",
                         kind=None, scope=None, output=str(out)))
        assert out.exists()
        content = out.read_text()
        assert "# Project Brain" in content or "##" in content

    def test_export_markdown_contains_nodes(self, seeded_dir, tmp_path):
        from project_brain.cli import cmd_export
        out = tmp_path / "export.md"
        cmd_export(_args(workdir=str(seeded_dir), format="markdown",
                         kind=None, scope=None, output=str(out)))
        content = out.read_text()
        assert "RS256" in content or "WAL" in content


# ══════════════════════════════════════════════════════════════════════════════
# PH2-05: synonyms.json 同義詞設定檔
# ══════════════════════════════════════════════════════════════════════════════

class TestSynonymsJson:
    def test_init_creates_synonyms_file(self, tmp_path):
        from project_brain.cli import cmd_init
        cmd_init(_args(workdir=str(tmp_path), name="test", local_only=False))
        assert (tmp_path / ".brain" / "synonyms.json").exists()

    def test_synonyms_file_is_valid_json(self, tmp_path):
        from project_brain.cli import cmd_init
        cmd_init(_args(workdir=str(tmp_path), name="test", local_only=False))
        data = json.loads((tmp_path / ".brain" / "synonyms.json").read_text())
        assert isinstance(data, dict)

    def test_custom_synonyms_merged(self, seeded_dir):
        """自訂 synonyms.json 的詞應被 ContextEngineer 載入"""
        # 寫入自訂同義詞
        syn_path = seeded_dir / ".brain" / "synonyms.json"
        syn_path.write_text(json.dumps({"自訂測試詞": ["custom_alias_xyz"]}), encoding="utf-8")

        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer
        graph = KnowledgeGraph(seeded_dir / ".brain")
        ce = ContextEngineer(graph, brain_dir=seeded_dir / ".brain")

        # 自訂詞應在 _SYNONYM_MAP 中
        assert "自訂測試詞" in ce._SYNONYM_MAP
        assert "custom_alias_xyz" in ce._SYNONYM_MAP["自訂測試詞"]

    def test_builtin_synonyms_still_present(self, seeded_dir):
        """載入自訂後，內建同義詞仍存在"""
        syn_path = seeded_dir / ".brain" / "synonyms.json"
        syn_path.write_text(json.dumps({"新詞": ["alias"]}), encoding="utf-8")

        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer
        graph = KnowledgeGraph(seeded_dir / ".brain")
        ce = ContextEngineer(graph, brain_dir=seeded_dir / ".brain")

        # 內建 jwt 同義詞應仍存在
        assert "jwt" in ce._SYNONYM_MAP

    def test_invalid_synonyms_json_falls_back(self, seeded_dir):
        """損壞的 synonyms.json 應靜默降級，不 crash"""
        syn_path = seeded_dir / ".brain" / "synonyms.json"
        syn_path.write_text("NOT VALID JSON {{{", encoding="utf-8")

        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer
        graph = KnowledgeGraph(seeded_dir / ".brain")
        ce = ContextEngineer(graph, brain_dir=seeded_dir / ".brain")
        # 內建同義詞仍應可用
        assert "jwt" in ce._SYNONYM_MAP


# ══════════════════════════════════════════════════════════════════════════════
# PH2-06: brain link-issue
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdLinkIssue:
    def _get_node_id(self, seeded_dir):
        from project_brain.brain_db import BrainDB
        db = BrainDB(seeded_dir / ".brain")
        rows = db.conn.execute("SELECT id FROM nodes LIMIT 1").fetchone()
        return rows[0] if rows else None

    def test_link_issue_stores_event(self, seeded_dir, capsys):
        from project_brain.cli import cmd_link_issue
        from project_brain.brain_db import BrainDB
        node_id = self._get_node_id(seeded_dir)
        assert node_id, "seeded_dir 應有節點"

        cmd_link_issue(_args(
            workdir=str(seeded_dir),
            node_id=node_id,
            url="https://github.com/org/repo/issues/42",
            list=False,
        ))
        captured = capsys.readouterr()
        assert "✓" in captured.out

        db = BrainDB(seeded_dir / ".brain")
        events = db.recent_events(event_type="issue_link", limit=5)
        assert len(events) >= 1

    def test_link_issue_list_shows_linked(self, seeded_dir, capsys):
        from project_brain.cli import cmd_link_issue
        node_id = self._get_node_id(seeded_dir)

        cmd_link_issue(_args(
            workdir=str(seeded_dir), node_id=node_id,
            url="https://github.com/org/repo/issues/99", list=False,
        ))
        capsys.readouterr()

        cmd_link_issue(_args(workdir=str(seeded_dir), node_id=None,
                             url=None, list=True))
        captured = capsys.readouterr()
        assert "issues/99" in captured.out

    def test_link_issue_missing_node_id_errors(self, seeded_dir, capsys):
        from project_brain.cli import cmd_link_issue
        cmd_link_issue(_args(workdir=str(seeded_dir), node_id=None,
                             url="https://github.com/x/y/issues/1", list=False))
        captured = capsys.readouterr()
        assert "✗" in captured.out

    def test_link_issue_missing_url_errors(self, seeded_dir, capsys):
        from project_brain.cli import cmd_link_issue
        node_id = self._get_node_id(seeded_dir)
        cmd_link_issue(_args(workdir=str(seeded_dir), node_id=node_id,
                             url=None, list=False))
        captured = capsys.readouterr()
        assert "✗" in captured.out


# ══════════════════════════════════════════════════════════════════════════════
# PH2-07: brain ask --json
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdAskJson:
    def test_ask_json_returns_valid_json(self, seeded_dir, capsys):
        from project_brain.cli import cmd_ask
        cmd_ask(_args(workdir=str(seeded_dir), query=["RS256"], json=True))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)

    def test_ask_json_contains_node_fields(self, seeded_dir, capsys):
        from project_brain.cli import cmd_ask
        cmd_ask(_args(workdir=str(seeded_dir), query=["RS256"], json=True))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        if data:
            assert "title" in data[0]
            assert "id" in data[0]

    def test_ask_json_no_results_returns_empty_list(self, seeded_dir, capsys):
        from project_brain.cli import cmd_ask
        cmd_ask(_args(workdir=str(seeded_dir), query=["量子糾纏超導體12345"], json=True))
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data == []

    def test_ask_text_mode_still_works(self, seeded_dir, capsys):
        """--json=False 仍應輸出文字格式"""
        from project_brain.cli import cmd_ask
        cmd_ask(_args(workdir=str(seeded_dir), query=["RS256"], json=False))
        captured = capsys.readouterr()
        assert "Brain Ask" in captured.out or "RS256" in captured.out
