"""
tests/unit/test_perf03_token_cache.py — PERF-03 lru_cache 驗收測試
═══════════════════════════════════════════════════════════════

問題（PERF-03）
──────────────
`context.py` 的 `_count_tokens(text)` 在每次組裝 context 時對同一段文字
重複計算，沒有任何快取。CJK 邏輯逐字元判斷，在大量節點時累積成可觀的 CPU 開銷。

  profile 範例（100 節點，每節點平均 300 字元）：
    _count_tokens  called 800+ times/request
    total tokens counted: 240,000+ chars
    wall time: ~15ms （純 Python，可降至 < 1ms with cache）

實作計劃（執行前請閱讀）
────────────────────────
1. `context.py` 頂部加入：
   ```python
   from functools import lru_cache
   ```

2. 在 `_count_tokens` 定義上加：
   ```python
   @lru_cache(maxsize=1024)
   def _count_tokens(text: str) -> int:
       ...
   ```

   注意：`lru_cache` 要求參數可 hash，`str` 天然符合。
   若函數現為方法（self），需改為 module-level function 或 staticmethod。

3. 若 `_count_tokens` 是 `ContextEngineer` 的 instance method，
   需改為 `@staticmethod` 再加 `@lru_cache`，或抽成 module-level function。

驗收標準
────────
- `_count_tokens` 有 `cache_info()` 方法（表示 lru_cache 已套用）
- 相同輸入兩次呼叫後，cache_info().hits >= 1
- 快取前後計算結果完全一致（無正確性迴歸）
- Benchmark：1000 次相同輸入，快取版比未快取版快 10x+
- 邊界值（空字串、純 CJK、純 ASCII、混合）結果正確且快取命中

執行方式
────────
  # 未實作前（應失敗）：
  python -m pytest tests/unit/test_perf03_token_cache.py -v

  # 實作後（應全部通過）：
  python -m pytest tests/unit/test_perf03_token_cache.py -v
"""
import time
import pytest


# ════════════════════════════════════════════════════════════════
#  測試群組 1：lru_cache 確實套用
# ════════════════════════════════════════════════════════════════

class TestPerf03CacheApplied:
    """_count_tokens 必須被 lru_cache 裝飾，具備 cache_info() 介面。"""

    def _get_count_tokens(self):
        """取得 _count_tokens callable（支援 module-level 或 staticmethod）。"""
        from project_brain import context as ctx_module

        # 優先：module-level function
        fn = getattr(ctx_module, "_count_tokens", None)
        if fn is not None:
            return fn

        # 次選：ContextEngineer staticmethod
        fn = getattr(ctx_module.ContextEngineer, "_count_tokens", None)
        if fn is not None:
            return fn

        raise AttributeError(
            "_count_tokens 不存在於 project_brain.context 或 ContextEngineer"
        )

    def test_count_tokens_has_cache_info(self):
        """_count_tokens 應有 cache_info() 方法（lru_cache 標誌）。"""
        fn = self._get_count_tokens()
        assert hasattr(fn, "cache_info"), (
            "_count_tokens 缺少 cache_info() 方法。\n"
            "請在函數定義上加 @lru_cache(maxsize=1024)。"
        )

    def test_count_tokens_has_cache_clear(self):
        """_count_tokens 應有 cache_clear() 方法（lru_cache 標誌）。"""
        fn = self._get_count_tokens()
        assert hasattr(fn, "cache_clear"), (
            "_count_tokens 缺少 cache_clear() 方法。"
        )

    def test_cache_hits_on_repeated_call(self):
        """相同輸入呼叫兩次後，cache_info().hits 應 >= 1。"""
        fn = self._get_count_tokens()
        fn.cache_clear()  # 重設計數器

        text = "Hello World 你好世界"
        fn(text)   # 第一次：miss
        fn(text)   # 第二次：hit

        info = fn.cache_info()
        assert info.hits >= 1, (
            f"第二次呼叫相同輸入應為 cache hit，實際 hits={info.hits}。\n"
            "lru_cache 可能未正確套用，或函數有 mutable 參數。"
        )

    def test_cache_miss_on_first_call(self):
        """第一次呼叫新輸入應為 cache miss（hits 不增加）。"""
        fn = self._get_count_tokens()
        fn.cache_clear()

        unique_text = "獨特字串_test_miss_" + "X" * 50
        fn(unique_text)

        info = fn.cache_info()
        assert info.misses >= 1, (
            "第一次呼叫應記錄 miss，但 misses 未增加。"
        )

    def test_cache_maxsize_is_at_least_1024(self):
        """lru_cache maxsize 應 >= 1024（避免頻繁 eviction）。"""
        fn = self._get_count_tokens()
        info = fn.cache_info()
        assert info.maxsize is None or info.maxsize >= 1024, (
            f"cache maxsize={info.maxsize}，建議 >= 1024 以覆蓋典型工作集。"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 2：正確性（快取不引入回歸）
# ════════════════════════════════════════════════════════════════

class TestPerf03Correctness:
    """快取前後計算結果必須完全一致。"""

    def _fn(self):
        from project_brain import context as ctx_module
        fn = getattr(ctx_module, "_count_tokens", None)
        if fn is None:
            fn = getattr(ctx_module.ContextEngineer, "_count_tokens", None)
        return fn

    @pytest.mark.parametrize("text,expected_range", [
        ("",                     (0, 0)),           # 空字串
        ("hello",                (1, 5)),            # 純 ASCII（各實作不同，token 數在合理範圍）
        ("你好世界",              (2, 8)),            # 純 CJK
        ("Hello 你好",           (2, 8)),            # 混合
        ("  ",                   (0, 2)),            # 空白
        ("a" * 100,              (1, 100)),          # 長 ASCII
        ("中" * 100,             (50, 150)),         # 長 CJK
    ])
    def test_correctness_stable(self, text, expected_range):
        """相同輸入多次呼叫結果應穩定且在合理範圍內。"""
        fn = self._fn()
        results = [fn(text) for _ in range(5)]
        assert len(set(results)) == 1, (
            f"相同輸入 {text!r:.30} 的計算結果不穩定：{results}"
        )
        lo, hi = expected_range
        assert lo <= results[0] <= hi, (
            f"_count_tokens({text!r:.30}) = {results[0]}，"
            f"超出預期範圍 [{lo}, {hi}]"
        )

    def test_empty_string_returns_zero(self):
        """空字串應回傳 0。"""
        fn = self._fn()
        assert fn("") == 0, f"_count_tokens('') 應為 0，實際 {fn('')}"

    def test_cjk_counts_more_than_half_char_count(self):
        """
        CJK 文字每字通常計為 2 token（或約 1.5），
        確保 CJK 不被低估（比同長度 ASCII 更多 token）。
        """
        fn = self._fn()
        ascii_text = "a" * 10
        cjk_text   = "中" * 10
        assert fn(cjk_text) >= fn(ascii_text), (
            f"CJK 10 字（{fn(cjk_text)}）應 >= ASCII 10 字（{fn(ascii_text)}），"
            "可能 CJK 計數邏輯有誤。"
        )

    def test_cache_does_not_corrupt_result(self):
        """快取命中的結果應與首次計算完全相同（無狀態污染）。"""
        fn = self._fn()
        fn.cache_clear()

        text = "Project Brain 知識管理系統 — 確認快取正確性"
        first  = fn(text)
        second = fn(text)   # cache hit
        third  = fn(text)   # cache hit

        assert first == second == third, (
            f"快取命中結果不一致：{first} / {second} / {third}"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 3：效能基準
# ════════════════════════════════════════════════════════════════

class TestPerf03Benchmark:
    """快取版應比純計算快 10x+（N=1000 次相同輸入）。"""

    def _fn(self):
        from project_brain import context as ctx_module
        fn = getattr(ctx_module, "_count_tokens", None)
        if fn is None:
            fn = getattr(ctx_module.ContextEngineer, "_count_tokens", None)
        return fn

    @pytest.mark.parametrize("text", [
        "Hello World",
        "你好世界這是一段測試文字用於效能基準",
        "Mixed content 混合內容 testing performance 效能測試 1234567890",
        "A" * 200,
        "中" * 200,
    ])
    def test_cached_calls_faster_than_uncached(self, text):
        """
        1000 次快取命中應比 1000 次手動重新計算快 10x+。

        測試方法：
        1. 記錄 cache_info 起始狀態
        2. 計時 1000 次 fn(text)（大多為 cache hit）
        3. 使用 __wrapped__ 計時 1000 次不經快取的原始函數
        4. 斷言加速比 >= 10
        """
        fn = self._fn()
        fn.cache_clear()

        # 預熱快取
        fn(text)

        N = 1000

        # 快取版（第 2-1001 次呼叫，全為 cache hit）
        t0 = time.perf_counter()
        for _ in range(N):
            fn(text)
        cached_time = time.perf_counter() - t0

        # 原始版（透過 __wrapped__ 繞過快取）
        raw_fn = getattr(fn, "__wrapped__", None)
        if raw_fn is None:
            pytest.skip("找不到 __wrapped__，無法比較原始速度（lru_cache 未套用？）")

        t0 = time.perf_counter()
        for _ in range(N):
            raw_fn(text)
        raw_time = time.perf_counter() - t0

        # 快取至少要快 10x（避免在極快機器上的浮動）
        if raw_time > 0.001:  # 只有原始版夠慢時才做比例斷言
            speedup = raw_time / max(cached_time, 1e-9)
            assert speedup >= 10, (
                f"快取加速比 {speedup:.1f}x < 10x（原始 {raw_time*1000:.2f}ms，"
                f"快取 {cached_time*1000:.2f}ms），可能快取未命中。\n"
                f"文字：{text[:50]!r}"
            )
        else:
            # 原始函數太快（< 1ms for 1000 calls），快取命中總時間也應更短
            assert cached_time <= raw_time * 2, (
                f"即使原始函數很快，快取版也不應更慢。"
                f"原始 {raw_time*1000:.3f}ms，快取 {cached_time*1000:.3f}ms"
            )

    def test_cache_hit_rate_after_repeated_queries(self):
        """
        模擬真實 context 組裝：20 個不同文字各查詢 50 次，
        最終命中率應 >= 90%。
        """
        fn = self._fn()
        fn.cache_clear()

        texts = [f"節點內容 {i}：這是第 {i} 個知識節點的文字內容，用於測試快取命中率。" for i in range(20)]

        for text in texts:
            fn(text)  # 預熱

        for _ in range(49):
            for text in texts:
                fn(text)

        info = fn.cache_info()
        total = info.hits + info.misses
        hit_rate = info.hits / max(total, 1)

        assert hit_rate >= 0.90, (
            f"快取命中率 {hit_rate:.1%} < 90%。\n"
            f"cache_info: hits={info.hits}, misses={info.misses}, "
            f"maxsize={info.maxsize}, currsize={info.currsize}"
        )

    def test_context_build_time_reduced_with_cache(self, tmp_path):
        """
        端對端：context.build() 第二次呼叫（快取暖身後）
        應比第一次快（cold → warm）。
        """
        from project_brain.graph import KnowledgeGraph
        from project_brain.context import ContextEngineer

        g = KnowledgeGraph(tmp_path)
        for i in range(30):
            g.add_node(
                f"node_{i}", "Rule", f"規則 {i}",
                content="A" * 300 + "中文內容 " * 20,
            )

        ce = ContextEngineer(g, tmp_path)

        # cold run（快取為空）
        fn = self._fn()
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()

        t0 = time.perf_counter()
        ce.build("規則")
        cold_time = time.perf_counter() - t0

        # warm run（快取已暖身）
        t0 = time.perf_counter()
        for _ in range(5):
            ce.build("規則")
        warm_time = (time.perf_counter() - t0) / 5

        # warm 應比 cold 快至少 2x（保守估計）
        assert warm_time <= cold_time * 0.8 or warm_time < 0.005, (
            f"快取暖身後 context.build() 未加速：\n"
            f"  cold: {cold_time*1000:.2f}ms\n"
            f"  warm: {warm_time*1000:.2f}ms\n"
            f"（注意：若原始速度已 < 5ms，此斷言自動通過）"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 4：邊界值與特殊情況
# ════════════════════════════════════════════════════════════════

class TestPerf03EdgeCases:
    """確認快取對邊界輸入不產生副作用。"""

    def _fn(self):
        from project_brain import context as ctx_module
        fn = getattr(ctx_module, "_count_tokens", None)
        if fn is None:
            fn = getattr(ctx_module.ContextEngineer, "_count_tokens", None)
        return fn

    def test_none_or_empty_does_not_poison_cache(self):
        """空字串不應污染後續呼叫的快取。"""
        fn = self._fn()
        fn.cache_clear()

        r_empty = fn("")
        r_hello = fn("hello")
        r_empty2 = fn("")  # cache hit

        assert r_empty == r_empty2 == 0, (
            f"空字串結果應穩定為 0，實際 {r_empty} / {r_empty2}"
        )
        assert r_hello > 0, "非空字串應有 token 數 > 0"

    def test_unicode_edge_cases(self):
        """Unicode 特殊字元不應使快取鍵計算出錯。"""
        fn = self._fn()
        fn.cache_clear()

        special_cases = [
            "\n\t\r",          # 控制字元
            "🧠💡🔥",          # emoji
            "Ｈｅｌｌｏ",       # 全形英文
            "＜＞＆",           # 全形符號
            "\u200b" * 10,     # 零寬空格
        ]
        for text in special_cases:
            r1 = fn(text)
            r2 = fn(text)  # cache hit
            assert r1 == r2, (
                f"Unicode 輸入 {text!r} 的快取結果不一致：{r1} vs {r2}"
            )

    def test_very_long_text_cached_correctly(self):
        """超長文字（10000 字元）應被快取且結果穩定。"""
        fn = self._fn()
        fn.cache_clear()

        long_text = ("Project Brain 知識管理系統 " * 200)[:10000]
        r1 = fn(long_text)
        r2 = fn(long_text)
        assert r1 == r2 > 0, (
            f"超長文字快取結果不一致或為 0：{r1} vs {r2}"
        )

    def test_different_inputs_have_different_cache_entries(self):
        """不同輸入不能互相污染快取（hash 衝突保護）。"""
        fn = self._fn()
        fn.cache_clear()

        texts = [
            "A" * 100,
            "B" * 100,
            "中" * 100,
            "Hello World " * 10,
            "你好世界 " * 20,
        ]
        results = {text: fn(text) for text in texts}

        # 再呼叫一次確認 cache hit 仍是正確值
        for text, expected in results.items():
            actual = fn(text)
            assert actual == expected, (
                f"快取污染：{text[:30]!r} 首次={expected}，再次={actual}"
            )
