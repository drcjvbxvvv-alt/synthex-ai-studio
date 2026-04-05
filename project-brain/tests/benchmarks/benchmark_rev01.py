"""
tests/benchmarks/benchmark_rev01.py — REV-01 量化對照實驗（Layer 1: 合成自動化）

商業假設
--------
使用 Project Brain 的 Agent 在相同任務上：
  A. 能召回 ≥ 70% 的已知 Pitfall（避免重複踩坑）
  B. 有 Brain context 的查詢比無 context 的 Pitfall 出現率高 ≥ 50pp（對照實驗）
  C. 正向反饋使 confidence 提升（+3% per signal，知識品質自我強化）
  D. 負向反饋使 confidence 下降（-5% per signal，知識自我修正）
  E. 15 次正向反饋後 confidence ≥ 0.90（知識可晉升至「核心知識」）
  F. adoption_count 隨正向反饋累加（F6 因子依賴）

執行
----
  python -m pytest tests/benchmarks/benchmark_rev01.py -v
  python -m pytest tests/benchmarks/benchmark_rev01.py -v -k "control_vs_treatment"
"""
from __future__ import annotations
import pytest
from project_brain.engine import ProjectBrain

# ── 合成資料集 ────────────────────────────────────────────────────────────────
# 5 對（Pitfall 標題, 內容）+ 對應查詢
# 每對的查詢語意相關但用語不同，測試 FTS + 向量召回的真實能力

PITFALLS: list[tuple[str, str]] = [
    (
        "JWT 簽名演算法必須使用 RS256，禁止 HS256",
        "HS256 是對稱演算法，在多服務架構下所有服務共享同一個 secret，"
        "任何一個服務被攻破即可偽造 token。RS256 私鑰只有簽名方持有。",
    ),
    (
        "SQLite 必須開啟 WAL 模式",
        "預設 journal_mode=DELETE 會在並發讀寫時產生 SQLITE_BUSY 錯誤。"
        "WAL 模式允許多個讀取者與一個寫入者同時操作。",
    ),
    (
        "API Key 驗證必須使用 hmac.compare_digest",
        "直接用 == 比較字串存在 timing attack 風險。"
        "compare_digest 保證比較時間固定，防止攻擊者透過回應時間推斷 key 長度。",
    ),
    (
        "資料庫遷移必須包含 rollback 機制",
        "無 rollback 的遷移在中途失敗時會造成 schema 半更新狀態，"
        "需要人工介入修復。應使用 try/except + conn.rollback()。",
    ),
    (
        "FTS5 索引更新必須與節點更新在同一個 transaction",
        "若 UPDATE nodes 成功但 FTS INSERT 失敗，搜尋索引與資料不一致，"
        "導致已更新的節點在 FTS 查詢中不可見（False Negative）。",
    ),
]

RELATED_QUERIES: list[str] = [
    "如何設定 JWT 簽名演算法確保跨服務安全",
    "SQLite 並發讀寫最佳實踐與鎖競爭處理",
    "後端 API Key 驗證的安全注意事項",
    "資料庫 schema 變更與遷移策略",
    "全文搜尋索引更新的原子性保證",
]

assert len(PITFALLS) == len(RELATED_QUERIES), "每個 Pitfall 應有一個對應查詢"


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def brain_with_pitfalls(tmp_path):
    """注入所有合成 Pitfall 的 Brain 實例（實驗組）"""
    b = ProjectBrain(str(tmp_path))
    for title, content in PITFALLS:
        b.add_knowledge(title, content, kind="Pitfall", tags=["rev01-synthetic"])
    return b


@pytest.fixture
def empty_brain(tmp_path):
    """空知識庫 Brain 實例（控制組）"""
    return ProjectBrain(str(tmp_path))


@pytest.fixture
def pb(tmp_path):
    """ProjectBrain 實例（用於反饋迴圈測試，透過 pb.db 存取 BrainDB）"""
    return ProjectBrain(str(tmp_path))


# ── Layer 1A: Pitfall 召回率 ──────────────────────────────────────────────────

class TestREV01PitfallRecall:
    """A. Pitfall 召回率必須 ≥ 70%"""

    def test_pitfall_recall_rate_meets_threshold(self, brain_with_pitfalls):
        """
        合成對照實驗：加入 5 個已知 Pitfall，查詢 5 個相關任務。
        至少 1 個 Pitfall 出現在 context 即算命中。
        門檻：召回率 ≥ 70%（5 個中至少 3.5 → 4 個命中）
        """
        hits = 0
        for i, query in enumerate(RELATED_QUERIES):
            ctx = brain_with_pitfalls.get_context(query) or ""
            # 用 Pitfall 標題前 15 字做寬鬆比對（允許截斷）
            anchor = PITFALLS[i][0][:15]
            if anchor in ctx:
                hits += 1

        recall = hits / len(RELATED_QUERIES)
        assert recall >= 0.70, (
            f"Pitfall 召回率 {recall:.0%} 未達 70% 門檻\n"
            f"  命中：{hits}/{len(RELATED_QUERIES)}\n"
            f"  → 確認 FTS n-gram 分詞與 get_context token budget 設定"
        )

    def test_each_pitfall_individually_retrievable(self, brain_with_pitfalls):
        """每個 Pitfall 單獨查詢時必須能被召回（個別可見性保證）"""
        missing = []
        for title, content in PITFALLS:
            # 用 content 的前幾個關鍵字查詢（與標題用語不同）
            keyword = content.split("。")[0][:20]
            ctx = brain_with_pitfalls.get_context(keyword) or ""
            if title[:15] not in ctx:
                missing.append(title[:40])

        assert not missing, (
            f"以下 Pitfall 無法被召回（共 {len(missing)} 個）：\n"
            + "\n".join(f"  - {t}" for t in missing)
        )


# ── Layer 1B: 對照實驗（有 Brain vs 無 Brain）────────────────────────────────

class TestREV01ControlVsTreatment:
    """B. 實驗組 vs 控制組的 Pitfall 出現率差距 ≥ 50pp"""

    def test_treatment_vs_control_pitfall_avoidance(self, tmp_path):
        """
        對照實驗核心：
          控制組 = 空知識庫（無任何 Pitfall）
          實驗組 = 5 個已知 Pitfall

        同樣查詢下，實驗組 context 包含 Pitfall 的比率
        必須比控制組高 ≥ 50 個百分點。
        """
        # 控制組
        control = ProjectBrain(str(tmp_path / "control"))

        # 實驗組
        treatment = ProjectBrain(str(tmp_path / "treatment"))
        for title, content in PITFALLS:
            treatment.add_knowledge(title, content, kind="Pitfall",
                                    tags=["rev01-synthetic"])

        control_hits, treatment_hits = 0, 0
        for i, query in enumerate(RELATED_QUERIES):
            c_ctx = control.get_context(query) or ""
            t_ctx = treatment.get_context(query) or ""
            anchor = PITFALLS[i][0][:15]
            if anchor in c_ctx:
                control_hits += 1
            if anchor in t_ctx:
                treatment_hits += 1

        control_rate   = control_hits   / len(RELATED_QUERIES)
        treatment_rate = treatment_hits / len(RELATED_QUERIES)
        diff = treatment_rate - control_rate

        assert diff >= 0.50, (
            f"實驗組 vs 控制組 Pitfall 出現率差距 {diff:.0%} < 50pp\n"
            f"  控制組：{control_rate:.0%}（{control_hits}/{len(RELATED_QUERIES)}）\n"
            f"  實驗組：{treatment_rate:.0%}（{treatment_hits}/{len(RELATED_QUERIES)}）\n"
            f"  → Brain 對 Pitfall 預防的增量貢獻不足"
        )

    def test_rule_also_retrieved_in_treatment(self, tmp_path):
        """Rule 類型知識在實驗組中也能被召回（非 Pitfall 的知識類型驗證）"""
        b = ProjectBrain(str(tmp_path))
        b.add_knowledge(
            "所有外部 API 呼叫必須設定 timeout",
            "未設定 timeout 的 HTTP 呼叫在對方無回應時會永久阻塞，"
            "需使用 requests(timeout=30) 或等效設定。",
            kind="Rule",
            tags=["rev01-synthetic"],
        )
        ctx = b.get_context("設計呼叫第三方服務的架構") or ""
        # Rule 應出現在 context（寬鬆：只要 context 非空）
        assert ctx, "實驗組注入 Rule 後，相關查詢 context 不應為空"


# ── Layer 1C/D: 反饋迴圈（confidence 動態調整）───────────────────────────────

class TestREV01FeedbackLoop:
    """C/D. confidence 反饋迴圈正確性"""

    def test_positive_feedback_increases_confidence(self, pb):
        """正向反饋後 confidence 提升 +3%"""
        nid = pb.add_knowledge("重要規則", "內容", kind="Rule", confidence=0.70)
        before = float(pb.db.get_node(nid)["confidence"])

        pb.db.record_feedback(nid, helpful=True)
        after = float(pb.db.get_node(nid)["confidence"])

        assert after > before, f"正向反饋後 confidence 未提升：{before:.3f} → {after:.3f}"
        assert abs(after - (before + 0.03)) < 0.001, (
            f"預期 +0.03，實際 {after - before:+.3f}"
        )
        assert after <= 1.0, "confidence 不可超過 1.0"

    def test_negative_feedback_decreases_confidence(self, pb):
        """負向反饋後 confidence 下降 -5%"""
        nid = pb.add_knowledge("過時知識", "舊內容", kind="Pitfall", confidence=0.80)
        before = float(pb.db.get_node(nid)["confidence"])

        pb.db.record_feedback(nid, helpful=False)
        after = float(pb.db.get_node(nid)["confidence"])

        assert after < before, f"負向反饋後 confidence 未下降：{before:.3f} → {after:.3f}"
        assert abs(after - (before - 0.05)) < 0.001, (
            f"預期 -0.05，實際 {after - before:+.3f}"
        )
        assert after >= 0.05, "confidence 不可低於 DECAY_FLOOR=0.05"

    def test_confidence_floor_enforced(self, pb):
        """連續負向反饋後 confidence 不可低於 0.05（DECAY_FLOOR）"""
        nid = pb.add_knowledge("已廢棄知識", "無效內容", kind="Pitfall", confidence=0.10)
        for _ in range(20):
            pb.db.record_feedback(nid, helpful=False)

        final = float(pb.db.get_node(nid)["confidence"])
        assert final >= 0.05, f"confidence {final:.3f} 跌破 DECAY_FLOOR=0.05"

    def test_confidence_ceiling_enforced(self, pb):
        """連續正向反饋後 confidence 不可超過 1.0（DECAY_CEIL）"""
        nid = pb.add_knowledge("核心規則", "重要內容", kind="Rule", confidence=0.95)
        for _ in range(20):
            pb.db.record_feedback(nid, helpful=True)

        final = float(pb.db.get_node(nid)["confidence"])
        assert final <= 1.0, f"confidence {final:.3f} 超過 DECAY_CEIL=1.0"


# ── Layer 1E: 知識晉升（高信心門檻）─────────────────────────────────────────

class TestREV01KnowledgePromotion:
    """E. 15 次正向反饋後 confidence ≥ 0.90（知識晉升為「核心知識」）"""

    def test_repeatedly_useful_node_reaches_high_confidence(self, pb):
        """
        商業意義：若一個知識節點被 Agent 連續 15 次確認有用，
        它應晉升為高信心知識（≥ 0.90），在未來查詢中優先出現。
        """
        nid = pb.add_knowledge("被驗證的最佳實踐", "核心內容", kind="Rule",
                               confidence=0.60)

        for _ in range(15):
            pb.db.record_feedback(nid, helpful=True)

        final = float(pb.db.get_node(nid)["confidence"])
        assert final >= 0.90, (
            f"15 次正向反饋後 confidence {final:.2f} < 0.90\n"
            f"  預期晉升為核心知識（≥ 0.90），實際未達標"
        )

    def test_alternating_feedback_stabilizes_confidence(self, pb):
        """正負交替反饋後 confidence 應在初始值附近穩定（±0.15 內）"""
        initial = 0.70
        nid = pb.add_knowledge("中性知識", "內容", kind="Rule", confidence=initial)

        for i in range(10):
            pb.db.record_feedback(nid, helpful=(i % 2 == 0))

        final = float(pb.db.get_node(nid)["confidence"])
        assert abs(final - initial) <= 0.15, (
            f"正負交替 10 輪後 confidence 偏移過大：{initial:.2f} → {final:.2f}"
        )


# ── Layer 1F: adoption_count（F6 因子）────────────────────────────────────────

class TestREV01AdoptionCount:
    """F. adoption_count 隨正向反饋正確累加（DecayEngine F6 因子依賴）"""

    def test_adoption_count_increments_on_positive_feedback(self, pb):
        """3 次正向反饋後 adoption_count ≥ 3"""
        nid = pb.add_knowledge("常用規則", "內容", kind="Rule")
        for _ in range(3):
            pb.db.record_feedback(nid, helpful=True)

        node = pb.db.get_node(nid)
        adoption = node.get("adoption_count", 0)
        assert adoption >= 3, (
            f"3 次正向反饋後 adoption_count={adoption}，預期 ≥ 3\n"
            f"  adoption_count 是 DecayEngine F6 因子，影響衰減速度"
        )

    def test_negative_feedback_does_not_increment_adoption_count(self, pb):
        """負向反饋不應增加 adoption_count"""
        nid = pb.add_knowledge("廢棄知識", "舊內容", kind="Pitfall")
        for _ in range(5):
            pb.db.record_feedback(nid, helpful=False)

        node = pb.db.get_node(nid)
        adoption = node.get("adoption_count", 0)
        assert adoption == 0, (
            f"5 次負向反饋後 adoption_count={adoption}，預期 == 0"
        )

    def test_mixed_feedback_adoption_count_only_counts_positive(self, pb):
        """正負混合反饋時，adoption_count 只計正向次數"""
        nid = pb.add_knowledge("混合反饋節點", "內容", kind="Rule")
        for i in range(6):
            pb.db.record_feedback(nid, helpful=(i % 2 == 0))  # 3 正 3 負

        node = pb.db.get_node(nid)
        adoption = node.get("adoption_count", 0)
        assert adoption == 3, (
            f"3 正 3 負後 adoption_count={adoption}，預期 == 3"
        )
