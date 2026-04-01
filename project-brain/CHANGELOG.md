# Project Brain — 版本歷史

> 為 AI Agent 設計的工程記憶基礎設施

---

## v0.1.0（2026-04-01）— 首次公開發布

### 核心功能

- **三層記憶架構**：L1a 工作記憶（SessionStore）+ L2 情節記憶（git commits）+ L3 語意記憶（KnowledgeGraph）
- **六因子知識衰減**：F1 時間 × F2 技術版本差距 × F3 git 活動反衰減 × F4 矛盾懲罰 × F5 程式碼引用確認 + F7 查詢頻率反衰減
- **NudgeEngine**：主動風險提醒，零 LLM 成本（純 FTS5），任務開始與 git commit 後觸發
- **KnowledgeReviewBoard（KRB）**：自動提取知識進入人工審核暫存區，核准後才進 L3
- **MemoryConsolidator**：L1a 工作筆記自動提煉至 L3（成本感知：min_entries=3）
- **MemorySynthesizer**：L1+L2+L3 三層融合成戰術摘要，opt-in（BRAIN_SYNTHESIZE=1）
- **ConditionWatcher**：監控 package.json / pyproject.toml / Dockerfile 等信號，自動偵測知識失效條件
- **Priority Queue 上文組裝**：pinned×2.5 + confidence×0.35 + access_count×0.25 + importance×0.15，附 Token Budget 管理
- **Hybrid Search**：FTS5 BM25（0.4）+ 向量 cosine（0.6）混合評分
- **中文 N-gram 分詞**：FTS5 自動處理，無需外部分詞工具
- **MCP Server**：Claude Code / Cursor 直接讀寫知識庫
- **零外部依賴**：純 SQLite（WAL 模式），備份 = 複製一個文件

### CLI 命令（13 個）

`setup` / `add` / `ask` / `status` / `sync` / `scan` / `review` / `serve` / `webui` / `context` / `index` / `init` / `meta`

### MCP 工具（7 個）

`get_context` / `add_knowledge` / `search_knowledge` / `temporal_query` / `brain_status` / `mark_helpful` / `impact_analysis`

---

## v11.x（2026-01 — 2026-03）— 內部迭代

### v11.1（2026-03-31）
- `brain review` CLI 恢復（list / approve / reject）
- MemorySynthesizer 三層融合修復（engine.py self._workdir → self.workdir，MCP server 補上 Synthesizer 呼叫）
- `brain scan` 加入 `--all` 選項與進度條
- MCP server 啟動 NameError 修復（mcp import 時序問題）
- README.md 重寫（企業級開源格式）+ 學術定位章節（對比 Lore、MemCoder、MemGovern）

### v11.0（2026-02）
- Phase 1 完成：sqlite-vec 向量語意搜尋（純 C 擴充，零外部依賴）
- Hybrid Search 評分融合（FTS5 × 0.4 + Vector × 0.6）
- SpacedRepetitionEngine 整合 F7 因子（access_count 影響衰減速度）
- SemanticDeduplicator：add_knowledge 時自動過濾近重複（cosine > 0.85）

---

## v10.x（2025-10 — 2026-01）— 架構統一

### v10.10（2026-01）
- brain.db 統一儲存（合併原 6 個 SQLite 文件）
- BrainDB.migrate_from_legacy() 自動遷移舊資料
- KnowledgeValidator 三階段驗證（Rule → Code grep → LLM 語意）
- ConditionWatcher v8.0：結構化條件語言解析器

### v10.6（2025-12）
- L2 改為純 SQLite（移除 FalkorDB / Graphiti 依賴）
- status_renderer.py 分離，彩色終端輸出模組化

### v10.4（2025-11）
- 空間作用域（scope）隔離（P1-A）
- NudgeEngine v8.0（主動提醒，含 git commit 觸發）
- ContextResult 結構化回傳（P3-A）
- temporal_query(git_branch) 時光機查詢（P3-B）
- 因果鏈輸出（PREVENTS / CAUSES / REQUIRES，P1-B）

---

## 版本說明

`v0.1.0` 是首次對外公開版本，對應內部 v11.1 的穩定快照。
內部版本號（v10.x / v11.x）用於追蹤迭代進度，不對外公告。
