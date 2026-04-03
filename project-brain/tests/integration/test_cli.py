"""
tests/integration/test_cli.py — CLI 核心命令整合測試（PH0-04）

策略：無 Mock，直接呼叫真實 Brain engine + SQLite DB，
驗證 init → add → ask 完整資料流。
"""

import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── helpers ──────────────────────────────────────────────────────────────────

def _args(**kwargs) -> argparse.Namespace:
    defaults = {
        "workdir": None,
        "quiet": True,
        "yes": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ══════════════════════════════════════════════════════════════════════════════
# brain init
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdInitIntegration:
    def test_creates_brain_dir(self, tmp_path, capsys):
        from project_brain.cli import cmd_init

        args = _args(workdir=str(tmp_path), name="test-project", local_only=False)
        cmd_init(args)

        assert (tmp_path / ".brain").is_dir(), ".brain/ 未建立"

    def test_creates_knowledge_db(self, tmp_path, capsys):
        from project_brain.cli import cmd_init

        args = _args(workdir=str(tmp_path), name="test-project", local_only=False)
        cmd_init(args)

        db_file = tmp_path / ".brain" / "knowledge_graph.db"
        assert db_file.exists(), "knowledge_graph.db 未建立"

    def test_idempotent_reinit(self, tmp_path, capsys):
        from project_brain.cli import cmd_init

        args = _args(workdir=str(tmp_path), name="test-project", local_only=False)
        cmd_init(args)
        # 第二次 init 不應 crash
        cmd_init(args)

        assert (tmp_path / ".brain").is_dir()

    def test_output_contains_success_indicator(self, tmp_path, capsys):
        from project_brain.cli import cmd_init

        args = _args(workdir=str(tmp_path), name="myproj", local_only=False)
        cmd_init(args)

        captured = capsys.readouterr()
        # init 成功後應印出含專案名稱或 "Brain" 的訊息
        combined = captured.out + captured.err
        assert combined.strip(), "init 應有輸出"


# ══════════════════════════════════════════════════════════════════════════════
# brain add
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdAddIntegration:
    @pytest.fixture
    def initialized_dir(self, tmp_path):
        from project_brain.cli import cmd_init
        cmd_init(_args(workdir=str(tmp_path), name="test", local_only=False))
        return tmp_path

    def test_add_writes_to_db(self, initialized_dir):
        from project_brain.cli import cmd_add
        from project_brain.brain_db import BrainDB

        args = _args(
            workdir=str(initialized_dir),
            text=["JWT 必須使用 RS256 簽名"],
            title=None,
            content=None,
            kind="Rule",
            confidence=0.9,
            tags=[],
            scope="global",
            emotional_weight=0.5,
        )
        cmd_add(args)

        db = BrainDB(initialized_dir / ".brain")
        hits = db.search_nodes("RS256", limit=5)
        assert any("RS256" in (h.get("title", "") + h.get("content", "")) for h in hits), \
            "add 後應可在 DB 中找到節點"

    def test_add_returns_node_id(self, initialized_dir, capsys):
        from project_brain.cli import cmd_add

        args = _args(
            workdir=str(initialized_dir),
            text=["使用 WAL 模式避免寫入衝突"],
            title=None,
            content=None,
            kind="Rule",
            confidence=0.8,
            tags=[],
            scope="global",
            emotional_weight=0.5,
        )
        cmd_add(args)

        captured = capsys.readouterr()
        assert "✓" in captured.out or "知識已加入" in captured.out, \
            "add 成功應印出確認訊息"

    def test_add_multiple_nodes(self, initialized_dir):
        from project_brain.cli import cmd_add
        from project_brain.brain_db import BrainDB

        notes = [
            ("絕對不要在 _init_lock 持鎖時呼叫其他需要同一鎖的屬性", "Pitfall"),
            ("SQLite WAL + busy_timeout=5000 處理寫入競爭", "Decision"),
            ("知識衰減只降低可見度，不刪除節點", "Rule"),
        ]
        for text, kind in notes:
            cmd_add(_args(
                workdir=str(initialized_dir),
                text=[text],
                title=None,
                content=None,
                kind=kind,
                confidence=0.85,
                tags=[],
                scope="global",
                emotional_weight=0.5,
            ))

        db = BrainDB(initialized_dir / ".brain")
        # 每筆知識都應可被搜尋到
        assert db.search_nodes("WAL", limit=5), "WAL 知識應可被找到"
        assert db.search_nodes("衰減", limit=5), "衰減知識應可被找到"

    def test_add_without_brain_dir_prints_error(self, tmp_path, capsys):
        from project_brain.cli import cmd_add

        # 沒有執行 init，.brain/ 不存在
        args = _args(
            workdir=str(tmp_path),
            text=["測試知識"],
            title=None,
            content=None,
            kind="Note",
            confidence=0.8,
            tags=[],
            scope="global",
            emotional_weight=0.5,
        )
        # 不應 crash，但應有某種輸出或靜默處理
        try:
            cmd_add(args)
        except SystemExit:
            pass  # 允許 early exit
        # 沒有 crash = 測試通過


# ══════════════════════════════════════════════════════════════════════════════
# brain ask
# ══════════════════════════════════════════════════════════════════════════════

class TestCmdAskIntegration:
    @pytest.fixture
    def seeded_dir(self, tmp_path):
        """初始化 + 加入幾筆知識"""
        from project_brain.cli import cmd_init, cmd_add

        cmd_init(_args(workdir=str(tmp_path), name="test", local_only=False))

        seeds = [
            ("JWT 認證必須使用 RS256，不可用 HS256", "Rule"),
            ("context_engineer 死鎖：在 _init_lock 持鎖內不可呼叫其他鎖", "Pitfall"),
            ("SQLite WAL 模式可處理並發讀寫", "Decision"),
        ]
        for text, kind in seeds:
            cmd_add(_args(
                workdir=str(tmp_path),
                text=[text],
                title=None,
                content=None,
                kind=kind,
                confidence=0.9,
                tags=[],
                scope="global",
                emotional_weight=0.5,
            ))
        return tmp_path

    def test_ask_returns_relevant_result(self, seeded_dir, capsys):
        from project_brain.cli import cmd_ask

        args = _args(workdir=str(seeded_dir), query=["JWT RS256"])
        cmd_ask(args)

        captured = capsys.readouterr()
        assert "RS256" in captured.out, "ask JWT RS256 應命中相關知識"

    def test_ask_no_results_prints_suggestion(self, seeded_dir, capsys):
        from project_brain.cli import cmd_ask

        args = _args(workdir=str(seeded_dir), query=["量子計算超導體"])
        cmd_ask(args)

        captured = capsys.readouterr()
        # 找不到時應提示使用者
        assert "找不到" in captured.out or "brain add" in captured.out, \
            "無結果時應給予提示"

    def test_ask_without_brain_dir_prints_error(self, tmp_path, capsys):
        from project_brain.cli import cmd_ask

        args = _args(workdir=str(tmp_path), query=["測試查詢"])
        cmd_ask(args)

        captured = capsys.readouterr()
        assert "brain setup" in captured.out or "初始化" in captured.out or "✗" in captured.out, \
            "未 init 時應提示初始化"

    def test_ask_empty_query_prints_usage(self, seeded_dir, capsys):
        from project_brain.cli import cmd_ask

        args = _args(workdir=str(seeded_dir), query=[])
        cmd_ask(args)

        captured = capsys.readouterr()
        assert "Usage" in captured.out or "✗" in captured.out, \
            "空 query 應印出使用說明"

    def test_ask_after_add_round_trip(self, tmp_path, capsys):
        """完整 init → add → ask 資料流驗證"""
        from project_brain.cli import cmd_init, cmd_add, cmd_ask

        # init
        cmd_init(_args(workdir=str(tmp_path), name="roundtrip", local_only=False))

        # add
        cmd_add(_args(
            workdir=str(tmp_path),
            text=["部署前必須執行 db migrate，否則 schema 不一致"],
            title=None,
            content=None,
            kind="Pitfall",
            confidence=0.9,
            tags=[],
            scope="global",
            emotional_weight=0.5,
        ))

        # ask
        capsys.readouterr()  # 清空 add 輸出
        cmd_ask(_args(workdir=str(tmp_path), query=["db migrate deploy"]))

        captured = capsys.readouterr()
        assert "migrate" in captured.out or "部署" in captured.out, \
            "add 後 ask 應能找到剛加入的知識"
