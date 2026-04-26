# Project Brain — 改善規劃書

> **當前版本**：v0.30.0（2026-04-06）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。
> **測試基準**：624 passed（Phase 1 Step 2 KnowledgeExecutor 18 tests）
> **分析基準**：2026-04-06 全程式碼審計，涵蓋 brain_db / engine / context / decay / mcp_server / graph / session_store / extractor

---

## 優先等級

| 等級 | 說明 | 目標 |
|------|------|------|
| **P1** | 資料正確性 / 安全性缺陷，影響生產穩定性 | 立即修復 |
| **P2** | 核心功能品質問題，影響使用體驗 | 1–2 週內 |
| **P3** | 長期改善、效能優化、功能強化 | 1–2 個月內 |

---

## 矩陣優先總覽

| 優先 | ID | 影響摘要 | 狀態 |
|------|----|---------|------|
| **P2** | TEST-04 | WebUI 測試覆蓋率 < 12%（scope 欄位 migration 不同步） | ⏸ 擱置 |
| **P2** | FEAT-08 | WebUI 節點行內編輯 | ⏸ 擱置 |
| **P2** | BUG-07 | `brain setup` 對已存在的 DB 觸發 legacy migration，`sessions`/`memories` 表不存在卻記錄 ERROR | 📋 規劃中 |
| **P2** | REV-01 | 量化對照實驗 Layer 2/3（需線上數據） | ⏸ 擱置 |
| **P2** | REV-02 | 衰減效用對比測試（需 90 天數據） | ⏸ 擱置 |

---

## P2 — 待修 Bug

### BUG-07 — `brain setup` 對已存在 DB 誤觸 legacy migration，假 ERROR 嚇使用者

**位置**：
- `setup_wizard.py:126–130`（legacy 偵測邏輯）
- `brain_db.py:1959–1978`（`migrate_from_legacy()` session 遷移段落）

**現象**：
在已初始化的專案執行 `brain setup`（或新版的 `brain init`）時，若 `.brain/` 目錄存在 `session_store.db`，終端輸出：
```
ERROR project_brain.brain_db: session migration table failed: no such table: sessions
ERROR project_brain.brain_db: session migration table failed: no such table: memories
```
DB 正常運作，但 ERROR log 令使用者誤以為初始化失敗。

**根本原因（三層）**：

1. **guard 條件不夠精確**（`setup_wizard.py:126`）
   ```python
   legacy = ["knowledge_graph.db","session_store.db","events.db"]
   if any((brain_dir / f).exists() for f in legacy):
       r = db.migrate_from_legacy(brain_dir)
   ```
   只要其中一個檔案存在就觸發完整的 `migrate_from_legacy()`，包含嘗試讀取 `sessions`/`memories` 表。

2. **表存在性未先驗證**（`brain_db.py:1963–1965`）
   ```python
   for tbl in ("sessions", "memories"):
       for row in old.execute(f"SELECT * FROM {tbl}").fetchall():
   ```
   直接 SELECT，未先查 `sqlite_master` 確認表存在。舊版 `session_store.db` schema 可能無這兩張表（例如早期版本只有單一表，或檔案是部分初始化的空 DB）。

3. **錯誤等級不對**（`brain_db.py:1975`）
   ```python
   except Exception as _e: logger.error("session migration table failed: %s", _e)
   ```
   "找不到舊版表" 是預期情境，應為 `logger.debug`，而非 `logger.error`（ERROR 讓 CI/使用者誤判）。

**修法（三步，各自獨立可部署）**：

**Step A — 表存在性先驗（最小改動，立即消除誤報）**
```python
# brain_db.py:1963 前加入
existing_tables = {
    row[0] for row in old.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
}
for tbl in ("sessions", "memories"):
    if tbl not in existing_tables:
        logger.debug("Legacy session_store.db: table '%s' not found, skip", tbl)
        continue
    for row in old.execute(f"SELECT * FROM {tbl}").fetchall():
        ...
```

**Step B — 降低 log 等級**
```python
# brain_db.py:1975
except Exception as _e:
    logger.debug("session migration table failed: %s", _e)  # was: logger.error
```

**Step C — guard 加冪等保護（防止重複 migration）**
```python
# setup_wizard.py:126，加已遷移記錄
if any((brain_dir / f).exists() for f in legacy):
    already = db.conn.execute(
        "SELECT value FROM brain_meta WHERE key='legacy_migrated'"
    ).fetchone()
    if not already:
        r = db.migrate_from_legacy(brain_dir)
        db.conn.execute(
            "INSERT OR REPLACE INTO brain_meta(key,value) VALUES('legacy_migrated','1')"
        )
        db.conn.commit()
        if r["nodes"] > 0:
            print(f"  {G}OK{R}  Migrated legacy data  ({r['nodes']} nodes)")
    # else: 已遷移過，靜默略過
```

**驗收條件**：
- `brain init`（已存在 DB）不再輸出任何 ERROR log
- `brain init`（全新目錄）行為不變
- `session_store.db` 含 `sessions` 表時仍能正常遷移資料
- `session_store.db` 不含 `sessions`/`memories` 表時靜默略過（debug log）
- 重複執行 `brain init` 不會重複 migration

**優先修**：Step A + Step B（5 分鐘改動，立即消除誤報）；Step C 為選做優化。

---

## P2 — 擱置

### TEST-04 — WebUI 測試覆蓋率

WebUI 測試覆蓋率 < 12%，`scope` 欄位 migration 不同步導致測試無法穩定通過。
暫時擱置，等待 WebUI 架構穩定後處理。

### FEAT-08 — WebUI 節點行內編輯

WebUI 節點支援直接行內編輯（不需跳轉 CLI），提升維護體驗。
暫時擱置，與 TEST-04 一起處理。

---

## P2 — 擱置（續）

### REV-01 — 量化對照實驗 Layer 2/3

需要線上數據（至少 30 天使用記錄）才能進行有效的 Layer 2（情節記憶）vs Layer 3（語意知識）查準率對照實驗。
等待足夠數據後啟動。

### REV-02 — 衰減效用對比測試

衰減引擎對知識查準率的效用驗證需要 90 天歷史數據。
等待足夠數據後啟動。
