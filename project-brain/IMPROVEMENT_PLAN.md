# Project Brain — 改善規劃書

> **當前版本**：v0.20.0（2026-04-05）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。
> **分析基準**：874 tests collected；v0.19.0 所有 P1+P2+P3 已完成，867 passed / 5 skipped。

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P1** | 明確影響正確性或安全性，應優先處理 | v0.20.0 |
| **P2** | 影響核心功能品質，計劃排入 | v0.20.0–v0.21.0 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## 矩陣優先總覽

### 已完成（歷史記錄）

| 優先 | ID | 影響 | 狀態 |
|------|----|------|------|
| P1 | SEC-03 | API Key Timing Attack | ✅ v0.12.0 |
| P1 | BUG-D01 | 29 處靜默例外 | ✅ v0.12.0 |
| P1 | BUG-D02 | Embedder Cache 競態 | ✅ v0.12.0 |
| P1 | TEST-01 | 15 個失敗測試修復 | ✅ v0.12.0 |
| P1 | PERF-05 | Decay N+1 查詢 | ✅ v0.12.0 |
| P1 | BUG-E01 | `_search_batch` 截斷 False Negative | ✅ v0.12.0 |
| P2 | FEAT-07 | `backfill-git` git 歷史回填 + AI 審核 | ✅ v0.13.0–v0.19.0 |
| P2 | PERF-06 | `nodes(type, confidence DESC)` 複合索引 | ✅ v0.13.0 |
| P2 | BUG-D03 | KRB cache 永不 VACUUM | ✅ v0.13.0 |
| P2 | BUG-D04 | SessionStore FD 洩漏 | ✅ v0.13.0 |
| P2 | ARCH-07 | scope 推斷邏輯去重 | ✅ v0.13.0 |
| P2 | OBS-02 | Decay F1–F7 因子量測輸出 | ✅ v0.14.0 |
| P2 | OBS-03 | rollback_node() 審計記錄 | ✅ v0.15.0 |
| P2 | SEC-04 | Federation PII 過濾擴充 | ✅ v0.15.0 |
| P2 | REV-02 | 衰減效用對比測試 | → `tests/TEST_PLAN.md §7` |
| P3 | FEAT-05 | Analytics 時序圖表 + HTML 報告 | ✅ v0.16.0 |
| P3 | FEAT-06 | `brain doctor` 矛盾/deprecated 比例 | ✅ v0.16.0 |
| P3 | ARCH-08 | ConflictResolver 快取 TTL 驅逐 | ✅ v0.16.0 |
| P3 | TEST-02 | Decay 100K 節點負載測試 | ✅ v0.16.0 |
| P3 | TEST-03 | Chaos 硬編碼路徑移除 | ✅ v0.16.0 |

### 待辦（v0.20.0 目標）

| 優先 | ID | 影響 | 解決方案 | 阻塞依賴 | 象限 | 狀態 |
|------|----|------|---------|---------|------|------|
| **P1** | SEC-05 | `_brain_cache` 無鎖，並發 workdir 切換有競態 | 新增 `_cache_lock = threading.Lock()`；所有 `_brain_cache` 讀寫加鎖 | 無 | ⚡ 快速獲益 | ✅ v0.20.0 |
| **P1** | REL-01 | `update_node()` FTS 同步失敗後未 rollback，節點資料與 FTS 索引不一致 | FTS 區塊加 `try/except` 後補 `self.conn.rollback()` 並重新 raise | 無 | ⚡ 快速獲益 | ✅ v0.20.0 |
| **P2** | TEST-04 | `test_web_ui.py` 189 行覆蓋 1604 行 server.py（覆蓋率 < 12%）；信心分布、is_pinned、filterConf 完全無測試 | 補充 Flask test_client 整合測試：stats API、pin/unpin 持久化、conf_dist 結構、圖篩選 | 無 | 🎯 高價值 | ⏸ 擱置（功能穩定後再補） |
| **P2** | UX-01 | WebUI 篩選狀態（kind/信心/釘選/搜尋）刷新即失，大圖（200+ 節點）無法書籤 | 將篩選狀態序列化至 URL hash（`#kind=Rule&conf=hi&q=auth`）；`loadGraph` / `filterConf` 讀寫 `location.hash` | 無 | 📋 計劃執行 | 🔲 待辦 |
| **P2** | FEAT-08 | WebUI 純唯讀，節點內容只能 CLI 或直接改 DB；日常微調知識需跳出瀏覽器 | 節點面板新增「編輯」模式：可修改 title/content/confidence；`POST /api/node/<id>` 後端端點 | 無 | 📋 計劃執行 | ⏸ 擱置（維持唯讀設計） |
| **P3** | PERF-07 | `session_store.py` 多處 `SELECT *` 拉取完整 value blob，僅需 metadata 的場景浪費 I/O | 依需求指定欄位：list 操作用 `SELECT key, created_at, expires_at`，content 操作才 `SELECT *` | 無 | 🔵 填空 | 🔲 待辦 |
| **P3** | FEAT-09 | `brain backfill-git` 預設掃描 200 commits，大型專案無進度回饋，使用者不知道在跑 | Phase 1 每 10 commit 輸出一次進度（`\r[{i}/{total}] ...`）；`--limit 0` 表示不限制 | 無 | 🔵 填空 | 🔲 待辦 |
| **P3** | OBS-04 | `brain status` 只顯示 DB 檔案統計；無法確認 MCP server 是否真的在回應 | `brain health [--mcp-port N]`：做 TCP connect + 送 `ping` JSON-RPC，回報延遲或錯誤 | 無 | 🏗 長期 | 🔲 待辦 |

---

## 依賴鏈

```
SEC-05 ──→ 無依賴（mcp_server.py 模組鎖）
REL-01 ──→ 無依賴（brain_db.py 單一函式）

TEST-04 ──→ 無依賴（但驗收 SEC-05 / REL-01 修復的正確性）
UX-01   ──→ 無依賴（純前端 URL hash 序列化）
FEAT-08 ──→ 無依賴（新增後端端點 + 前端表單）

PERF-07 ──→ 無依賴（查詢最佳化，不改 schema）
FEAT-09 ──→ 無依賴（僅 cli_admin.py print 輸出）
OBS-04  ──→ 無依賴（新增 CLI 子指令）
```

---

## P1 — 正確性 / 安全性缺陷

### SEC-05 — `_brain_cache` 並發競態（mcp_server.py）

**問題**：`mcp_server.py:125`：

```python
_brain_cache: dict[str, Any] = {}   # ← 無鎖
```

`_resolve_brain()` 在多 workdir 環境下並發呼叫時（FastMCP 多執行緒）：

```python
# Line 156-158：read-check-write 非原子
if key not in _brain_cache:          # Thread A 通過檢查
    _brain_cache[key] = ProjectBrain(key)  # Thread B 也在寫入同一 key
```

對比 `_session_nodes` 已正確加鎖（`_snodes_lock`），`_brain_cache` 卻沒有。
CPython GIL 通常防止 dict 崩潰，但 **雙重初始化**（兩個 `ProjectBrain(key)` 同時建立）
仍會造成：
1. 重複開啟 SQLite WAL connection（可能觸發 `database is locked`）
2. 兩個 Brain 實例各自有不同快取狀態，後寫者覆蓋前者

**修復**：

```python
# mcp_server.py 頂層新增
_cache_lock = threading.Lock()

# _resolve_brain() 內改為
with _cache_lock:
    if key not in _brain_cache:
        try:
            _brain_cache[key] = ProjectBrain(key)
        except Exception:
            return brain
    return _brain_cache[key]
```

同樣模式應用於 `multi_brain_query()` 中的 `_brain_cache` 存取（line 1053–1055）。

**工時**：< 30 分鐘。**測試**：`test_mcp.py` 新增 concurrent workdir 切換測試。

---

### REL-01 — `update_node()` FTS 失敗後未 rollback（brain_db.py）

**問題**：`brain_db.py:537–549`：

```python
self.conn.execute(f"UPDATE nodes SET {', '.join(ups)} WHERE id=?", params)
# ↑ 節點已更新

if title is not None or content is not None:
    try:
        self.conn.execute("DELETE FROM nodes_fts WHERE id=?", ...)
        self.conn.execute("INSERT INTO nodes_fts ...", ...)
    except Exception as _e:
        logger.error("FTS index update failed: %s", _e)
        # ← 沒有 rollback！

self.conn.commit()  # 節點更新被 commit，但 FTS 索引可能是舊的
```

**後果**：FTS 索引與 nodes 資料不一致——節點 title/content 已更新，但
`search_nodes()` 的 FTS5 查詢仍返回舊內容，導致**搜尋遺漏已更新的節點**。

**修復**：

```python
try:
    self.conn.execute(f"UPDATE nodes SET {', '.join(ups)} WHERE id=?", params)
    if title is not None or content is not None:
        nt = title   if title   is not None else ex["title"]
        nc = content if content is not None else ex["content"]
        self.conn.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
        self.conn.execute(
            "INSERT INTO nodes_fts(id,title,content,tags) VALUES(?,?,?,?)",
            (node_id, self._ngram(nt), self._ngram(nc), ex.get("tags","[]"))
        )
    self.conn.commit()
except Exception as _e:
    self.conn.rollback()
    logger.error("update_node failed, rolled back: %s", _e)
    raise
```

**工時**：< 1 小時。**測試**：在 `test_core.py` 新增 FTS 一致性測試（更新後搜尋可命中）。

---

## P2 — 核心功能品質

### TEST-04 — WebUI 測試覆蓋率嚴重不足 ⏸ 擱置

**問題**：`tests/test_web_ui.py` 目前 **189 行**，覆蓋的是基本的 `/api/graph`、`/api/node/<id>/pin` 路徑。
但 `web_ui/server.py` 已成長至 **1604 行**，包含：

| 功能 | 是否有測試 |
|------|-----------|
| `/api/stats` conf_dist 結構 | ❌ |
| `is_pinned` 釘選持久化（pin → reload → 仍釘選） | ❌ |
| `filterConf` 節點信心篩選 | ❌（純前端，需 Selenium / Playwright）|
| 節點 fallback schema（`cols2` 缺欄位修正） | ❌ |
| `/api/graph?kind=Rule` 篩選回傳 | ❌ |
| 大型圖（500+ 節點）回應時間 | ❌ |

v0.19.0 的三個 WebUI 修復（conf_dist 零值、pinned 零值、is_pinned 不持久）完全靠人工測試發現，下次回歸時仍有機會復發。

**修復方向**：

1. **後端端點測試**（優先，用 Flask `test_client`）：
   - `GET /api/stats` → 驗證 `conf_dist.hi + med + low + vlow == total_nodes`
   - `POST /api/node/<id>/pin` → `GET /api/node/<id>` 確認 `is_pinned=true`
   - `GET /api/graph?kind=Rule` → 所有回傳節點 `kind == "Rule"`
   - `GET /api/graph` → 回傳 `nodes` list，每個節點含 `confidence, is_pinned, scope`

2. **前端篩選測試**（選用，用 Playwright）：
   - `filterConf('hi')` → 只有 confidence >= 0.80 的節點 opacity = 0.88
   - `filterPinned()` → 只有 `is_pinned=true` 的節點可見

**工時**：後端測試約 1 天；Playwright 另計。

---

### UX-01 — WebUI 篩選狀態無 URL 持久化

**問題**：目前 JavaScript 狀態（`currentFilter`、`confFilter`、`pinnedFilter`、`searchInput`）
完全存活於記憶體。**重新整理** → 全部歸零。

使用場景：
- 查看 `kind=Rule` 的節點時，想把 URL 分享給同事 → 對方看到的是全部節點
- 已知低信心節點需要審核，整理一半去喝咖啡 → 回來後狀態消失

**修復**：將篩選狀態序列化至 `location.hash`：

```javascript
// 寫入 hash
function _syncHash() {
  const parts = [];
  if (currentFilter && currentFilter !== 'all') parts.push('kind=' + currentFilter);
  if (confFilter)   parts.push('conf=' + confFilter);
  if (pinnedFilter) parts.push('pin=1');
  const q = document.getElementById('search-input')?.value?.trim();
  if (q) parts.push('q=' + encodeURIComponent(q));
  history.replaceState(null, '', parts.length ? '#' + parts.join('&') : '#');
}

// 讀取 hash（頁面載入時）
function _restoreHash() {
  const h = location.hash.slice(1);
  if (!h) return;
  const p = Object.fromEntries(h.split('&').map(s => s.split('=')));
  if (p.kind) filterKind(p.kind);
  if (p.conf) filterConf(p.conf);
  if (p.pin)  filterPinned();
  if (p.q)    { searchInput.value = decodeURIComponent(p.q); searchInput.dispatchEvent(new Event('input')); }
}
```

`filterKind`、`filterConf`、`filterPinned`、search handler 結尾各呼叫 `_syncHash()`；
`loadGraph()` 完成後呼叫 `_restoreHash()`。

**工時**：< 2 小時（純前端）。

---

### FEAT-08 — WebUI 節點行內編輯 ⏸ 擱置

**問題**：知識庫管理完全依賴 CLI（`brain update`）或直接改 DB。
已有節點面板，但只能讀取。日常校正信心分數、修正錯誤描述需要離開瀏覽器。

**修復**：

1. **後端**：`web_ui/server.py` 新增：
   ```python
   # PATCH /api/node/<nid>
   # Body: {"title":str, "content":str, "confidence":float}
   def _route_node_patch(nid):
       data = request.get_json(silent=True) or {}
       # 白名單欄位
       allowed = {"title", "content", "confidence"}
       updates = {k: v for k, v in data.items() if k in allowed}
       if not updates:
           return jsonify({"error": "no valid fields"}), 400
       if "confidence" in updates:
           updates["confidence"] = max(0.0, min(1.0, float(updates["confidence"])))
       db.execute("UPDATE nodes SET ... WHERE id=?", ...)
       return jsonify({"ok": True})
   ```

2. **前端**：節點面板底部加「✏ 編輯」按鈕，點擊後 title/content 變為 `<textarea>`，
   confidence 變為 `<input type="range">`；「儲存」送 `PATCH /api/node/<nid>`，
   成功後 reload 該節點資料並更新圖中標籤。

3. **注意**：`server.py` 走 `brain_db` 路徑（非 `graph.py`），需確保 `update_node` 後
   REL-01 修復已上線（FTS 一致性保障）。

**工時**：後端 1 小時 + 前端 2 小時。阻塞：建議先完成 REL-01。

---

## P3 — 長期願景 / 低頻改善

### PERF-07 — `session_store.py` SELECT * 優化

**問題**：`session_store.py` 有 4 處 `SELECT *`（行 353、392、446、552），
在 list / count 場景下拉取完整 `value` TEXT blob（可達數 KB），實際只需 metadata。

**修復**：依場景替換：
- 列表 / 分頁操作 → `SELECT key, session_id, created_at, expires_at, size`
- 搜尋（需比對 value）→ 保留 `SELECT *`
- `get_session_entries()` → `SELECT *`（需要完整內容，不變）

**工時**：30 分鐘。

---

### FEAT-09 — `backfill-git` 進度顯示

**問題**：預設掃描 200 commits，執行時靜默。大型專案（500+ commits + `--limit 0`）
可能跑 5+ 分鐘，使用者不知道是否卡住。

**修復**：`cli_admin.py` Phase 1 迴圈：
```python
for i, ch in enumerate(to_process, 1):
    if i % 10 == 0 or i == len(to_process):
        print(f"\r  [{i}/{len(to_process)}] 處理中…", end="", flush=True)
    engine.learn_from_commit(ch)
print()  # 換行
```

`--limit 0` 的語意：不限制掃描深度（現行 `--limit N` 預設 200）。

**工時**：< 30 分鐘。

---

### OBS-04 — `brain health` MCP 連接狀態檢查

**問題**：`brain status` 回報 DB 統計，但無法確認 MCP server 是否在回應。
使用者啟動 Claude Code 後不確定 MCP 工具是否可用。

**修復**：`cli_admin.py` 新增 `cmd_health()`：

```python
def cmd_health(args):
    port = args.mcp_port or int(os.environ.get("BRAIN_MCP_PORT", "3000"))
    import socket, time
    t0 = time.monotonic()
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        s.close()
        ms = int((time.monotonic() - t0) * 1000)
        print(f"✅ MCP server 回應（port {port}，{ms}ms）")
    except OSError as e:
        print(f"❌ MCP server 無回應（port {port}）：{e}")
```

`cli_utils.py` 新增 `brain health [--mcp-port N]` 子指令。

**工時**：1 小時。

---

## 驗收標準（v0.20.0）

```
pytest tests/ -x -q
# 目標：≥ 880 passed（新增 TEST-04 測試後），0 failed
```

| 項目 | 驗收條件 |
|------|---------|
| SEC-05 | `test_mcp.py` 並發 workdir 切換不 deadlock / 不重複初始化 |
| REL-01 | `test_core.py` 更新節點後搜尋可命中新內容 |
| TEST-04 | `test_web_ui.py` ≥ 400 行；conf_dist、pin 持久化有獨立測試案例 |
| UX-01 | 手動驗收：`#kind=Rule` URL 載入後自動套用篩選 |
| FEAT-08 | 手動驗收：節點面板可編輯 title/content，儲存後圖中標籤即時更新 |
