# Project Brain — 改善規劃書

> **當前版本**：v0.24.0（2026-04-06 — MEM-07~10 memdir 啟發改善完成）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。
> **分析基準**：v0.24.0 903 passed / 5 skipped（45 unit tests in test_mem_improvements.py）

---

## 優先等級

| 等級 | 說明 | 目標版本 |
|------|------|---------|
| **P1** | 明確影響正確性或安全性，應優先處理 | v0.22.0 ✅ |
| **P2** | 影響核心功能品質，計劃排入 | v0.23.0 |
| **P3** | 長期願景、低頻路徑、實驗性 | 評估中 |

---

## 矩陣優先總覽

### 已完成（v0.24.0）

| 優先 | ID | 影響摘要 | 象限 | 狀態 |
|------|----|---------|------|------|
| **P2** | MEM-07 | 新鮮度基準改為 `updated_at`（修正 MEM-04） | ⚡ 快速獲益 | ✅ v0.24.0 |
| **P2** | MEM-08 | `_SonnetSelector` 改用 `tool_use` + 索引（防幻想 ID） | 🎯 高價值 | ✅ v0.24.0 |
| **P2** | MEM-09 | 新鮮度警告文字強化（`file:line` + `grep` 驗證提示） | ⚡ 快速獲益 | ✅ v0.24.0 |
| **P3** | MEM-10 | `alreadySurfaced` 前移至 AI 選取前（5-slot 全用於新知識） | 🔵 填空 | ✅ v0.24.0 |
| **P1** | AUTO-01 | PostStop hook 接通 `from_git_commit()` 自動觸發 | 🎯 高價值 | ✅ v0.23.0 |
| **P1** | AUTO-02 | `complete_task` 接通 `from_session_log()` + title 修復 | ⚡ 快速獲益 | ✅ v0.23.0 |
| **P2** | AUTO-03 | `EXTRACTION_PROMPT` 改用 `tool_use` 結構化輸出 | ⚡ 快速獲益 | ✅ v0.23.0 |
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

---

## 第三波改善：知識生產斷路修復（AUTO-01~03）

> **背景**：程式碼審計發現 `KnowledgeExtractor`（`extractor.py`）已完整實作，
> `complete_task` MCP 工具也已存在，但兩條知識生產路徑都有關鍵斷路，
> 導致 KB 無法自動累積知識。修復成本低，收益高。

---

### 現況診斷：兩條路徑都斷了

```
路徑 A（Session）:  complete_task ─→ inline 寫節點
                    品質：差（title = content[:80] 截斷，無 LLM 提煉）
                    觸發：不可靠（LLM 需記得呼叫）

路徑 B（Git）:      from_git_commit() ─→ 高品質節點
                    品質：高（LLM 分析 diff，提取病因）
                    觸發：從不自動（只有手動 CLI）

from_session_log(): 為 complete_task 而寫（docstring 明確標注），
                    但 complete_task 有自己的 inline 邏輯 → 死碼
```

---

### AUTO-01 — PostStop Hook 接通 Git 路徑

**優先**：P1　**影響**：🔴 高（解鎖自動知識生產）　**工時**：1 小時

#### 問題

`from_git_commit()` 是品質最高的提取路徑，但只有手動執行 `brain extract` 時才觸發。每次 commit 後需要開發者主動呼叫，實際上從不發生。

#### 解決方案

**Step 1：在 `settings.json` 加入 PostStop hook**

```json
"hooks": {
  "Stop": [{
    "matcher": "",
    "hooks": [{
      "type": "command",
      "command": "cd \"${BRAIN_WORKDIR}\" && git diff --quiet HEAD~1 HEAD 2>/dev/null || brain extract-commit HEAD --workdir \"${BRAIN_WORKDIR}\""
    }]
  }]
}
```

- `git diff --quiet HEAD~1 HEAD` 先確認有新 commit（避免無 commit 時空跑）
- `||` 確保只在有變更時才執行 extract

**Step 2：確認 `brain extract-commit` CLI 入口存在**

`cli_knowledge.py` 已有 `extract` 指令，需確認支援 `extract-commit <hash>` 子命令，或新增別名。

**Step 3：提取結果自動寫入 Brain**

`from_git_commit()` 回傳 `knowledge_chunks`，hook 腳本呼叫 `b.add_knowledge()` for each chunk，`confidence` 設為 `0.65`（auto:git-hook tag），等待 `mark_helpful` 確認後升至 `0.9`。

#### 影響

| 場景 | 舊版 | 新版 |
|------|------|------|
| 完成 commit 後 | KB 不變 | 自動提取 diff 中的 Pitfall/Decision |
| 開發者工作量 | 需手動呼叫 brain extract | 零額外操作 |
| 知識累積速度 | 依賴手動 | 每次 commit 自動觸發 |

#### 驗收條件

- PostStop 後執行 `brain status`，新增節點帶有 `auto:git-hook` tag
- 無新 commit 時 hook 靜默（不寫節點、不報錯）
- hook 失敗（如 API 不可達）不影響 Claude 正常停止

---

### AUTO-02 — `complete_task` 接通 `from_session_log()` 並修復 Title

**優先**：P1　**影響**：🔴 高（Session 路徑節點品質）　**工時**：1 小時

#### 問題

**問題 1：`from_session_log()` 是死碼**

`extractor.py` 的 `from_session_log()` docstring 寫明「Called by complete_task MCP tool」，但 `mcp_server.py` 的 `complete_task` 有自己的 inline 邏輯，從未呼叫它。兩份相同邏輯，維護負擔加倍，且 inline 版本品質更差。

**問題 2：title = content[:80]**

```python
# mcp_server.py:827 — 現況
title = content[:80].strip()
```

產生的節點 title 是 content 截斷，例如：
- content: `"FTS5 sync bypass: _add_node_with_date() 用 raw SQL INSERT 繞過 FTS5 index sync，導致搜尋找不到節點。修復方式：改用 db.add_node() 後再 UPDATE created_at"`
- title（現況）: `"FTS5 sync bypass: _add_node_with_date() 用 raw SQL INSERT 繞過 F"`

FTS5 和向量召回都依賴 title，這種 title 實際上無法被正確召回。

#### 解決方案

**Step 1：`complete_task` 改用 `from_session_log()`**

```python
# mcp_server.py — 替換 inline 邏輯
from project_brain.extractor import KnowledgeExtractor

extractor = KnowledgeExtractor(workdir=str(b.workdir))
extracted = extractor.from_session_log(
    task_description=task_desc,
    decisions=_decisions,
    lessons=_lessons,
    pitfalls=_pitfalls,
    source=f"session:{datetime.now(timezone.utc).date()}",
)
for chunk in extracted.get("knowledge_chunks", []):
    node_id = b.add_knowledge(
        title=chunk["title"],
        content=chunk["content"],
        kind=chunk["type"],
        tags=chunk.get("tags", []) + ["auto:complete_task"],
        confidence=chunk.get("confidence", 0.8),
    )
    created_ids.append(node_id)
```

**Step 2：`from_session_log()` title 改為第一句話**

```python
# extractor.py — from_session_log()
# 現況：title = content[:60]（截斷）
# 修正：取第一個句號/換行前的內容，最多 60 字
title = re.split(r'[。.！!？?\n]', decision.strip())[0][:60]
```

#### 影響

- `complete_task` 產生的節點 title 變為可讀且可召回的短句
- `from_session_log()` 從死碼變為唯一實作，消除重複邏輯
- 維護時只需改一處

#### 驗收條件

- `complete_task(decisions=["FTS5 sync bypass 原因是 raw SQL 繞過 index"])` 產生的節點 title 不是截斷字串
- `brain search "FTS5 sync"` 能召回上述節點
- 舊有 VISION-01 auto-feedback 邏輯不受影響

---

### AUTO-03 — `EXTRACTION_PROMPT` 改用 `tool_use` 結構化輸出

**優先**：P2　**影響**：🟡 中（Git 路徑解析穩健性）　**工時**：半天

#### 問題

`extractor.py` 的 `_call()` 使用 raw `json.loads()`：

```python
text = re.sub(r"```json\n?", "", text)  # 手動清 markdown
text = re.sub(r"```\n?", "", text)
return json.loads(text.strip())          # 仍然脆弱
```

LLM 在 `from_git_commit()` 路徑回應時偶爾夾雜前言文字，導致解析失敗，`_call()` 捕捉 exception 後回傳空 `knowledge_chunks`，白費一次 API 呼叫。

這是 MEM-08（AI 選取器同款問題）在 extractor 裡的另一個實例。

#### 解決方案

Anthropic provider 改用 `tool_use`：

```python
_EXTRACT_TOOL = {
    "name": "store_knowledge",
    "description": "Store extracted knowledge chunks",
    "input_schema": {
        "type": "object",
        "properties": {
            "knowledge_chunks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type":       {"type": "string", "enum": ["Decision","Pitfall","Rule","Architecture"]},
                        "title":      {"type": "string", "maxLength": 80},
                        "content":    {"type": "string"},
                        "tags":       {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
                    },
                    "required": ["type", "title", "content", "confidence"]
                },
                "maxItems": 8
            }
        },
        "required": ["knowledge_chunks"]
    }
}

def _call(self, content: str, max_tokens: int = 1000) -> dict:
    if self.provider == "anthropic":
        resp = self.client.messages.create(
            model=self.model, max_tokens=max_tokens,
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "store_knowledge"},
            messages=[{"role": "user", "content": EXTRACTION_PROMPT + "\n\n---\n\n" + content[:4000]}]
        )
        tool_use = next(b for b in resp.content if b.type == "tool_use")
        return tool_use.input   # 保證是 dict，不含前言
    # OpenAI-compatible 路徑保持 json.loads（Ollama 尚未全面支援 tool_use）
    ...
```

#### 影響

| 指標 | 舊版 | 新版 |
|------|------|------|
| Anthropic 路徑解析失敗率 | ~5–10% | ~0% |
| OpenAI/Ollama 路徑 | 不變（保留原有 json.loads） | 不變 |
| confidence < 0.5 過濾 | prompt 中說明，LLM 自行判斷 | schema 強制 0–1 範圍 |

#### 驗收條件

- mock LLM 回傳含前言的 JSON，`_call()` 仍能正確解析
- `from_git_commit()` 空回傳率在測試中降至 0
- OpenAI-compatible provider 路徑行為不變

---

## 依賴鏈（AUTO-01~03）

```
AUTO-02 (from_session_log 接通) ──→ 無依賴，可獨立實作
AUTO-03 (tool_use 結構化輸出)   ──→ 無依賴，可獨立實作
AUTO-01 (PostStop hook)         ──→ AUTO-03（hook 呼叫 from_git_commit，需先修穩定性）

建議實作順序：AUTO-02 → AUTO-03 → AUTO-01
```

---

## 第二波改善：吸收 Claude Code memdir 優點（MEM-07~10）

> **背景**：深入閱讀 Claude Code memdir 原始碼（8 個 TypeScript 檔案）後，發現 v0.22.0
> 的實作與 memdir 設計仍有四項差距。以下為修正與強化規劃。

---

### MEM-07 — 新鮮度基準改為 `updated_at`（修正 MEM-04）

**優先**：P2　**影響**：🟡 中（警告準確性）　**工時**：2 小時

#### 問題

MEM-04 的新鮮度計算使用 `created_at`：

```python
days = (datetime.now() - created_at).days
```

但知識節點可能在建立後被多次更新（`add_knowledge` 覆寫 content / confidence）。一個「建立於 180 天前但上週剛驗證更新過」的節點，仍會顯示「⚠ 此知識建立於 180 天前」，造成誤警。

#### memdir 做法

`memoryFreshnessText(mtimeMs)` 使用**檔案的修改時間（mtime）**，而非建立時間。只要記憶檔被碰過（哪怕只是 `add_note`），mtime 就更新，警告消失。

> **memdir 閾值**：> 1 天即警告（適合高頻 session 場景）。
> **Project Brain 現況**：30 天閾值（適合跨 session 長期知識庫）。維持 30 天，只改基準欄位。

#### 解決方案

**Step 1：`_freshness_note()` 改用 `updated_at`**

```python
# context.py
def _freshness_note(node: NodeDict) -> str:
    ts = node.get('updated_at') or node.get('created_at', '')
    try:
        dt = datetime.fromisoformat(ts.replace(' ', 'T'))
        days = (datetime.now(timezone.utc) - dt.replace(tzinfo=timezone.utc)).days
    except Exception:
        return ''
    if days <= FRESHNESS_WARN_DAYS:
        return ''
    return (
        f'\n> ⚠ 此知識最後更新於 {days} 天前，'
        f'引用前請確認仍適用於當前架構。'
    )
```

**Step 2：確認 `NodeDict` 包含 `updated_at` 欄位**

`get_context_nodes()` 的 SELECT 需包含 `updated_at`（目前 `brain_db.py` 的 `list_nodes()` 已有此欄位，確認 context 路徑也一併讀取）。

#### 驗收條件

- 180 天前建立、30 天前更新的節點 → **無警告**
- 180 天前建立、未更新的節點 → **有警告（180 天）**
- `test_mem_improvements.py` 更新 `TestMEM04FreshnessWarning`：加入「更新後警告消失」測試案例

---

### MEM-08 — AI 選取器輸出改為結構化 JSON Schema（強化 MEM-01）

**優先**：P2　**影響**：🔴 高（選取器穩健性）　**工時**：半天

#### 問題

MEM-01 的 `SonnetSelector` / `OllamaSelector` 目前使用 `json.loads(resp.content[0].text)` 解析輸出：

```python
raw = json.loads(resp.content[0].text)
return raw.get("selected", [])[:5]
```

LLM 回應可能夾雜前言、markdown 程式碼塊（` ```json `）、或多餘文字，導致 `json.loads` 拋 `JSONDecodeError`，直接 fallback 到 `KeywordSelector`，白費 API 費用。

#### memdir 做法

`findRelevantMemories.ts` 使用 `output_format: { type: 'json_schema', json_schema: {...} }` 強制 Sonnet 輸出符合 schema 的 JSON：

```typescript
output_format: {
  type: 'json_schema',
  json_schema: {
    name: 'selected_memories',
    schema: {
      type: 'object',
      properties: {
        selected_indices: { type: 'array', items: { type: 'number' } }
      },
      required: ['selected_indices'],
      additionalProperties: false
    },
    strict: true
  }
}
```

使用**索引**（而非字串 ID）避免 LLM 幻想出不存在的 ID。

#### 解決方案

**Step 1：`SonnetSelector` 改用 `tool_use` 強制結構化輸出**

Anthropic Python SDK 使用 `tools` + `tool_choice` 達到相同效果：

```python
class SonnetSelector:
    _TOOL = {
        "name": "select_nodes",
        "description": "Select relevant knowledge node indices",
        "input_schema": {
            "type": "object",
            "properties": {
                "selected_indices": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "maxItems": 5,
                    "description": "0-based indices of selected candidates"
                }
            },
            "required": ["selected_indices"]
        }
    }

    def select(self, task: str, candidates: list[dict]) -> list[str]:
        manifest = _build_manifest(candidates)  # 含 index 前綴
        resp = self._client.messages.create(
            model="claude-haiku-4-5-20251001",   # 成本最低，夠用
            max_tokens=128,
            tools=[self._TOOL],
            tool_choice={"type": "tool", "name": "select_nodes"},
            messages=[{"role": "user", "content": _SELECT_PROMPT.format(
                task=task, manifest=manifest
            )}]
        )
        tool_use = next(b for b in resp.content if b.type == "tool_use")
        indices = tool_use.input.get("selected_indices", [])
        return [candidates[i]['id'] for i in indices if i < len(candidates)]
```

**Step 2：`OllamaSelector` 使用 Ollama `format` 參數**

```python
class OllamaSelector:
    def select(self, task: str, candidates: list[dict]) -> list[str]:
        manifest = _build_manifest(candidates)
        resp = self._client.chat(
            model=self._model,
            format={
                "type": "object",
                "properties": {
                    "selected_indices": {
                        "type": "array",
                        "items": {"type": "integer"}
                    }
                },
                "required": ["selected_indices"]
            },
            messages=[{"role": "user", "content": _SELECT_PROMPT.format(
                task=task, manifest=manifest
            )}]
        )
        indices = json.loads(resp['message']['content']).get("selected_indices", [])
        return [candidates[i]['id'] for i in indices if i < len(candidates)]
```

**Step 3：`_build_manifest` 加入索引編號**

```python
def _build_manifest(candidates: list[dict]) -> str:
    lines = []
    for i, n in enumerate(candidates):
        desc = n.get('description') or n['title']
        lines.append(f"[{i}] ({n['type']}) {n['title']} — {desc}")
    return "\n".join(lines)
```

#### 影響

| 指標 | 舊版 | 新版 |
|------|------|------|
| JSON 解析失敗率 | ~5–15%（LLM 前言） | ~0%（強制 schema） |
| 幻想 ID 問題 | 可能出現不存在的 ID | 改用索引，不可能越界 |
| Fallback 頻率 | 解析失敗即 fallback | 只在 API 不可達時 fallback |

#### 驗收條件

- `SonnetSelector.select()` 在 mock LLM 回傳含前言的 JSON 時，仍能正確解析
- `_build_manifest` 輸出每行含 `[index]` 前綴
- `test_mem_improvements.py` 新增：`TestMEM01AISelect::test_structured_output_index_based`

---

### MEM-09 — 新鮮度警告文字強化（直接採用 memdir 措辭）

**優先**：P2　**影響**：🟡 中（Agent 行為品質）　**工時**：30 分鐘

#### 問題

MEM-04 的警告文字：
> ⚠ 此知識建立於 N 天前，引用前請確認仍適用於當前架構。

這是泛用提醒，但沒有說明 **什麼最容易過期**——導致 Agent 仍可能直接引用過時的 `file:line` 位置。

#### memdir 做法

```
This memory is 47 days old. Memories are point-in-time observations,
not live state — claims about code behavior or file:line citations may
be outdated. Verify against current code before asserting as fact.
```

三個關鍵設計：
1. **明確說明過期的東西**：`file:line citations`（最常過期的具體類型）
2. **明確說明驗證方法**：`verify against current code`（告訴 Agent 該怎麼做）
3. **框架定位**：`point-in-time observations, not live state`（認知框架，不只是警告）

#### 解決方案

直接採用 memdir 措辭並翻譯為中文（保留英文原文於中英混合文件中）：

```python
# context.py
def _freshness_note(node: NodeDict) -> str:
    ts = node.get('updated_at') or node.get('created_at', '')
    # ... 計算 days ...
    if days <= FRESHNESS_WARN_DAYS:
        return ''
    return (
        f'\n> ⚠ 此知識最後更新於 **{days} 天前**。'
        f'知識節點是時間點快照，非即時狀態——'
        f'程式碼行為描述或 `file:line` 引用可能已過時。'
        f'引用前請以 `grep` / `Read` 工具驗證現況。'
    )
```

注意：此改善依賴 MEM-07（改用 `updated_at`），應同步實作。

#### 影響

Agent 看到警告時會：
- 不直接複製貼上 `file:line` 位置
- 在引用程式碼行為前先 grep 確認
- 理解這是「快照」而非「當前真相」

#### 驗收條件

- 警告文字包含 `file:line` 關鍵詞
- 警告文字包含「驗證」或 `grep` 指引
- 更新 `test_mem_improvements.py::TestMEM04FreshnessWarning::test_freshness_note_contains_warning` 斷言新措辭

---

### MEM-10 — `alreadySurfaced` 前移至 AI 選取前（強化 MEM-03）

**優先**：P3　**影響**：🟢 低中（AI 選取器 5-slot 利用率）　**工時**：1 小時

#### 問題

MEM-03 的去重邏輯目前在 `ContextEngineer.build()` 裡，即 **AI 選取完後** 過濾：

```
recall 20 candidates
    → AI 選 5
        → build() 過濾 already_surfaced
            → 輸出（可能剩下 < 5 個）
```

若 AI 選出 5 個，其中 3 個已是 already_surfaced，最終只輸出 2 個——浪費了 AI 選取器的 5-slot 預算，也浪費了一次 API 呼叫。

#### memdir 做法

`findRelevantMemories(query, memoryDir, signal, recentTools, alreadySurfaced)` 在組 manifest 給 Sonnet **之前** 先過濾 `alreadySurfaced`：

```typescript
const unseenMemories = allMemories.filter(
    m => !alreadySurfaced.has(m.id)
);
// 只把 unseen 送入 Sonnet
const selected = await selectRelevantMemories(query, unseenMemories, signal, recentTools);
```

Sonnet 只看到「未曾出現的記憶」，5-slot 全部用在新知識上。

#### 解決方案

**Step 1：`get_context()` 在候選召回後、AI 選取前過濾**

```python
# engine.py
def get_context(self, task: str,
                exclude_ids: set[str] | None = None,
                ai_select: bool = False, ...) -> str:
    candidates = self._recall_candidates(task, limit=20)

    # ★ 前移：AI 選取前先排除已服務節點
    if exclude_ids:
        candidates = [c for c in candidates if c['id'] not in exclude_ids]

    if not ai_select or not candidates:
        return self._build_context(candidates[:5])

    selector = _resolve_selector()
    selected_ids = selector.select(task, candidates)  # 候選已乾淨
    selected = [c for c in candidates if c['id'] in selected_ids]
    return self._build_context(selected)
```

**Step 2：`ContextEngineer.build()` 保留 `exclude_ids` 參數作向後相容**

`build()` 的 `exclude_ids` 過濾改為「防禦性過濾」（理論上此時已無 already_surfaced 節點，但保留以防直接呼叫 `build()` 的場景）。

#### 影響

| 場景 | 舊版 | 新版 |
|------|------|------|
| session 內第 3 次查詢，已 served 15 個節點 | AI 選 5，其中 3 個被過濾，輸出 2 個 | AI 從 unseen 候選中選 5，輸出 5 個 |
| AI 選取器 API 費用 | 每次查詢固定 1 次 | 相同（仍 1 次），但品質更好 |

#### 驗收條件

- `test_mcp.py`：session 第 3 次查詢，回傳節點數量不低於 `min(unseen_count, 5)`
- `engine.py` 單元測試：傳入 `exclude_ids` 時，mock selector 的 `candidates` 參數不含被排除的節點

---

## 依賴鏈（MEM-07~10）

```
MEM-07 (updated_at 基準) ──→ MEM-09 (警告文字使用 updated_at)   依賴
MEM-08 ──→ 無直接依賴（可獨立實作）
MEM-10 ──→ MEM-01 + MEM-03（在已有架構上前移邏輯）

建議實作順序：MEM-07 → MEM-09 → MEM-08 → MEM-10
```

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
