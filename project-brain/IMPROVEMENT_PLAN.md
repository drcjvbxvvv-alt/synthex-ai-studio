# Project Brain — 改善規劃書

> **當前版本**：v0.24.0（2026-04-06）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。
> **測試基準**：903 passed / 5 skipped（45 unit tests in `test_mem_improvements.py`）

---

## 優先等級

| 等級 | 說明 |
|------|------|
| **P1** | 明確影響正確性或安全性，應優先處理 |
| **P2** | 影響核心功能品質，計劃排入 |
| **P3** | 長期願景、低頻路徑、實驗性 |

---

## 待辦項目

| 優先 | ID | 影響摘要 | 象限 | 狀態 |
|------|----|---------|------|------|
| **P2** | TEST-04 | WebUI 測試覆蓋率 < 12% | 🎯 高價值 | ⏸ 擱置 |
| **P2** | FEAT-08 | WebUI 節點行內編輯 | 📋 計劃執行 | ⏸ 擱置 |
| **P2** | REV-01 | 量化對照實驗 Layer 2/3（需線上數據） | △ 需累積 | △ 進行中 |
| **P2** | REV-02 | 衰減效用對比測試（需 90 天數據） | △ 需累積 | △ 進行中 |

---

## TEST-04 — WebUI 測試覆蓋率

**狀態**：擱置（等 WebUI 功能穩定）

10 個 pre-existing failures（`sqlite3: no such column: scope`）反映 WebUI 測試與 schema v22 不同步。
待 `scope` 欄位 migration 完成後一併補測試。

## FEAT-08 — WebUI 節點行內編輯

**狀態**：擱置

計劃在 `web_ui/server.py` 新增 `PATCH /api/nodes/<id>` 端點，前端加入 inline edit 模式。

## REV-01 / REV-02 — 量化對照實驗

**狀態**：持續累積數據

需要至少 30 天線上使用數據後才能比較：
- REV-01：AI 選取（MEM-01）召回率 vs. 純 FTS5
- REV-02：Decay Engine 衰減效用（需 90 天以上）
