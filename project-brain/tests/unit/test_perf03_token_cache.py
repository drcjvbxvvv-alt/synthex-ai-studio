"""
tests/unit/test_perf03_token_cache.py — _count_tokens 驗收測試
═══════════════════════════════════════════════════════════════

歷史：
  PERF-03 (v0.33)  加入 @lru_cache(maxsize=1024)
  B-06    (v0.35)  移除 @lru_cache — 5000+ 節點命中率 < 20%，
                   改為確定性 O(n) 估算，無 cache 管理成本

驗收標準（B-06）：
  - _count_tokens 無 @lru_cache decorator（無 cache_info 屬性）
  - 結果與舊實作誤差 < 20%
  - 空字串 → 0
  - 純 CJK → ~1 token/char
  - 純 ASCII → ~1 token/4 chars
  - 混合文字 → 分段計算
  - 相同輸入永遠相同輸出（確定性）
  - context.py 相關測試全通過
"""
from __future__ import annotations

import pytest


def _fn():
    """取得 _count_tokens callable。"""
    from project_brain import context as ctx_module
    fn = getattr(ctx_module, "_count_tokens", None)
    if fn is None:
        fn = getattr(ctx_module.ContextEngineer, "_count_tokens", None)
    if fn is None:
        raise AttributeError(
            "_count_tokens 不存在於 project_brain.context 或 ContextEngineer"
        )
    return fn


# ════════════════════════════════════════════════════════════════
#  Group 1：LRU cache 已移除
# ════════════════════════════════════════════════════════════════


class TestB06CacheRemoved:
    """B-06: _count_tokens 不應有 @lru_cache decorator。"""

    def test_no_cache_info_attribute(self):
        """確認 cache_info() 不存在（已移除 decorator）。"""
        fn = _fn()
        assert not hasattr(fn, "cache_info"), (
            "_count_tokens 仍有 cache_info — @lru_cache 尚未移除"
        )

    def test_no_cache_clear_attribute(self):
        """確認 cache_clear() 不存在。"""
        fn = _fn()
        assert not hasattr(fn, "cache_clear"), (
            "_count_tokens 仍有 cache_clear — @lru_cache 尚未移除"
        )

    def test_no_wrapped_attribute(self):
        """確認 __wrapped__ 不存在。"""
        fn = _fn()
        assert not hasattr(fn, "__wrapped__"), (
            "_count_tokens 仍有 __wrapped__ — @lru_cache 尚未移除"
        )


# ════════════════════════════════════════════════════════════════
#  Group 2：確定性（Determinism）
# ════════════════════════════════════════════════════════════════


class TestB06Determinism:
    """相同輸入永遠相同輸出（不依賴快取狀態）。"""

    def test_same_input_same_output(self):
        fn = _fn()
        text = "Project Brain 知識管理系統 — 確定性測試"
        results = [fn(text) for _ in range(10)]
        assert len(set(results)) == 1, f"結果不穩定：{results}"

    def test_order_independent(self):
        """呼叫順序不影響結果。"""
        fn = _fn()
        a = fn("hello")
        fn("unrelated text 不相關文字")
        b = fn("hello")
        assert a == b


# ════════════════════════════════════════════════════════════════
#  Group 3：空字串
# ════════════════════════════════════════════════════════════════


class TestB06EmptyString:
    """空字串必須回傳 0。"""

    def test_empty_returns_zero(self):
        assert _fn()("") == 0

    def test_empty_is_int(self):
        assert isinstance(_fn()(""), int)


# ════════════════════════════════════════════════════════════════
#  Group 4：純 CJK
# ════════════════════════════════════════════════════════════════


class TestB06PureCJK:
    """CJK ideographs: ~1 token per character。"""

    def test_four_cjk_chars(self):
        """'你好世界'（4 chars）→ 4 tokens。"""
        assert _fn()("你好世界") == 4

    def test_100_cjk_chars(self):
        """100 個 CJK 字 → 100 tokens。"""
        assert _fn()("中" * 100) == 100

    def test_cjk_extension_a(self):
        """CJK Extension A (U+3400-U+4DBF) 也算 CJK。"""
        fn = _fn()
        # U+3400 is the first char in CJK Extension A
        assert fn("\u3400") == 1

    def test_cjk_compatibility_ideographs(self):
        """CJK Compatibility Ideographs (U+F900-U+FAFF) 也算 CJK。"""
        fn = _fn()
        # U+F900 is the first char in CJK Compatibility Ideographs
        assert fn("\uf900") == 1


# ════════════════════════════════════════════════════════════════
#  Group 5：純 ASCII
# ════════════════════════════════════════════════════════════════


class TestB06PureASCII:
    """ASCII: ~1 token per 4 characters, minimum 1 for non-empty。"""

    def test_hello_world(self):
        """'hello world'（11 chars）→ max(1, 11//4) = max(1, 2) = 2。"""
        assert _fn()("hello world") == 2

    def test_short_ascii(self):
        """'hi'（2 chars）→ max(1, 2//4) = max(1, 0) = 1。"""
        assert _fn()("hi") == 1

    def test_single_char(self):
        """'a'（1 char）→ max(1, 1//4) = 1。"""
        assert _fn()("a") == 1

    def test_100_ascii_chars(self):
        """100 ASCII chars → max(1, 100//4) = 25。"""
        assert _fn()("a" * 100) == 25

    def test_four_ascii_chars(self):
        """4 chars → max(1, 4//4) = 1。"""
        assert _fn()("abcd") == 1


# ════════════════════════════════════════════════════════════════
#  Group 6：混合文字
# ════════════════════════════════════════════════════════════════


class TestB06Mixed:
    """Mixed CJK + ASCII: tokens = cjk_count + ascii_count // 4。"""

    def test_hello_nihao(self):
        """'Hello 你好'（6 ASCII + 2 CJK = 8 chars）→ 2 + max(1, 6//4) = 2 + 1 = 3。"""
        assert _fn()("Hello 你好") == 3

    def test_cjk_more_than_ascii(self):
        """CJK 部分始終 >= 同長度 ASCII 部分的 token 數。"""
        fn = _fn()
        assert fn("中" * 10) >= fn("a" * 10)


# ════════════════════════════════════════════════════════════════
#  Group 7：邊界值與特殊字元
# ════════════════════════════════════════════════════════════════


class TestB06EdgeCases:
    """特殊字元與邊界情況。"""

    def test_whitespace_only(self):
        """純空白 → 非零（按 ASCII 規則計算）。"""
        fn = _fn()
        assert fn("    ") >= 1  # 4 spaces → max(1, 4//4) = 1

    def test_newlines(self):
        fn = _fn()
        result = fn("\n\n\n\n")
        assert result >= 1

    def test_emoji(self):
        """Emoji 按 non-CJK 規則計算。"""
        fn = _fn()
        result = fn("🧠💡🔥")
        assert result >= 1

    def test_fullwidth_ascii(self):
        """全形英文 (U+FF00-U+FFEF) 不再算 CJK（B-06 修正）。"""
        fn = _fn()
        # 全形 "Ｈ" (U+FF28) — 不在 CJK ideograph 範圍內
        result = fn("Ｈ")
        assert result >= 1

    def test_very_long_text(self):
        """10000 字元的長文字。"""
        fn = _fn()
        text = ("Project Brain 知識管理 " * 500)[:10000]
        result = fn(text)
        assert result > 0
        # 確定性
        assert fn(text) == result

    def test_unicode_stability(self):
        """各種 Unicode 字元結果穩定。"""
        fn = _fn()
        cases = [
            "\n\t\r",
            "🧠💡🔥",
            "Ｈｅｌｌｏ",
            "\u200b" * 10,
        ]
        for text in cases:
            r1 = fn(text)
            r2 = fn(text)
            assert r1 == r2, f"不穩定: {text!r} → {r1} vs {r2}"


# ════════════════════════════════════════════════════════════════
#  Group 8：與舊實作的誤差 < 20%
# ════════════════════════════════════════════════════════════════


class TestB06BackwardCompat:
    """新實作與舊實作（移除 cache 前）結果接近。"""

    @staticmethod
    def _old_count_tokens(text: str) -> int:
        """舊實作的純計算邏輯（不含 cache）。"""
        cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff'
                  or '\u3000' <= ch <= '\u303f'
                  or '\uff00' <= ch <= '\uffef')
        rest = len(text) - cjk
        return cjk + (rest // 4)

    @pytest.mark.parametrize("text", [
        "Hello World",
        "你好世界",
        "Mixed content 混合內容 testing",
        "A" * 200,
        "中" * 200,
        "Project Brain 知識管理系統 — 這是一個完整的中英混合語句用於誤差測試",
    ])
    def test_error_within_20_percent(self, text):
        """新舊實作誤差 < 20%。"""
        fn = _fn()
        new_val = fn(text)
        old_val = self._old_count_tokens(text)
        if old_val == 0:
            assert new_val == 0
            return
        error = abs(new_val - old_val) / old_val
        assert error < 0.20, (
            f"誤差 {error:.1%} >= 20% — "
            f"text={text[:50]!r}, new={new_val}, old={old_val}"
        )
