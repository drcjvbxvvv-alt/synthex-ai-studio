# Project Brain — 改善規劃書

> **當前版本**：v0.6.0（2026-04-04）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P2** | 值得做但可計劃排入 | 計劃中 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## P2 — 量測中（需累積真實數據）

| ID | 問題 | 影響 | 解決方案 | 狀態 |
|----|------|------|---------|------|
| REV-02 | 尚未量測 Decay 實際效用 | 無法驗證衰減是幫助還是傷害召回率 | 對比有/無衰減知識庫；統計過時節點排前 3 的比例 | △ 需 90 天以上數據 |

**REV-02 量測方式**：詳見 `tests/TEST_PLAN.md` § 7 — REV-02 衰減效用量測

---

## P3 — 長期 / 低頻 / 實驗性

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| REF-01 | BrainDB ~1800 行，承擔 10+ 職責（God Object） | 難以維護，重構前需測試覆蓋率 ≥ 70% | 逐步抽離：`VectorStore`（add/search vector）、`FeedbackTracker`（record_feedback）| 2 週+ | 前提：覆蓋率 ≥ 70% |
| ARCH-04 | scope 三路控制流（`--global` / `--scope` / 自動推斷）讓使用者困惑 | UX 複雜，Breaking change | 合併 `--global` / `--scope` 為單一 `--scope global`；保留自動推斷 | 1 週 | Breaking change，需 major 版本 |
| REF-04 | 魔法數字散落（`0.003`、`800`、`400`、`limit=8`） | 維護時難以追蹤意圖，修改需同步多處 | 新增 `project_brain/constants.py`，遷入四個常數 | 半天 | 📋 `tests/unit/test_ref04_constants.py` |
| PERF-03 | CJK token 計數逐字迭代，無快取 | 高頻呼叫時浪費 CPU（800+ 次/request） | `_count_tokens()` 加 `@lru_cache(maxsize=1024)` | 30 分 | 📋 `tests/unit/test_perf03_token_cache.py` |
| BUG-A03 | `engine.py` 6 個懶加載屬性共用 `_init_lock`（非可重入）| 極低概率競態：雙重初始化 + 鏈式呼叫死鎖 | 拆分為各屬性獨立 `threading.Lock()` | 1 小時 | 📋 `tests/unit/test_bug_a03_locking.py` |

---

## 版本路線圖

| 版本 | 主題 | 主要工作 | 發布 Gate |
|------|------|---------|----------|
| **v0.7.0** | 清零技術債 | REF-04、PERF-03、BUG-A03（測試計劃已就緒，可立即執行）| 三項測試全通過；Chaos 100%；召回率 ≥ 60% |
| **v1.0.0** | 長期穩定 | REF-01（BrainDB 拆分）、ARCH-04（scope UX）| 覆蓋率 ≥ 70%；BrainDB ≤ 800 行 |

---

## 四維指標量測基準（v0.6.0）

> 每個 minor 版本發布前執行完整核查。**Gate** 條件為硬性阻塞點。

### 一、走向（Direction）

| 指標 | 門檻 | 量測方法 | v0.6.0 |
|------|------|---------|--------|
| 版本發布條件達成率 | 100%（Gate）| CHANGELOG 每版本 Gate checklist 完成數 ÷ 總數 | ✅ 達成 |
| 計劃打勾 vs 程式碼完成率 | 100% | code review 隨機抽查 5 項（commit hash + 行號可查）| △ 已制度化（DIR-03） |
| 技術債清零週期 | P0 ≤ 當版本；其餘 ≤ 2 版本 | IMPROVEMENT_PLAN 歷史計算 Bug ID 從出現到完成的版本跨距 | ✅ 符合 |
| Arch-Ready vs 端對端比例 | ≥ 70% | COMMANDS.md：🟢 ÷（🟢 + 🟡）| ✅ 17/22 = **77%** |
| 版本週期一致性 | 相鄰版本完成數差距 ≤ 30% | CHANGELOG 各版本 ✅ 條目數統計 | △ 未量測（需 CHANGELOG 歷史）|

### 二、穩定性（Stability）

| 指標 | 門檻 | 量測方法 | v0.6.0 |
|------|------|---------|--------|
| 靜默失效路徑數 | 0（Gate）| `grep -rn 'except.*pass' project_brain/` | ✅ 0 |
| Migration 失敗可觀察率 | 100% | 故意破壞 schema 後執行 `brain doctor`，確認有 warning | ✅ |
| Chaos test 通過率 | 100%（Gate v0.7.0）| `pytest -m chaos` | ✅ 17/17 |
| SR node 追蹤準確率 | 誤判率 0% | 注入含 emoji 標題，確認 access_count 更新對象正確 | ✅（STAB-07）|
| ReviewBoard.db 損壞恢復能力 | 有可操作錯誤訊息 | 故意損壞後確認 `brain review list` 非 stack trace | ✅（STAB-06）|

### 三、技術誠實性（Tech Honesty）

| 指標 | 門檻 | 量測方法 | v0.6.0 |
|------|------|---------|--------|
| 功能狀態標記覆蓋率 | 100% | COMMANDS.md 每個命令是否有 🟢/🟡/🔴 | ✅ 22/22 |
| LoRA 路徑說明準確性 | 已標注 | COMMANDS.md「已移除命令」含 Axolotl/Unsloth 說明 | ✅ |
| Synonym Map 條目數一致性 | 差距 ≤ 2 | `len(brain_db._SYNONYM_MAP)` vs `len(context._SYNONYM_MAP)` | ✅ 46 = 46 |
| ANN 觸發條件文件化 | 已標注 | COMMANDS.md 向量索引說明是否標注 HNSW 切換條件 | ✅ |
| 每版本宣稱 vs 實際審計 | 每版本執行 | 隨機抽查 3 個 CHANGELOG「完成」項目（commit hash + 行號）| ✅（DIR-03）|

### 四、飛輪（Flywheel）

| 指標 | 門檻 | 量測 SQL / 方法 | v0.6.0 |
|------|------|--------------|--------|
| 知識庫自然成長率 | ≥ 5 節點/7 天 | `SELECT COUNT(*) FROM nodes WHERE tags LIKE '%auto:complete_task%' AND created_at >= datetime('now','-7 days')` | △ SQL 就緒，需累積使用數據 |
| NudgeEngine 命中率 | ≥ 30%（> 20 節點後）| events 表 `nudge_triggered` ÷ `get_context` 總呼叫數 | △ emit 已實作，需累積事件 |
| `get_context` 召回率 | ≥ 60%（Gate）| `tests/benchmarks/benchmark_recall.py`，50 節點 + 20 查詢 | ✅ **95%**（hybrid search） |
| 衰減效用 | 過時節點排前 3 比例 < 20% | 對比有/無衰減庫召回率 + 年齡分布 SQL（REV-02）| △ 需 90 天以上數據 |
