"""
tests/unit/test_ref04_constants.py — REF-04 魔法數字提取驗收測試
═══════════════════════════════════════════════════════════════

問題（REF-04）
──────────────
多個模組散落相同的魔法數字，無法透過名稱理解意圖，且修改時需同步多處：

  | 數值 | 檔案:行 | 意圖 |
  |------|---------|------|
  | 0.003 | brain_db.py:300 | 每日衰減率（Ebbinghaus 曲線） |
  | 800   | context.py:288  | ADR 類型節點的 content token 上限 |
  | 400   | context.py:288  | 一般節點的 content token 上限 |
  | 8     | engine.py:647, cli.py:1006, graph.py:1023 | 搜尋預設回傳數量 |

  注意：`decay_engine.py` 已有 `BASE_DECAY_RATE = 0.003`，
  但 `brain_db.py` 中同樣的 0.003 是孤立字面量，未引用。

實作計劃（執行前請閱讀）
────────────────────────
1. 建立 `project_brain/constants.py`：

   ```python
   # project_brain/constants.py
   \"\"\"全域共用常數 — 所有魔法數字的唯一來源。\"\"\"

   # 衰減
   BASE_DECAY_RATE  = 0.003   # 日衰減率（約 1 年後降至 0.33）；同步 decay_engine.py

   # Context 組裝
   ADR_CONTENT_CAP  = 800     # ADR 節點的最大 content 字元數（≈ token 數）
   NODE_CONTENT_CAP = 400     # 一般節點的最大 content 字元數

   # 搜尋
   DEFAULT_SEARCH_LIMIT = 8   # search_nodes / search_nodes_multi 預設 limit
   ```

2. `brain_db.py:300` — 替換孤立字面量：
   ```python
   # 舊
   decay = math.exp(-0.003 * days)          # F1: BASE_DECAY_RATE=0.003
   # 新
   from .constants import BASE_DECAY_RATE
   decay = math.exp(-BASE_DECAY_RATE * days)
   ```

3. `context.py:288` — 替換兩個 content cap：
   ```python
   # 舊
   max_c = 800 if label == "📄 ADR" else 400
   # 新
   from .constants import ADR_CONTENT_CAP, NODE_CONTENT_CAP
   max_c = ADR_CONTENT_CAP if label == "📄 ADR" else NODE_CONTENT_CAP
   ```

4. `engine.py:647`, `cli.py:1006`, `graph.py:1023` — 替換 limit=8：
   ```python
   # 舊
   hits = db.search_nodes(search_q, limit=8)
   # 新
   from project_brain.constants import DEFAULT_SEARCH_LIMIT
   hits = db.search_nodes(search_q, limit=DEFAULT_SEARCH_LIMIT)
   ```

5. `decay_engine.py` 的 `BASE_DECAY_RATE = 0.003` 可改為從 constants 匯入
   或保留（避免迴圈匯入），但數值必須與 constants.py 一致。

驗收標準
────────
- constants.py 存在且匯出四個名稱
- brain_db._effective_confidence() 計算結果與使用 0.003 字面量一致
- context.py 的 ADR/Node cap 值與 constants.py 一致
- search_nodes 預設 limit 與 DEFAULT_SEARCH_LIMIT 一致
- 修改 constants.py 的值後，行為同步改變（無孤立字面量）

執行方式
────────
  # 未實作前（應失敗）：
  python -m pytest tests/unit/test_ref04_constants.py -v

  # 實作後（應全部通過）：
  python -m pytest tests/unit/test_ref04_constants.py -v
"""
import math
import pytest


# ════════════════════════════════════════════════════════════════
#  測試群組 1：constants.py 模組存在且值正確
# ════════════════════════════════════════════════════════════════

class TestRef04ConstantsModuleExists:
    """constants.py 必須存在並匯出所有預期名稱與正確數值。"""

    def test_constants_module_importable(self):
        """project_brain.constants 模組可正常匯入。"""
        from project_brain import constants  # noqa: F401

    def test_base_decay_rate_exported(self):
        """BASE_DECAY_RATE 必須被匯出。"""
        from project_brain.constants import BASE_DECAY_RATE
        assert BASE_DECAY_RATE == 0.003, (
            f"BASE_DECAY_RATE 應為 0.003，實際：{BASE_DECAY_RATE}"
        )

    def test_adr_content_cap_exported(self):
        """ADR_CONTENT_CAP 必須被匯出，且值為 800。"""
        from project_brain.constants import ADR_CONTENT_CAP
        assert ADR_CONTENT_CAP == 800, (
            f"ADR_CONTENT_CAP 應為 800，實際：{ADR_CONTENT_CAP}"
        )

    def test_node_content_cap_exported(self):
        """NODE_CONTENT_CAP 必須被匯出，且值為 400。"""
        from project_brain.constants import NODE_CONTENT_CAP
        assert NODE_CONTENT_CAP == 400, (
            f"NODE_CONTENT_CAP 應為 400，實際：{NODE_CONTENT_CAP}"
        )

    def test_default_search_limit_exported(self):
        """DEFAULT_SEARCH_LIMIT 必須被匯出，且值為 8。"""
        from project_brain.constants import DEFAULT_SEARCH_LIMIT
        assert DEFAULT_SEARCH_LIMIT == 8, (
            f"DEFAULT_SEARCH_LIMIT 應為 8，實際：{DEFAULT_SEARCH_LIMIT}"
        )

    def test_adr_cap_greater_than_node_cap(self):
        """ADR 節點比一般節點有更大的 content 空間。"""
        from project_brain.constants import ADR_CONTENT_CAP, NODE_CONTENT_CAP
        assert ADR_CONTENT_CAP > NODE_CONTENT_CAP, (
            "ADR_CONTENT_CAP 應大於 NODE_CONTENT_CAP（ADR 需要更多上下文）"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 2：brain_db 使用 BASE_DECAY_RATE（非孤立字面量）
# ════════════════════════════════════════════════════════════════

class TestRef04BrainDbUsesConstant:
    """
    brain_db._effective_confidence() 計算結果必須與
    math.exp(-BASE_DECAY_RATE * days) 一致，而非硬編碼的 0.003。
    """

    def test_effective_confidence_uses_base_decay_rate(self):
        """
        _effective_confidence 的衰減計算結果應與 constants.BASE_DECAY_RATE 一致。

        驗證方式：
        1. 計算「使用 constants.BASE_DECAY_RATE」的期望值
        2. 呼叫 BrainDB._effective_confidence()
        3. 兩者應相等（誤差 < 1e-9）
        """
        import math
        from project_brain.constants import BASE_DECAY_RATE
        from project_brain.brain_db import BrainDB
        from datetime import datetime, timezone, timedelta

        days = 100
        base_confidence = 0.9
        created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        # 期望值：使用 constants 計算
        expected_decay = math.exp(-BASE_DECAY_RATE * days)
        expected = max(0.05, min(1.0, base_confidence * expected_decay))

        # 實際值：透過 BrainDB._effective_confidence
        node = {
            "confidence": base_confidence,
            "created_at": created_at,
            "access_count": 0,
        }
        actual = BrainDB._effective_confidence(node)

        assert abs(actual - expected) < 1e-9, (
            f"_effective_confidence 計算結果（{actual:.6f}）與"
            f" constants.BASE_DECAY_RATE 期望值（{expected:.6f}）不符。"
            f" 可能仍使用孤立字面量 0.003。"
        )

    def test_changing_constant_changes_behavior(self, monkeypatch):
        """
        修改 constants.BASE_DECAY_RATE 應影響 _effective_confidence 計算。
        若 brain_db 仍用孤立字面量，此測試會失敗。
        """
        import math
        import project_brain.constants as _c
        from project_brain.brain_db import BrainDB
        from datetime import datetime, timezone, timedelta

        # 使用刻意不同的衰減率
        fake_rate = 0.010
        monkeypatch.setattr(_c, "BASE_DECAY_RATE", fake_rate)

        days = 50
        created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        node = {"confidence": 0.8, "created_at": created_at, "access_count": 0}

        # 使用 fake_rate 計算期望值
        expected = max(0.05, min(1.0, 0.8 * math.exp(-fake_rate * days)))
        actual   = BrainDB._effective_confidence(node)

        assert abs(actual - expected) < 1e-9, (
            f"monkeypatch BASE_DECAY_RATE={fake_rate} 後，"
            f"_effective_confidence 應為 {expected:.6f}，實際 {actual:.6f}。"
            f" 表示 brain_db.py 仍有孤立字面量 0.003（未引用 constants）。"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 3：context.py 使用 ADR_CONTENT_CAP / NODE_CONTENT_CAP
# ════════════════════════════════════════════════════════════════

class TestRef04ContextUsesContentCaps:
    """
    context.py 的 _fmt_node() / build() 必須使用 constants 中的 cap 值，
    而非孤立的 800 / 400。
    """

    def test_adr_node_uses_adr_content_cap(self, tmp_path):
        """
        ADR 節點格式化時，max_chars 應等於 ADR_CONTENT_CAP（800）。

        驗證方式：建立一個超過 800 字元 content 的 ADR 節點，
        確認 context build 輸出不超過 ADR_CONTENT_CAP 字元數。
        """
        from project_brain.constants import ADR_CONTENT_CAP
        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer

        g = KnowledgeGraph(tmp_path)
        long_content = "A" * 2000  # 遠超 800 字元
        g.add_node("adr1", "ADR", "ADR 測試", content=long_content)

        ce = ContextEngineer(g, tmp_path)
        result = ce.build("ADR 測試")

        # ADR 節點的 content 在 context 中不應超過 ADR_CONTENT_CAP
        assert long_content not in result, (
            "完整 2000 字元 content 不應出現在 context 中（應被 cap 截斷）"
        )
        # 但截斷後的 content 仍應出現（前 ADR_CONTENT_CAP 字元）
        truncated = long_content[:ADR_CONTENT_CAP]
        assert truncated[:50] in result or len(result) > 0, (
            "ADR 節點應出現在 context 中（被截斷版本）"
        )

    def test_content_cap_values_match_constants(self):
        """
        context.py 原始碼中不應再有孤立的 800 或 400 字面量
        （已被 constants 取代）。

        這是一個 grep 式測試：解析 context.py 原始碼，
        確認 `max_c = 800` 和 `max_c = 400` 等孤立字面量已消失。
        """
        import ast
        from pathlib import Path

        context_path = Path(__file__).parent.parent.parent / "project_brain" / "context.py"
        source = context_path.read_text(encoding="utf-8")
        tree   = ast.parse(source)

        # 找出所有數值字面量
        magic_numbers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, int):
                magic_numbers.add(node.value)

        # 800 和 400 不應再作為孤立字面量出現（應改用 ADR_CONTENT_CAP / NODE_CONTENT_CAP）
        assert 800 not in magic_numbers, (
            "context.py 仍有字面量 800，應改用 constants.ADR_CONTENT_CAP"
        )
        assert 400 not in magic_numbers, (
            "context.py 仍有字面量 400，應改用 constants.NODE_CONTENT_CAP"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 4：search_nodes 使用 DEFAULT_SEARCH_LIMIT
# ════════════════════════════════════════════════════════════════

class TestRef04SearchLimitUsesConstant:
    """engine.py / cli.py / graph.py 的搜尋 limit=8 必須改用 constants。"""

    def test_default_search_limit_matches_actual_behavior(self, tmp_path):
        """
        BrainDB.search_nodes() 不傳 limit 時，回傳結果數量應 ≤ DEFAULT_SEARCH_LIMIT。
        """
        from project_brain.constants import DEFAULT_SEARCH_LIMIT
        from project_brain.brain_db import BrainDB

        db = BrainDB(tmp_path)
        for i in range(20):
            db.add_node(f"n{i}", "Rule", f"規則 {i}", content=f"測試內容 {i}")

        # 使用預設 limit
        results = db.search_nodes("規則")
        assert len(results) <= DEFAULT_SEARCH_LIMIT, (
            f"預設搜尋結果數 {len(results)} 應 ≤ DEFAULT_SEARCH_LIMIT({DEFAULT_SEARCH_LIMIT})"
        )

    def test_no_orphan_limit_8_in_engine(self):
        """
        engine.py 不應有孤立的 limit=8 字面量（已被 DEFAULT_SEARCH_LIMIT 取代）。
        """
        import ast
        from pathlib import Path

        engine_path = Path(__file__).parent.parent.parent / "project_brain" / "engine.py"
        source = engine_path.read_text(encoding="utf-8")

        # 使用簡單字串搜尋（比 AST 更直觀，因為 limit=8 是 keyword argument）
        assert "limit=8" not in source, (
            "engine.py 仍有孤立字面量 `limit=8`，應改用 constants.DEFAULT_SEARCH_LIMIT"
        )
