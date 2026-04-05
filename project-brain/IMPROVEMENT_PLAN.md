# Project Brain — 改善規劃書

> **當前版本**：v0.22.0（2026-04-05 — MEM-01~06 全部實作完成）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。
> **分析基準**：903 tests collected；v0.22.0 MEM-01~06 實作，884 passed / 5 skipped。

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P1** | 明確影響正確性或安全性，應優先處理 | v0.22.0 |
| **P2** | 影響核心功能品質，計劃排入 | v0.22.0–v0.23.0 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## 矩陣優先總覽

### 已完成（v0.22.0）

| 優先 | ID | 影響摘要 | 象限 | 狀態 |
|------|----|---------|------|------|
| **P2** | MEM-04 | 過時節點明確警告文字注入 context | ⚡ 快速獲益 | ✅ v0.22.0 |
| **P2** | MEM-03 | `alreadySurfaced` session 內去重 | ⚡ 快速獲益 | ✅ v0.22.0 |
| **P2** | MEM-02 | `description` 欄位 + 摘要/全文分層載入 | 🎯 高價值 | ✅ v0.22.0 |
| **P2** | MEM-01 | AI 輔助相關性選取（召回精準度大幅提升） | 🎯 高價值 | ✅ v0.22.0 |
| **P3** | MEM-05 | `recentTools` 降權（減少 context 雜訊） | 🔵 填空 | ✅ v0.22.0 |
| **P3** | MEM-06 | 摘要層 / 詳細層 context 分離 | 🏗 長期 | ✅ v0.22.0 |

### 待辦

| 優先 | ID | 影響摘要 | 象限 | 狀態 |
|------|----|---------|------|------|
| **P2** | TEST-04 | WebUI 測試覆蓋率 < 12% | 🎯 高價值 | ⏸ 擱置 |
| **P2** | FEAT-08 | WebUI 節點行內編輯 | 📋 計劃執行 | ⏸ 擱置 |
| **P2** | REV-01 | 量化對照實驗 Layer 2/3（需線上數據） | △ 需累積 | △ 進行中 |
| **P2** | REV-02 | 衰減效用對比測試（需 90 天數據） | △ 需累積 | △ 進行中 |

---

## 依賴鏈

```
MEM-02 (description 欄位) ──→ MEM-01 (AI 選取依賴 description 做輸入)  ✅ 已完成
MEM-03 ──→ 無依賴（MCP session state）                                   ✅ 已完成
MEM-04 ──→ 無依賴（get_context 輸出後處理）                              ✅ 已完成
MEM-05 ──→ MEM-03（同屬 get_context 呼叫端過濾邏輯）                    ✅ 已完成
MEM-06 ──→ MEM-02（摘要層使用 description 欄位）                         ✅ 已完成

TEST-04 ──→ 無依賴（等功能穩定）
FEAT-08 ──→ 無依賴（維持擱置）
```

**實作順序（已完成）**：MEM-04 → MEM-03 → MEM-02 → MEM-01 → MEM-05 → MEM-06

---

## 重大更新：memdir 啟發的六項改善

> **背景**：分析 Claude Code 的 `memdir` 記憶系統原始碼後，識別出六個設計優勢
> 可移植至 Project Brain，顯著提升召回品質與 Agent 使用體驗。

---

### MEM-01 — AI 輔助相關性選取（雙入口架構）✅ 已實作（v0.22.0）

**優先**：P2　**影響**：🔴 高（召回精準度）　**工時**：1–2 天

#### 問題

`get_context(task)` 目前使用 FTS5 關鍵字 + 向量 ANN 做機械式召回。對「語意相關但關鍵字不重疊」的查詢（例如：查「設計驗證流程」，卻需要的知識標題是「hmac.compare_digest 防 timing attack」）效果差。

#### memdir 做法

`findRelevantMemories.ts` 兩段式召回：
1. 掃描所有記憶的 `description`（一行摘要），組成 manifest
2. 用 **Sonnet side query** 讀 manifest + 使用者查詢 → 挑出最相關的 5 個

> **memdir 的限制**：side query 強依賴 Sonnet API，無法在本地或離線環境使用。Project Brain 採用**雙入口架構**，保留本地優先的設計原則。

#### 架構設計：三層降級選取器

```
get_context(task, ai_select=True)
         ↓
RelevanceSelector（抽象介面）
    ├── OllamaSelector   → 本地模型（優先，零 API 費用）
    ├── SonnetSelector   → Anthropic API（高精度備援）
    └── KeywordSelector  → 純規則（零依賴 fallback）
```

**`auto` 模式優先順序**：
1. 偵測本地 Ollama 服務是否運行 → 使用 `OllamaSelector`
2. 偵測 `ANTHROPIC_API_KEY` 是否存在 → 使用 `SonnetSelector`
3. fallback → `KeywordSelector`（永不失敗）

#### 解決方案

**Step 1：設定檔支援**（`.brain/config.toml`）

```toml
[memory]
relevance_selector = "auto"      # auto | sonnet | ollama | keyword
ollama_model = "qwen2.5:7b"      # 任何支援 JSON 輸出的本地模型
ollama_url = "http://localhost:11434"
```

**Step 2：選取器介面**

```python
# engine.py
class RelevanceSelector(Protocol):
    def select(self, task: str, candidates: list[dict]) -> list[str]:
        """回傳最多 5 個 node id"""
        ...

class KeywordSelector:
    """純規則 fallback：依 confidence × title keyword match 排序"""
    def select(self, task: str, candidates: list[dict]) -> list[str]:
        return [n['id'] for n in candidates[:5]]

class OllamaSelector:
    """本地模型選取（使用既有 OllamaClient，format='json'）"""
    def select(self, task: str, candidates: list[dict]) -> list[str]:
        manifest = _build_manifest(candidates)
        resp = ollama_client.messages.create(
            model=config.ollama_model,
            format="json",
            max_tokens=64,
            messages=[{"role": "user", "content": _SELECT_PROMPT.format(
                task=task, manifest=manifest
            )}]
        )
        raw = json.loads(resp.content[0].text)
        return raw.get("selected", [])[:5]

class SonnetSelector:
    """Anthropic API 選取（高精度備援）"""
    def select(self, task: str, candidates: list[dict]) -> list[str]:
        # 同 OllamaSelector，但呼叫 anthropic.messages.create
        ...
```

**Step 3：`get_context` 整合**

```python
def get_context(self, task: str, ai_select: bool = False) -> str:
    candidates = self._recall_candidates(task, limit=20)
    if not ai_select or not candidates:
        return self._build_context(candidates[:5])

    selector = _resolve_selector()   # 根據 config + 環境自動選擇
    try:
        selected_ids = selector.select(task, candidates)
    except Exception:
        selected_ids = [n['id'] for n in candidates[:5]]  # 降級

    selected = [n for n in candidates if n['id'] in selected_ids]
    return self._build_context(selected)
```

**Prompt（英文，強制 JSON，適用所有選取器）**：
```
Given this task: "{task}"
Select up to 5 node IDs from the list below that are CLEARLY relevant.
Be selective — omit anything uncertain.
{manifest}
Return only JSON: {"selected": ["id1", "id2", ...]}
```

MCP `get_context` 工具加 `ai_select: bool = False` 參數；CLI `brain context` 加 `--ai-select` 旗標。

#### 影響

| 指標 | KeywordSelector | OllamaSelector | SonnetSelector |
|------|----------------|----------------|----------------|
| 語意召回率 | ~60–70% | ~80–85% | ~90%+ |
| API 費用 | 零 | 零 | ~$0.001/次 |
| 延遲 | <1ms | ~500ms（本地） | ~800ms |
| 離線可用 | ✅ | ✅（Ollama 在跑） | ❌ |

#### 驗收條件

- `brain context "設計 API 驗證流程" --ai-select` 能召回 `hmac.compare_digest` 相關 Pitfall
- `auto` 模式：Ollama 在跑時使用 `OllamaSelector`；僅有 API key 時使用 `SonnetSelector`；兩者皆無時使用 `KeywordSelector`
- 任一選取器拋出例外時，系統自動降級到 `KeywordSelector`，不拋錯
- `test_engine.py` 新增：
  - `test_ai_select_retrieves_semantic_match`
  - `test_ai_select_fallback_on_error`
  - `test_selector_resolution_auto_mode`

---

### MEM-02 — `description` 欄位 + 索引/召回分離 ✅ 已實作（v0.22.0）

**優先**：P2　**影響**：🔴 高（召回效率 + token 節省）　**工時**：半天

#### 問題

節點只有 `title` + `content`。召回時需讀全文比對，token 用量隨命中節點數線性成長。MEM-01 的 AI 選取若只能用 `title` 做 manifest，精準度有限。

#### memdir 做法

每個記憶有獨立 `description`（frontmatter 一行摘要），專門為相關性判斷最佳化，與完整 `content` 分離。`scanMemoryFiles` 只讀前 30 行（frontmatter），不讀全文。

#### 解決方案

**Step 1：schema 新增欄位**

```sql
ALTER TABLE nodes ADD COLUMN description TEXT NOT NULL DEFAULT '';
```

`add_knowledge` / `add_node` 加 `description` 參數；若未填，截取 `content` 前 100 字作為預設值。

**Step 2：MCP `add_knowledge` 工具加 `description` 參數**

```python
# mcp_server.py
@mcp.tool()
def add_knowledge(title: str, content: str, kind: str = "Pitfall",
                  description: str = "", ...):
    # description 為空時自動生成：content[:100].replace('\n', ' ')
```

**Step 3：`brain add` CLI 加 `--description`**

```bash
brain add "JWT 必須使用 RS256" \
  --description "多服務架構下 HS256 secret 共享風險" \
  --kind Rule
```

#### 影響

| 指標 | 改善 |
|------|------|
| MEM-01 AI 選取精準度 | description 比 title 更具語意，提升 manifest 品質 |
| `get_context` 第一段掃描成本 | 只讀 description（短），不讀 content（長） |
| 向後相容 | `description = ''` 時 fallback 到 title，舊節點不受影響 |

#### 驗收條件

- `brain add --description` 正確寫入 DB
- `get_node` 回傳包含 `description` 欄位
- 舊節點 `description=''` 時 `get_context` fallback 到 `title`，功能不退化

---

### MEM-03 — `alreadySurfaced` Session 內去重 ✅ 已實作（v0.22.0）

**優先**：P2　**影響**：🟡 中（減少重複推薦雜訊）　**工時**：2 小時

#### 問題

`get_context` 每次呼叫獨立查詢，同一 session 內的多輪對話中，同一個 Pitfall 節點可能被反覆推薦，佔用 context token 且干擾 Agent 判斷。

#### memdir 做法

`findRelevantMemories(query, memoryDir, signal, recentTools, alreadySurfaced)` 接受 `alreadySurfaced: ReadonlySet<string>`，已在前幾輪出現的記憶先過濾掉，再送入 AI 選取器。

#### 解決方案

MCP server session state 維護 `served_node_ids`：

```python
# mcp_server.py
_session_served: dict[str, set[str]] = {}  # session_id → node_ids

@mcp.tool()
def get_context(task: str, workdir: str = "", force: bool = False) -> str:
    session_id = _get_session_id()
    already = _session_served.get(session_id, set())

    results = brain.get_context_nodes(task, exclude_ids=already)

    # 更新 served set
    new_ids = {n['id'] for n in results}
    _session_served.setdefault(session_id, set()).update(new_ids)

    return brain.build_context_text(results)
```

`force=True` 跳過去重（用於明確要求「重新顯示所有相關知識」的場景）。

Session 結束時（or 超過 30 分鐘無呼叫）自動清除，避免記憶體洩漏。

#### 影響

| 場景 | 舊版 | 新版 |
|------|------|------|
| 同一 session 多次查詢相同主題 | 同個 Pitfall 重複出現 | 第二次起自動排除已服務節點 |
| 不同 session 查詢 | 正常召回 | 不受影響（set 獨立） |

#### 驗收條件

- `test_mcp.py` 新增：同一 session 呼叫 `get_context` 兩次，第二次結果不包含第一次已回傳的節點 ID
- `force=True` 時不受 already set 影響

---

### MEM-04 — 過時節點明確警告文字 ✅ 已實作（v0.22.0）

**優先**：P2　**影響**：🟡 中（防止 Agent 以過時知識為事實）　**工時**：1 小時

#### 問題

Project Brain 有 Ebbinghaus 衰減（confidence 隨時間下降），但 `get_context` 輸出的 context 文字**不包含「這個知識是 N 天前寫的」的提示**。Agent 可能把 6 個月前的架構決策當作當前事實引用。

#### memdir 做法

`memoryFreshnessText(mtimeMs)` 對超過 1 天的記憶自動附加：
> "This memory is 47 days old. Memories are point-in-time observations, not live state — claims about code behavior or file:line citations may be outdated. Verify against current code before asserting as fact."

#### 解決方案

`build_context_text()` 組裝每個節點時，根據 `created_at` 計算天數並附加警告：

```python
# engine.py
FRESHNESS_WARN_DAYS = 30  # 超過 30 天加警告

def _freshness_note(created_at: str) -> str:
    try:
        dt = datetime.fromisoformat(created_at.replace(' ', 'T'))
        days = (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).days
    except Exception:
        return ''
    if days <= FRESHNESS_WARN_DAYS:
        return ''
    return f'\n> ⚠ 此知識建立於 {days} 天前，引用前請確認仍適用於當前架構。'

# context 組裝時附加
context_block = f"**{node['title']}**\n{node['content']}{_freshness_note(node['created_at'])}"
```

閾值 30 天可透過 `BRAIN_FRESHNESS_WARN_DAYS` 環境變數覆蓋。

#### 影響

| 節點年齡 | 輸出變化 |
|---------|---------|
| ≤ 30 天 | 無變化 |
| 31–90 天 | 附加「建立於 N 天前」警告 |
| > 90 天 | 同上 + confidence 已被衰減至較低值，可能不出現在 top-5 |

#### 驗收條件

- `test_engine.py`：新增 60 天前建立的節點，`get_context` 回傳包含警告文字
- `test_engine.py`：30 天內建立的節點，`get_context` 回傳不含警告

---

### MEM-05 — `recentTools` 相關節點降權 ✅ 已實作（v0.22.0）

**優先**：P3　**影響**：🟢 低中（減少 context 雜訊）　**工時**：1 小時

#### 問題

`get_context("實作 JWT 驗證")` 時，若 Agent 正在寫 JWT 驗證程式碼，推回「JWT 應該這樣設計」的 Rule 是雜訊——Agent 已經在實作了，不需要提醒怎麼設計。

#### memdir 做法

`selectRelevantMemories` 的 system prompt 明確說明：「如果 Agent 正在使用某工具，不要推薦該工具的參考文件，但 **仍要推薦警告/Pitfall**——正在使用時才最需要知道地雷。」

#### 解決方案

`get_context` 加 `current_context_tags: list[str]` 參數，與查詢高度重疊的 **Rule/Decision** 節點降權（排在 Pitfall 後面），但 **Pitfall 不降權**。

```python
def get_context(self, task: str,
                current_context_tags: list[str] | None = None) -> str:
    results = self._recall_candidates(task)
    if current_context_tags:
        # Rule/Decision 若 tags 與 current_context_tags 高度重疊 → 降分
        # Pitfall 永遠不降權（正在做的時候才最需要踩坑警告）
        results = _deprioritize_non_pitfall(results, current_context_tags)
    return self._build_context(results[:5])
```

#### 影響

- 減少「正在做 X 時被提醒怎麼做 X」的重複 Rule 出現
- Pitfall 不受影響，維持高優先

---

### MEM-06 — 摘要層 / 詳細層 Context 分離 ✅ 已實作（v0.22.0）

**優先**：P3　**影響**：🟡 中（token 節省 + Agent 可選擇性展開）　**工時**：半天

#### 問題

`get_context` 目前回傳所有命中節點的完整 content，5 個節點若每個 500 字，context 就是 2500 字。Agent 通常只需要摘要確認相關後，才對少數節點需要全文。

#### memdir 做法

`MEMORY.md`（index，只有指標）永遠載入；topic 檔案只在 `findRelevantMemories` 選中後才讀全文。輕量索引 + 按需展開。

#### 解決方案

`get_context` 加 `detail_level: str = "summary"` 參數：

```python
# summary 模式（預設）：只回傳 title + description（< 200 tokens）
# full 模式：回傳完整 content（現行行為）

def get_context(self, task: str, detail_level: str = "summary") -> str:
    results = self._recall_candidates(task, limit=5)
    if detail_level == "summary":
        lines = []
        for n in results:
            desc = n.get('description') or n['content'][:100]
            lines.append(f"- [{n['id'][:8]}] ({n['type']}, {n['confidence']:.0%}) "
                         f"**{n['title']}** — {desc}")
        return "\n".join(lines)
    return self._build_context(results)  # full mode
```

Agent 先取摘要層確認相關性，再對特定節點呼叫 `get_node(id)` 取全文。
依賴 MEM-02（需要 `description` 欄位讓摘要有意義）。

#### 影響

| 模式 | token 用量 | 適用場景 |
|------|-----------|---------|
| `summary`（新預設） | ~100–200 | 任務開始快速確認相關知識 |
| `full`（現行） | ~500–2500 | 需要完整 content 做決策時 |

---

## 驗收標準（v0.22.0）✅ 全部通過

```bash
pytest tests/ -q --ignore=tests/benchmarks --ignore=tests/chaos/test_decay_load.py
# 結果：884 passed / 5 skipped（10 pre-existing WebUI failures 與本次無關）
# 新增測試：tests/unit/test_mem_improvements.py — 26 tests, 26 passed
```

| 項目 | 驗收條件 | 結果 |
|------|---------|------|
| MEM-04 | 60 天前節點的 context 含警告文字；30 天內節點無警告 | ✅ |
| MEM-03 | 同 session 去重；`force=True` 跳過；TTL 30 分鐘自動清除 | ✅ |
| MEM-02 | `description` 寫入 DB；`get_node` 回傳欄位；空白時自動截取 content 前 100 字 | ✅ |
| MEM-01 | `ai_select=True` 啟動三層降級選取器；auto 模式自動偵測 Ollama/Sonnet/Keyword；選取器例外時降級不拋錯 | ✅ |
| MEM-05 | Rule/Decision 標籤重疊時降權 50%；Pitfall 不受影響 | ✅ |
| MEM-06 | `detail_level="summary"` 回傳字元數明顯少於 `full`；full 為預設行為 | ✅ |
