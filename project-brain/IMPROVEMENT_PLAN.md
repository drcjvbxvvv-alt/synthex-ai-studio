# Project Brain — 改善規劃書

> **當前版本**：v0.6.0（2026-04-04）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P1** | 明確影響正確性，應優先處理 | 下一個 minor |
| **P2** | 值得做但可計劃排入 | 計劃中 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## P1 — 正確性缺陷

~~BUG-B02~~ ✅ **已修復（2026-04-04）**：`_effective_confidence()`（`brain_db.py`）和 `decay_engine._factor_time()`（`decay_engine.py`）改用 `MAX(created_at, updated_at)` 作為衰減時間基準。820 天前建立但 3 天前更新的節點，effective_confidence 從 0.077 恢復至 0.892。

> P1 項目全數完成，本節保留供 CHANGELOG 同步後移除。

---

## P2 — 已知缺陷

### BUG-B01 — BrainDB.session_* 是死碼

**問題**：`brain_db.py` 含有 `session_set / session_get / session_list / session_clear` 四個方法（`~1126~1165` 行），但 **grep 確認在 `project_brain/` 內無任何業務呼叫者**。`session_store.py` 的 `SessionStore` 是 L1a 的真正實作，`brain_db.session_*` 從未被連接到任何流程。

**實際影響**：
- `brain_db.py` 虛增 ~50 行（含 `ReadBrainDB` 中 4 個對應的 `PermissionError` override）
- 讀者難以判斷「L1a 到底應該用 BrainDB 還是 SessionStore」
- 任何新貢獻者都可能誤用 `db.session_set()` 而非 `SessionStore`

**修復方案**：移除 `BrainDB.session_set/get/list/clear` 及 `ReadBrainDB` 中的四個對應 override。確認無測試直接呼叫這四個方法（`test_core.py` 有無？）後直接刪除。

**工時**：1 小時（刪除 + 確認測試仍通過）

### REV-02 — Decay 實際效用未量測

無法驗證衰減是幫助還是傷害召回率。對比有/無衰減知識庫；統計過時節點排前 3 的比例。△ 需 90 天以上數據。

詳見 `tests/TEST_PLAN.md` § 7 — REV-02 衰減效用量測

---

## P3 — 長期 / 低頻 / 實驗性

| ID | 問題 | 影響 | 解決方案 | 工時 | 備註 |
|----|------|------|---------|------|------|
| REF-01 | BrainDB ~1800 行，承擔 10+ 職責（God Object） | 難以維護，重構前需測試覆蓋率 ≥ 70% | 逐步抽離：`VectorStore`（add/search vector）、`FeedbackTracker`（record_feedback）| 2 週+ | 前提：覆蓋率 ≥ 70% |
| CLI-01 | `cli.py` 2864 行，31 個 `cmd_*` 函數全在同一檔案 | 比 BrainDB 更大；每個命令函數重複 `_workdir + brain_dir.exists()` 樣板；`cmd_serve` 240 行、`cmd_doctor` 378 行 | 按功能群組拆分：`cli_serve.py`、`cli_admin.py`、`cli_knowledge.py` 等；抽取 `@require_brain_dir` 裝飾器消除樣板 | 1.5 週 | 先補整合測試覆蓋率，再拆分 |
| ARCH-04 | scope 三路控制流（`--global` / `--scope` / 自動推斷）讓使用者困惑 | UX 複雜，Breaking change | 合併 `--global` / `--scope` 為單一 `--scope global`；保留自動推斷 | 1 週 | Breaking change，需 major 版本 |
| REF-04 | 魔法數字散落（`0.003`、`800`、`400`、`limit=8`） | 維護時難以追蹤意圖，修改需同步多處 | 新增 `project_brain/constants.py`，遷入四個常數 | 半天 | 📋 `tests/unit/test_ref04_constants.py` |
| PERF-03 | CJK token 計數逐字迭代，無快取 | 高頻呼叫時浪費 CPU（800+ 次/request） | `_count_tokens()` 加 `@lru_cache(maxsize=1024)` | 30 分 | 📋 `tests/unit/test_perf03_token_cache.py` |
| BUG-A03 | `engine.py` 6 個懶加載屬性共用 `_init_lock`（非可重入）| 極低概率競態：雙重初始化 + 鏈式呼叫死鎖 | 拆分為各屬性獨立 `threading.Lock()` | 1 小時 | 📋 `tests/unit/test_bug_a03_locking.py` |

---

## 版本路線圖

| 版本 | 主題 | 主要工作 | 發布 Gate |
|------|------|---------|----------|
| **v0.7.0** | 正確性優先 | BUG-B02（Decay 時間基準）、BUG-B01（session 死碼）、REF-04、PERF-03、BUG-A03 | 所有測試通過；Chaos 100%；召回率 ≥ 60% |
| **v1.0.0** | 長期穩定 | REF-01（BrainDB 拆分）、CLI-01（cli.py 拆分）、ARCH-04（scope UX）| 覆蓋率 ≥ 70%；BrainDB ≤ 800 行；cli.py ≤ 500 行 |
