# SYNTHEX AI STUDIO — 技術架構說明

---

## 目錄

- [系統全貌](#系統全貌)
- [核心模組](#核心模組)
- [Agent 執行模型](#agent-執行模型)
- [WebOrchestrator 流水線](#weborchestrator-流水線)
- [AgentSwarm 並行系統](#agentswarm-並行系統)
- [Project Brain v4.0](#project-brain-v40)
- [記憶與 Context 管理](#記憶與-context-管理)
- [品質與可靠性](#品質與可靠性)
- [資料流總覽](#資料流總覽)

---

## 系統全貌

```
外部輸入
┌────────────────────────────────────────────────────────────┐
│  CLI（synthex.py）         Claude Code（CLAUDE.md）        │
│  python synthex.py ship    @NEXUS 設計架構                  │
└──────────────────────┬─────────────────┬───────────────────┘
                       │                 │
              ┌────────▼────────┐        │ 直接互動
              │ WebOrchestrator │        │
              │  12-Phase 流水線 │        │
              └────────┬────────┘        │
                       │                 │
              ┌────────▼─────────────────▼──────┐
              │           Agent Layer            │
              │  BaseAgent（全部 28 個 Agent）    │
              │  AgentSwarm（並行協作）           │
              └────────┬───────────────┬─────────┘
                       │               │
         ┌─────────────▼──┐   ┌────────▼──────────────┐
         │  Anthropic API  │   │  Project Brain v4.0    │
         │  Claude 模型    │   │  三層認知記憶系統       │
         │  Opus/Sonnet/   │   │  L1 + L2 + L3         │
         │  Haiku          │   └───────────────────────┘
         └────────────────┘

輸出
┌────────────────────────────────────────────────────────────┐
│  程式碼檔案    文件    git commit    測試報告    部署腳本   │
└────────────────────────────────────────────────────────────┘
```

---

## 核心模組

### `synthex.py` — CLI 主入口

所有命令的進入點，負責解析命令列參數並路由到對應的函數。

```
synthex.py
├── cmd_ship()          → WebOrchestrator.run()
├── cmd_discover()      → WebOrchestrator.discover()
├── cmd_agent()         → Agent 對話模式
├── cmd_do()            → Agent Agentic 模式
├── cmd_shell()         → 互動 Agentic Shell
├── cmd_brain_*()       → ProjectBrain 系列命令
└── ...（完整命令見 COMMANDS.md）
```

**設定儲存：** `~/.synthex_config.json`（預設工作目錄、API Key 等）

---

### `core/base_agent.py` — BaseAgent（901 行）

所有 Agent 的基底類別，提供：

**兩種工作模式：**

```python
# 對話模式：用 messages API，有完整 context
agent.chat("設計 API 架構")
→ client.messages.create(model, messages=[...])

# Agentic 模式：用工具，能操作檔案和執行命令
agent.agentic("實作登入功能")
→ client.messages.create(model, tools=[...], ...)
→ while tool_calls:
      執行工具 → 繼續對話
```

**CompactionManager（Context 長任務管理）：**

當 input tokens 超過閾值時，自動把歷史 context 壓縮成 Haiku 生成的語意摘要，避免 context window 耗盡：

```
正常對話 → 超過 150K tokens → CompactionManager 觸發
  → Haiku 把舊 context 壓縮成摘要
  → 用摘要取代舊的詳細 context
  → 繼續工作，不丟失關鍵資訊
```

**TokenBudget（成本追蹤）：**

```python
class TokenBudget:
    total_input_tokens:  int
    total_output_tokens: int
    total_cache_read:    int
    total_cost_usd:      float

    def within_budget(self, max_usd: float) -> bool: ...
```

每次 API 呼叫後自動更新，超過 `--budget` 設定值時中止執行。

---

### `core/config.py` — 集中模型管理

所有模型設定的單一真相來源（Single Source of Truth）：

```python
class ModelID(str, Enum):
    OPUS_46   = "claude-opus-4-6"      # 1M context，最高品質
    SONNET_46 = "claude-sonnet-4-6"    # 1M context，均衡
    SONNET_45 = "claude-sonnet-4-5"
    HAIKU_45  = "claude-haiku-4-5-20251001"  # 最快最廉價

class ModelTier(str, Enum):
    FLAGSHIP    = "flagship"    # Opus 4.6：NEXUS、ARIA、SIGMA
    STANDARD    = "standard"    # Sonnet 4.6：BYTE、STACK、ECHO...
    ECONOMY     = "economy"     # Haiku 4.5：RELAY、BRIDGE、WIRE...
    COMPACTION  = "compaction"  # Haiku 4.5：Context 壓縮（內部用）
```

修改模型只需改 `config.py`，不需要搜尋整個 codebase。

---

### `core/web_orchestrator.py` — 12 Phase 流水線（1753 行）

`/ship` 命令的核心引擎。

**Phase 管理：**

```python
class PhaseCheckpoint:
    """原子性寫入的斷點續跑機制"""
    def save(self, phase: int, data: dict) -> None:
        # 先寫 .tmp，成功後才 rename 覆蓋原檔
        # 防止中途崩潰導致資料損毀
        tmp_path = self.checkpoint_path.with_suffix('.tmp')
        tmp_path.write_text(json.dumps(data))
        tmp_path.rename(self.checkpoint_path)

    def load(self, phase: int) -> dict | None:
        # 自動從中斷點繼續，不重複 Phase
```

**AgentSwarm 並行（Phase 9+10）：**

BYTE（前端）和 STACK（後端）在 API 介面設計完成後並行執行，省 30-50% 時間：

```python
async def run_phase_9_10_parallel():
    tasks = [
        byte_agent.agentic_async(frontend_task),
        stack_agent.agentic_async(backend_task),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
```

---

### `core/swarm.py` — AgentSwarm（661 行）

多 Agent 並行協作的調度引擎。

**任務依賴圖（DAG）：**

使用 Kahn's Algorithm 進行拓撲排序，確保有依賴關係的 Agent 按正確順序執行：

```python
class AgentSwarm:
    def __init__(self, failure_policy: FailurePolicy):
        # FAIL_FAST：任一失敗立即中止所有
        # PARTIAL_OK：繼續執行，收集所有結果
        # SKIP_FAILED：跳過失敗的，繼續執行其他

    async def run(self, tasks: list[SwarmTask]) -> SwarmResult:
        order = self._topological_sort(tasks)  # Kahn's Algorithm
        for batch in order:
            # 同一批次的 Task 並行執行
            results = await asyncio.gather(*[run_task(t) for t in batch])
```

**部分失敗恢復（PARTIAL_OK 策略）：**

即使某個 Agent 失敗，其他 Agent 的結果仍然保留並返回。比如 BYTE 的前端失敗，STACK 的後端程式碼仍然可用。

---

### `core/tools.py` — Agent 工具集（1526 行）

Agentic 模式下 Agent 可以使用的工具，每個工具都有多層安全防護：

| 工具 | 說明 | 安全措施 |
|------|------|---------|
| `read_file` | 讀取檔案 | 路徑必須在 workdir 內 |
| `write_file` | 寫入檔案 | 自動建立目錄，路徑驗證 |
| `run_command` | 執行命令 | argv 陣列（非 shell=True）、黑名單過濾 |
| `search_files` | 全文搜尋 | 限制搜尋範圍、結果數量 |
| `list_dir` | 列出目錄 | 深度限制，不洩漏敏感路徑 |
| `move_file` | 移動檔案 | 路徑驗證、確認提示 |
| `delete_file` | 刪除檔案 | 必須確認（或 --yes）|
| `get_project_info` | 專案偵測 | 只讀，不修改 |

**命令安全過濾（`run_command` 的黑名單）：**

```python
DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+[/~]',        # 刪除根目錄
    r'curl\s+.*\|\s*bash',     # 管道執行遠端腳本
    r'>\s*/dev/sd',             # 覆蓋磁碟
    r'mkfs\.',                  # 格式化磁碟
    r'dd\s+if=',                # 磁碟操作
    r'chmod\s+777\s+/',         # 開放根目錄權限
    r':(){ :|:& };:',           # Fork Bomb
]
```

所有命令使用 `subprocess.run(argv_list, shell=False)` 執行，**不使用** `shell=True`，從根本上防止 Shell Injection。

---

### `core/rate_limiter.py` — 速率限制

Token Bucket 算法實作，防止 API 呼叫超過 Anthropic 速率限制：

```python
class TokenBucketRateLimiter:
    def acquire(self, tokens: int) -> float:
        """
        返回需要等待的秒數。
        超過速率上限時自動等待，不丟失請求。
        """

class CircuitBreaker:
    """
    故障隔離器：
    - 連續失敗 N 次後，開啟 Circuit（暫停請求）
    - 等待冷卻期後，嘗試半開（讓少量請求通過）
    - 請求成功後，恢復正常
    """
```

---

### `core/logging_setup.py` — 結構化日誌（264 行）

使用 `structlog` 輸出 JSON 格式的結構化日誌：

```python
# 開發環境：彩色的人類可讀格式
# Production 環境（SYNTHEX_ENV=production）：JSON 格式，可接入 ELK / Loki

logger.info("ship_phase_complete",
    phase=9, agent="BYTE",
    tokens=15234, cost_usd=0.042, elapsed_ms=8421)

# → {"event": "ship_phase_complete", "phase": 9, "agent": "BYTE",
#    "tokens": 15234, "cost_usd": 0.042, "elapsed_ms": 8421, ...}
```

**TokenGuard：** 整合進日誌系統，每次 API 呼叫完成後自動記錄 token 用量：

```python
class TokenGuard:
    """防止意外的超大 token 用量"""
    def warn_if_excessive(self, tokens: int, threshold: int = 100_000):
        if tokens > threshold:
            logger.warning("excessive_tokens", tokens=tokens)
```

---

## Agent 執行模型

### 對話模式（Chat Mode）

```
用戶輸入 → BaseAgent.chat()
    → 加入 system_prompt（角色定義）
    → 加入 Project Brain context（三層知識注入）
    → 加入歷史對話（最多 20 輪）
    → client.messages.create()
    → 解析回應
    → 儲存到 memory/<agent>_memory.json
    → 輸出給用戶
```

**記憶格式（`memory/<agent>_memory.json`）：**

```json
{
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "..."}
  ],
  "created_at": "2026-03-27T10:00:00Z",
  "last_updated": "2026-03-27T10:30:00Z"
}
```

### Agentic 模式（Tools Mode）

```
用戶任務 → BaseAgent.agentic()
    → 加入工具定義（read_file, write_file, run_command...）
    → API 呼叫
    → Claude 決定使用哪個工具
    → 執行工具（有安全檢查）
    → 把工具結果加回 messages
    → 繼續呼叫 API（直到 stop_reason = "end_turn"）
    → 輸出最終結果

最大工具呼叫迴圈：50 次（防止無限迴圈）
```

### 結構化輸出（GA 格式）

Phase 之間傳遞的資料使用 Claude 原生的結構化輸出（GA 格式，非 beta）：

```python
from core.advanced_tool_use import StructuredOutputParser

# 要求 Claude 輸出 JSON schema 定義的格式
result = StructuredOutputParser.parse(
    raw_response,
    schema={"type": "object", "properties": {...}},
)
# 解析失敗時自動 fallback 到 regex 提取
```

---

## WebOrchestrator 流水線

### Phase 間的資料傳遞

每個 Phase 產出結構化輸出，傳遞給下一個 Phase：

```
Phase 1（ARIA）→ task_confirmation（任務範疇）
    ↓
Phase 2（ECHO）→ prd（功能清單、AC、資料模型）
    ↓
Phase 3（LUMI）→ 驗證結果（通過 / 要求修改）
    ↓
Phase 4（NEXUS）→ architecture（技術選型、Schema、API 規格）
    ↓
Phase 5（SIGMA）→ feasibility（成本、風險評估）
    ↓
Phase 6（FORGE）→ setup_result（環境建立確認）
    ↓
Phase 7（SPARK）→ ux_design（用戶旅程、線框圖）
    ↓
Phase 8（PRISM）→ ui_system（Design Token、組件規範）
    ↓
Phase 9（BYTE）→ frontend_result（前端程式碼）
Phase 10（STACK）→ backend_result（後端程式碼）
    ↓（並行，Phase 9+10）
Phase 11（PROBE + TRACE）→ test_result（測試報告）
    ↓
Phase 12（SHIELD + ARIA）→ delivery（安全報告 + 交付文件）
```

### 斷點續跑（PhaseCheckpoint）

每個 Phase 完成後寫入 checkpoint 文件：

```
.synthex_checkpoint/
└── <任務 hash>.json   ← 包含已完成的 Phase 和輸出資料
```

下次執行相同任務（相同的需求字串），自動從上次中斷的 Phase 繼續，不重複已完成的工作。

---

## AgentSwarm 並行系統

### 任務圖（DAG）定義

```python
tasks = [
    SwarmTask(id="byte", agent=BYTE, deps=[]),       # 無依賴
    SwarmTask(id="stack", agent=STACK, deps=[]),      # 無依賴
    SwarmTask(id="probe", agent=PROBE, deps=["byte", "stack"]),  # 等兩者完成
]
```

### 失敗策略

| 策略 | 行為 | 適用場景 |
|------|------|---------|
| `FAIL_FAST` | 任一失敗立即中止所有 | 嚴格依賴、任一失敗結果無意義 |
| `PARTIAL_OK` | 繼續，收集所有成功結果 | 前後端並行，一個失敗另一個結果仍有用 |
| `SKIP_FAILED` | 跳過失敗的，繼續執行其他 | 可選的 Agent，失敗可以接受 |

### Async / Sync 邊界

```python
# WebOrchestrator 是 async 的
async def run_ship_pipeline():
    await swarm.run(tasks)

# 但 Agent 的 API 呼叫是同步的
def agent_execute():
    return anthropic.messages.create(...)

# 邊界處理：asyncio.to_thread() 包裹同步呼叫
await asyncio.to_thread(agent_execute)
```

---

## Project Brain v4.0

完整說明見 [PROJECT_BRAIN.md](PROJECT_BRAIN.md)。以下是與 orchestrator 的整合方式。

### 知識注入點

Project Brain 在兩個時機注入知識：

**1. 每個 Phase 開始前（自動）：**

```python
# WebOrchestrator 在每個 Phase 開始前
brain_context = brain.router.query(task_description)
phase_prompt = brain_context.to_context_string() + "\n\n" + original_prompt
```

**2. 每個 Phase 完成後（自動學習）：**

```python
# Phase 完成後
brain.router.learn_from_phase(
    phase    = 9,
    agent    = "BYTE",
    content  = phase_output,
    decision = "選擇 App Router 而非 Pages Router",
)
```

### 三層知識路由

```
router.query(task)
    ├── L1 SQLite FTS5    → <10ms   ← 本次任務即時踩坑
    ├── L2 Graphiti 混合  → <100ms  ← 歷史決策時序
    └── L3 SQLite + Chroma → <200ms  ← 深度語義知識
           ↓
    BrainQueryResult.to_context_string()
           ↓
    注入 Agent system prompt（<3,000 tokens）
```

---

## 記憶與 Context 管理

### 三層記憶架構

```
L1 工作記憶（session 級）
    儲存：本次任務即時資訊（踩坑、進展、決策）
    API：Anthropic Memory Tool（memory_20250818）
    後端：SQLite WAL + FTS5
    生命週期：可選持久化（v4.0 跨 session 持久化）
    查詢延遲：< 10ms

L2 情節記憶（專案級）
    儲存：決策的時序演化（「這個決策現在還有效嗎？」）
    API：Graphiti 時序知識圖譜
    後端：FalkorDB / Neo4j / TemporalGraph（降級）
    生命週期：專案週期內
    查詢延遲：< 100ms

L3 語義記憶（永久）
    儲存：深度踩坑記錄、業務規則、反事實分析
    API：SQLite FTS5 + Chroma 向量搜尋
    後端：.brain/knowledge_graph.db
    生命週期：永久（三維衰減管理信心）
    查詢延遲：< 200ms
```

### CompactionManager

當 Agent 執行長任務、context 積累到 150K tokens 時觸發：

```
context_size > 150K tokens
    ↓
CompactionManager.compact()
    ↓
Haiku 把前 N 輪對話壓縮成 2K token 的語意摘要
    ↓
用摘要取代舊的詳細 context
    ↓
繼續執行，不丟失關鍵資訊
```

**為什麼用 Haiku？** 壓縮本身不需要高品質推理，Haiku 又快又便宜，成本只有 Sonnet 的 1/10。

---

## 品質與可靠性

### 測試架構（139 個測試）

```
tests/test_core.py
├── TestSafeRun（7）         — shell injection、timeout、截斷
├── TestConversationHistory（3）
├── TestTokenGuard（3）
├── TestStructuredOutputParser（6）
├── TestToolRegistry（5）
├── TestDocContextAtomicWrite（3）
├── TestUrlSecurity（3）
├── TestConfig（7）           — ModelID、1M context、成本計算
├── TestStructuredOutputGA（6）
├── TestComputerUseSecurity（7）
├── TestSwarmFailureRecovery（8）
├── TestTokenBudgetV4（4）
├── TestCompactionManager（6）
├── TestPhaseCheckpointFixed（7）
├── TestEvalsGoldenDataset（7）
├── TestSwarmAsyncSafety（3）
├── TestBrainMemoryBackend（8）  — v3.0 L1
├── TestGraphitiAdapter（8）     — v3.0 L2
├── TestBrainRouter（9）         — v3.0
├── TestKnowledgeValidator（7）  — v4.0
├── TestKnowledgeFederation（8） — v4.0
├── TestKnowledgeDistiller（6）  — v4.0
├── TestSessionPersistence（4）  — v4.0
└── TestBrainV4Integration（4）  — v4.0
```

### Evals（品質評估框架）

```
evals/suites/
├── prd_quality.json         — PRD 完整性評估（ECHO 的輸出）
├── architecture_quality.json — 架構決策品質（NEXUS 的輸出）
├── security_quality.json    — 安全審查徹底性（SHIELD 的輸出）
└── code_quality.json        — 程式碼品質（BYTE + STACK 的輸出）
```

每個 case 定義：輸入 prompt → 期望輸出關鍵特徵 → 評分維度（1-5）。

詳見 [EVALS.md](EVALS.md)。

---

## 資料流總覽

### `ship` 命令完整資料流

```
用戶：python synthex.py ship "電商平台..."
    ↓
synthex.py：解析命令，呼叫 WebOrchestrator.run()
    ↓
WebOrchestrator
    ├── 讀取 PhaseCheckpoint（是否有未完成的相同任務？）
    ├── 初始化 ProjectBrain（如果 .brain/ 存在）
    │
    Phase 1（ARIA）
    ├── Project Brain context 注入（查詢 L1+L2+L3）
    ├── API 呼叫：claude-opus-4-6
    ├── 輸出：task_confirmation（JSON）
    ├── PhaseCheckpoint 儲存
    └── Project Brain 學習（learn_from_phase）
    ↓
    Phase 2（ECHO）
    ├── context = previous_phases + brain_context
    └── ...（依此類推）
    ↓
    Phase 9+10（AgentSwarm 並行）
    ├── BYTE task → asyncio.to_thread(byte.agentic)
    ├── STACK task → asyncio.to_thread(stack.agentic)
    └── gather() → 兩者完成才繼續
    ↓
    Phase 12（SHIELD 安全審查 → ARIA 交付）
    ├── git commit -m "feat: ..."
    └── docs/DELIVERY.md
    ↓
Project Brain Git Hook（post-commit）
    ├── L2：learn_from_commit() → Graphiti Episode
    └── L3：KnowledgeExtractor → 提取決策/踩坑/規則
```

### 技術選型原則

整個系統的技術選型遵循幾個一致的原則：

**零外部依賴優先（可以的話）：** SQLite 而非 PostgreSQL、FTS5 而非 Elasticsearch、Python stdlib 而非第三方框架。讓系統可以在任何機器上直接跑，不需要 Docker 或額外設定。

**降級設計必須完整：** 每個可選功能都要有完整的降級路徑。Graphiti 不可用 → TemporalGraph；Chroma 不可用 → SQLite FTS5；Memory Tool 不可用 → 直接 context inject。任何一個外部服務掛掉，核心功能都要繼續正常運作。

**確定性輸出優先：** 除了和 AI 互動的部分，其他邏輯（Context 組裝、Token 計算、路徑驗證）都追求確定性，讓系統的行為可預測、可測試、可除錯。

**安全是設計，不是事後加上的：** 路徑驗證、命令注入防護、SSRF 防護、Rate Limiting 都在設計之初就整合進去，而不是功能完成後再加。
