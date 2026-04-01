# Project Brain — Master Document

> 這是 Project Brain 的唯一文件。所有設計決策、缺陷分析、開發計劃都在這裡。
> 其他 `.md` 文件是對外說明（README、INSTALL），這裡是對內設計記錄。

**版本**：v11.1  
**更新日期**：2026-03-31

---

## 目錄

1. [系統定位](#1-系統定位)
2. [架構現況](#2-架構現況)
3. [CLI 命令參考](#3-cli-命令參考)
4. [設計缺陷誠實清單](#4-設計缺陷誠實清單)
5. [Route B 技術路線圖](#5-route-b-技術路線圖)
6. [評分歷史（誠實版）](#6-評分歷史誠實版)
7. [下一輪計劃](#7-下一輪計劃)

---

## 1. 系統定位

### 目標

讓 AI Agent 針對企業級軟體專案建立長期記憶，依靠記憶持續開發，不重複踩坑，不遺忘架構決策。

### 現在是什麼（誠實）

**結構化工程日誌 + git hook 自動記錄 + MCP 讀取介面 + 語意搜尋（Phase 1）。**

不是：
- ✗ 動態學習的 AI 記憶系統（confidence 目前是靜態的）
- ✅ 語意搜尋（Phase 1: SQLite-vec + Embedding，有 Ollama/OpenAI 時全功能）
- ✗ 主動感知 Agent 行為（MCP 是被動協定，但已有 CLAUDE.md 解法）

### 核心價值

**讓 Agent 不要重複踩同一個坑。**

具體場景：你六個月前踩過 Stripe Webhook 冪等性問題。你忘了，但 Brain 記得。新 Agent 在實作退款功能時查詢 Brain，收到警告，不再踩坑。

---

## 2. 架構現況

### 資料庫結構（brain.db）

```
brain.db（單一文件，備份 = 複製一個文件）
├── nodes          L3 語意記憶（Rule/Decision/Pitfall/ADR/Note）
│   ├── scope      空間作用域（auth/payment_service/global）
│   └── confidence 確信度（0.0~1.0）
├── edges          因果關係邊（PREVENTS/CAUSES/REQUIRES）
├── episodes       L2 情節記憶（git commits，含 confidence）
├── temporal_edges 時序關係（支援時光機查詢）
├── sessions       L1a 工作記憶（當前任務）
└── node_vectors   （Phase 1 預留：向量搜尋）
```

### 記憶層次

| 層 | 內容 | 寫入方式 | 讀取方式 |
|----|------|---------|---------|
| L3 語意 | 規則、決策、踩坑 | `brain add` / MCP | `brain ask` |
| L2 情節 | git commit 歷史 | `brain sync`（自動）| `brain ask` / 時光機 |
| L1a 工作 | 當前任務 session | API | MCP |

### confidence 分級

| 來源 | confidence | 意義 |
|------|-----------|------|
| 人工驗證後加入 | 0.9 | 確定正確 |
| 人工直接加入 | 0.8 | 信任但未驗證 |
| Agent 發現加入 | 0.6 | 可能正確 |
| 自動 commit 提取 | 0.5 | 一般品質 commit |
| 低品質 commit | 0.2 | `fix`/`wip` 等 |

### 空間作用域（P1-A）

同一查詢詞，不同 scope 的結果：
```
brain ask "auth rule" --scope user_profile
→ 返回 user_profile + global，排除 payment_service
```

### MCP 工具

| 工具 | 說明 |
|------|------|
| `get_context(task, scope)` | 查詢相關知識（含因果鏈 + nudge）|
| `add_knowledge(title, content, kind, scope, confidence)` | Agent 寫入知識 |
| `temporal_query(at_time, git_branch)` | 時光機讀取 |
| `search_knowledge(query)` | 直接搜尋 |
| `brain_status()` | 記憶庫狀態 |

---

## 3. CLI 命令參考

**已安裝全局指令**：`pip install .` 後直接使用 `brain`。  
**多專案**：`brain` 自動從當前目錄往上找 `.brain/`，類似 git。

| 命令 | 說明 | 例子 |
|------|------|------|
| `brain setup` | 一鍵初始化 | `brain setup` |
| `brain add "筆記"` | 加入知識（快速）| `brain add "JWT 必須用 RS256" --kind Rule` |
| `brain ask "問題"` | 查詢知識 | `brain ask "JWT 怎麼設定"` |
| `brain status` | 記憶庫狀態 | `brain status` |
| `brain sync` | git hook 學習 | `brain sync --quiet` |
| `brain scan` | 掃描 git 歷史提取知識 | `brain scan --all` |
| `brain review` | 審查 KRB 暫存區知識 | `brain review list` |
| `brain serve` | REST API | `brain serve --port 7891` |
| `brain serve --mcp` | MCP Server | `brain serve --mcp` |
| `brain webui` | D3.js 視覺化 | `brain webui --port 7890` |
| `brain index` | 重建 FTS5 / 向量索引 | `brain index` |
| `brain init` | 低階初始化 | （一般用 setup 即可）|

**已移除命令**：`learn`, `distill`, `validate`, `export-rules`, `daemon` 等（v10.x 清理）

---

## 4. 設計缺陷誠實清單

*「任何號稱完美無缺的系統都是在實驗室裡的玩具，承認缺陷，正是走向偉大的開始。」*

### 已修補（讀取端缺陷）

| 缺陷 | 版本 | 說明 |
|------|------|------|
| P1-A 空間作用域污染 | v10.4 | scope 欄位 + 查詢過濾 |
| P1-B 圖譜退化扁平文字 | v10.4 | 因果鏈輸出（⛓ PREVENTS）|
| P2-A nudge 被動性 | v10.4 | nudge 附帶每次 MCP 回應 |
| P2-B git hook 無聲失敗 | v10.4 | 不依賴 LLM，直接記錄 |
| P3-A 空 Brain 狀態模糊 | v10.5 | ContextResult 結構化回傳 |
| P3-B 無時間作用域 | v10.5 | temporal_query(git_branch) |
| P4 記憶碎片拼接 | v10.6 | MemorySynthesizer（opt-in）|

### 結構性缺陷（Route B 計劃修補）

**S1：知識庫冷啟動**  
Brain 剛安裝是空的，Agent 查詢得到空字串，繞過 Brain。  
修補：Phase 0 首次體驗流程已改善（v10.10），Guide 引導加入種子知識。

**S2：三層記憶未對齊**  
L2 episode 和 L3 node 可能說同一件事，沒有連結，Agent 收到重複資訊。  
解法：FTS5 版本（現在可做）→ 向量版本（Phase 1 後），自動建立 `DERIVES_FROM` 邊。  
修補：Phase 1 前用 FTS5，Phase 1 後升級向量。

**S3：confidence 是靜態的**  
知識被用了多少次、有沒有幫到 Agent，系統不知道。  
解法：Phase 3 — 使用計數影響衰減速度，然後接 CI 反饋。

**S4：scope 需要手動指定**  
容易忘記 `--scope`，導致知識變成 global 污染所有查詢。  
解法：Phase 5 — 從當前目錄自動推導（1 天工作量）。

### 永久天花板（已接受，不修）

| 天花板 | 原因 |
|--------|------|
| 語意記憶 75% | Ontology 是研究問題，不是工程問題 |
| 企業就緒度 24% | SQLCipher/Audit/RBAC 刻意推遲，個人開發者不需要 |
| MCP 被動等待 | 企業級場景下 CLAUDE.md 已夠用，VS Code 擴充優先級低 |

---

## 5. Route B 技術路線圖

### 現在 vs 目標

| 能力 | 現在（v10.10）| Route B 目標 |
|------|-------------|-------------|
| 搜尋方式 | FTS5 關鍵字 | 向量語意搜尋 |
| Agent 感知 | CLAUDE.md 指示主動查詢 | IDE hook（可選）|
| 知識品質 | 靜態 confidence | 使用計數動態衰減 |
| 三層整合 | 獨立拼接 | 語意去重 + 連結 |
| scope 設定 | 手動指定 | 路徑自動推導 |
| 首次成功率 | 60%（改善中）| ≥ 80% |

### Phase 0：首次體驗（v10.10，進行中）

✅ `brain add → brain ask` 流程正確（Note 類型可被找到）  
✅ 移除所有 `brain scan` 引用  
✅ `brain add` 成功後顯示查詢提示  
📋 B-24：真實用戶路徑整合測試

### Phase 5：Scope 自動推導（1 天，下輪即做）

從當前工作目錄自動推導 scope：
```
cd /project/payment_service/
brain add "Stripe 冪等性"  →  scope 自動 = "payment_service"
```

### Phase 1：語意搜尋 SQLite-vec ✅（v11.0 已完成）

**為什麼優先**：這是整個 Route B 的基礎。修好後語意召回率 75% → 90%+。

技術方案：
- `sqlite-vec`：純 C 擴充，零外部依賴
- Embedding：Ollama `nomic-embed-text`（本地免費）→ OpenAI fallback
- Hybrid ranking：向量相似度 × 0.6 + FTS5 BM25 × 0.4
- 向後相容：沒有向量 = 降級 FTS5，永遠可用

新增表：
```sql
CREATE TABLE IF NOT EXISTS node_vectors (
    node_id TEXT PRIMARY KEY,
    vector  BLOB,   -- float32 × 768
    model   TEXT DEFAULT 'nomic-embed-text'
);
```

### Phase 2A：CLAUDE.md 注入（v11.0 同期，2 天）

`brain setup` 自動生成 `.claude/CLAUDE.md`：
```markdown
Always call the `get_context` MCP tool at the start of each task.
If Brain returns nudges, treat them as hard constraints.
```

**為什麼不做 VS Code 擴充套件（Phase 2B）**：  
企業級工作流是「開始任務前查詢 Brain」，不是「寫程式途中即時 nudge」。  
CLAUDE.md 兩天解決 80% 的需求，VS Code 擴充是後期可選項目。

### Phase 3：動態信心 ✅（v11.1 已完成）

第一步（使用計數）：
```python
access_count 高的節點 → 衰減速度慢
```

第二步（CI 反饋）：
```yaml
# .github/workflows/brain_feedback.yml
brain feedback --session-id $SESSION --result pass/fail
```

### Phase 4：三層記憶對齊 ✅（v11.1 已完成）

`brain sync` 寫入 episode 後，自動用向量相似度連結 L3 節點：
```python
similar_nodes = db.search_nodes_by_vector(ep_vector, threshold=0.85)
db.add_temporal_edge(ep_id, "DERIVES_FROM", node_id)
```

`context.py` 輸出去重：已連結的 episode 不重複輸出。

### 實作優先順序

```
Phase 0  首次體驗      ✅ v10.10（進行中）
Phase 5  Scope 自動    → 下輪（1 天）
Phase 1  語意搜尋      → v11.0（2 週）
Phase 2A CLAUDE.md     → v11.0 同期（2 天）
Phase 3  動態信心      → v11.1
Phase 4  三層對齊      → v11.1（需要 Phase 1）
Phase 2B VS Code       → 可選，後期
```

---

## 6. 評分歷史（誠實版）

### 評分方法說明

**實際可用度**不等於 Mock 測試通過率。

| 指標 | 說明 |
|------|------|
| Mock 通過率 | `returncode == 0`，不代表好用 |
| 真實首次成功率 | 真實用戶無輔助完成的步驟比例 |
| 誠實可用度 | Mock×0.4 + 真實×0.6 |

Ahern 首次使用數據（真實）：
- `pip install -e .` 失敗 → 已修（v10.6.2）
- git hook 格式錯誤 → 已修（v10.6.1）
- `brain status` 顯示「未初始化」→ 已修（v10.7）
- `brain add → brain ask` 找不到 → 已修（v10.10）

### 版本軌跡

```
v9.1   81%  召回率 17% → 100%
v10.0  83%  brain setup + 單一 brain.db
v10.4  84%  P1-P4 讀取端缺陷全修
v10.5  85%  ContextResult + 時光機
v10.7  84%  全局指令 + git-style 偵測（評分加入誠實真實度）
v10.9  71%  首次承認真實可用度 25%（修正評分計算）
v10.10 ?%   A-24 首次體驗改善（7/7 步驟通過）
```

### 分數天花板分析

```
組成：理論×0.20 + 工程×0.35 + 可用×0.30 + 企業×0.15

突破 80% 需要：
  實際可用度（真實）≥ 70%   → Route B Phase 0+5
  語意搜尋 90%+              → Route B Phase 1
  企業就緒度 24% → 48%       → 故意推遲，個人開發者不需要
```

---

## 7. 下一輪計劃

### v10.10 已完成

| 項目 | 說明 |
|------|------|
| Phase 0 首次體驗 | brain add → brain ask Note 類型修復 |
| Phase 5 Scope 自動 | 從目錄自動推導 scope |
| Phase 2A CLAUDE.md | brain setup 自動生成 Claude Code 指示 |
| 文件整合 | BRAIN_MASTER.md + 刪除 4 個過期文件 |

### 下一大版本（v11.0）

**Phase 1 語意搜尋（SQLite-vec，最高 ROI）**

B-24：真實用戶路徑整合測試

不用 Mock，走完整首次流程：
```python
def test_first_time_user_complete_flow(tmp_path):
    # 1. setup  2. add  3. ask（找到加入的知識）  4. commit → sync  5. ask 再次確認
    assert "RS256" in brain_ask_output  # 真實結果驗證
```

**Phase 5：Scope 自動推導**（1 天）
```python
def _infer_scope(current_file: str) -> str:
    # /project/payment_service/stripe.py → "payment_service"
```

### 下一大版本（v11.0）

Phase 1 語意搜尋（SQLite-vec）+ Phase 2A（CLAUDE.md 注入）

預期效果：
- 召回率 75% → 90%+
- Agent 每次對話自動帶上 Brain context
- 首次成功率目標 ≥ 80%

---

*維護者：Ahern*  
*這份文件是 Project Brain 的單一事實來源*  
*所有其他 `.md` 文件（README、INSTALL 等）是對外說明，以本文件為準*
