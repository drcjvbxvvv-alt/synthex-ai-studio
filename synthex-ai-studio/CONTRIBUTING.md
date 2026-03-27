# SYNTHEX AI STUDIO — 開發者貢獻指南

---

## 目錄

- [開發環境建立](#開發環境建立)
- [專案結構](#專案結構)
- [如何新增 Agent](#如何新增-agent)
- [如何新增工具](#如何新增工具)
- [如何修改 ship 流水線](#如何修改-ship-流水線)
- [如何擴充 Project Brain](#如何擴充-project-brain)
- [測試規範](#測試規範)
- [Eval 規範](#eval-規範)
- [程式碼風格](#程式碼風格)
- [提交規範](#提交規範)
- [Pull Request 流程](#pull-request-流程)

---

## 開發環境建立

```bash
# 1. Clone 或解壓縮到本地
cd ~/tools/synthex-ai-studio

# 2. 建立 virtual environment（強烈建議）
python -m venv .venv
source .venv/bin/activate

# 3. 安裝依賴（含開發工具）
pip install -r requirements.txt
pip install pytest pytest-asyncio black isort mypy

# 4. 設定 API Key
export ANTHROPIC_API_KEY="sk-ant-..."

# 5. 執行測試確認環境正常
python -m pytest tests/ -v

# 6. 執行單一測試確認
python -m pytest tests/test_core.py::TestConfig -v
```

---

## 專案結構

```
synthex-ai-studio/
│
├── synthex.py              ← CLI 主入口，所有 cmd_* 函數在這裡
│
├── core/                   ← 核心引擎
│   ├── base_agent.py       ← Agent 基底（對話 + Agentic + CompactionManager）
│   ├── config.py           ← 模型設定（ModelID、Tier、SynthexConfig）
│   ├── web_orchestrator.py ← /ship 12-Phase 流水線
│   ├── swarm.py            ← AgentSwarm 並行協作（Kahn's Algorithm）
│   ├── tools.py            ← Agent 工具集（所有工具定義和安全邏輯）
│   ├── web_tools.py        ← 網頁開發專用工具（npm、git、框架偵測）
│   ├── advanced_tool_use.py ← 結構化輸出 GA 格式
│   ├── computer_use.py     ← Computer Use 安全層
│   ├── observability.py    ← OpenTelemetry 整合
│   ├── rate_limiter.py     ← Token Bucket + CircuitBreaker
│   ├── logging_setup.py    ← structlog 設定
│   ├── evals.py            ← EvalRunner + EvalScorer
│   ├── browser_qa.py       ← Playwright 瀏覽器 QA
│   └── brain/              ← Project Brain v4.0
│       ├── engine.py       ← ProjectBrain 主引擎
│       ├── memory_tool.py  ← L1 工作記憶（Anthropic Memory Tool）
│       ├── graphiti_adapter.py ← L2 情節記憶
│       ├── router.py       ← BrainRouter v3.0
│       ├── knowledge_validator.py ← v4.0 自主驗證
│       ├── federation.py   ← v4.0 差分隱私聯邦
│       ├── knowledge_distiller.py ← v4.0 知識蒸餾
│       ├── graphiti_mcp_server.py ← v4.0 Graphiti MCP
│       ├── web_ui/         ← v4.0 D3.js Web UI
│       └── ...（其他 Brain 模組）
│
├── agents/
│   └── all_agents.py       ← 全部 28 個 Agent 的 system_prompt 定義
│
├── evals/
│   ├── suites/             ← 評估案例 JSON 檔案
│   └── results.db          ← 評估歷史（SQLite，不提交 git）
│
├── tests/
│   └── test_core.py        ← 所有自動化測試（139 個）
│
├── docs/
│   └── images/             ← 架構圖 SVG
│
└── memory/                 ← Agent 對話記憶（自動生成，不提交 git）
```

---

## 如何新增 Agent

### Step 1：在 `agents/all_agents.py` 定義

```python
class IRIS(BaseAgent):
    """你的新 Agent 說明"""

    name   = "IRIS"                    # 大寫英文
    title  = "資料視覺化工程師"          # 人類可讀職稱
    dept   = "ai_data"                 # 所屬部門
    emoji  = "📊"                      # 識別 emoji
    color  = "\033[36m"                # ANSI 顏色（終端輸出用）

    skills = [
        "D3.js 資料視覺化",
        "Recharts / Chart.js",
        "大數據前端展示",
        "互動式儀表板設計",
        "資料密集型 UI 效能優化",
    ]

    personality_traits = {
        "數據美學": 95,
        "技術深度": 85,
        "溝通能力": 78,
    }

    system_prompt = """
你是 IRIS，SYNTHEX AI STUDIO 的資料視覺化工程師。

【人設與思維】
- 相信好的視覺化能讓複雜數據一目了然
- 用 D3.js 能寫出讓設計師驚訝的互動圖表
- 效能和美觀不是取捨，而是都要達到的目標

【核心能力】
1. D3.js 力導向圖、地圖視覺化、自訂 SVG 動畫
2. Recharts / Chart.js 快速原型
3. 大量資料的前端虛擬化（Virtualization）
4. Canvas vs SVG 的選型判斷

【工作風格】
- 先理解數據的本質，再決定最適合的視覺化形式
- 提供具體的效能數字（「可以流暢渲染 10 萬個資料點」）
- 給出可直接使用的程式碼範例
"""
```

### Step 2：在 `synthex.py` 的 `AGENT_MAP` 加入

```python
from agents.all_agents import ..., IRIS

AGENT_MAP = {
    ...
    "IRIS":   IRIS,
}
```

### Step 3：（選填）在 `CLAUDE.md` 加入 SKILL.md 說明

如果你的 Agent 有專屬的技能文件，在 CLAUDE.md 的角色表格裡加入：

```markdown
| IRIS | `agents/IRIS/SKILL.md` | 資料視覺化（D3.js / Recharts）|
```

並建立對應的 `agents/IRIS/SKILL.md`。

### Step 4：寫評估案例

```json
// evals/suites/code_quality.json 新增：
{
  "case_id": "viz-001",
  "suite": "code_quality",
  "agent": "IRIS",
  "prompt": "用 Recharts 設計一個折線圖，顯示過去 30 天的日活躍用戶數。",
  "expected_keywords": ["LineChart", "data", "XAxis", "YAxis"],
  "forbidden_keywords": [],
  "rubric": {"min_length": 100, "pass_threshold": 0.6},
  "tags": ["code", "visualization"]
}
```

### Step 5：確認測試通過

```bash
python -m pytest tests/test_core.py -v -k "agent"
python -m core.evals run --suite code_quality
```

---

## 如何新增工具

所有工具定義在 `core/tools.py` 的 `TOOL_DEFINITIONS` 和對應的執行函數。

### Step 1：定義工具 Schema

```python
# 在 TOOL_DEFINITIONS 列表中加入
{
    "name":        "read_database",
    "description": "查詢 SQLite 資料庫",
    "input_schema": {
        "type": "object",
        "properties": {
            "db_path": {
                "type": "string",
                "description": "資料庫檔案路徑（相對於 workdir）"
            },
            "query": {
                "type": "string",
                "description": "SQL 查詢（只允許 SELECT）"
            },
        },
        "required": ["db_path", "query"],
    },
},
```

### Step 2：實作執行函數

```python
def _tool_read_database(
    db_path: str,
    query:   str,
    workdir: Path,
) -> str:
    # 安全驗證（必須有）
    safe_path = _validate_path(workdir, db_path)

    # 只允許 SELECT（防止資料修改）
    q = query.strip().upper()
    if not q.startswith("SELECT"):
        raise ValueError("只允許 SELECT 查詢")

    # 限制查詢複雜度
    if "DROP" in q or "DELETE" in q or "INSERT" in q:
        raise ValueError("不允許修改操作")

    conn = sqlite3.connect(str(safe_path))
    try:
        cursor = conn.execute(query)
        rows   = cursor.fetchmany(100)  # 最多 100 行
        return json.dumps(rows, ensure_ascii=False)
    finally:
        conn.close()
```

### Step 3：在路由函數中加入

```python
def execute_tool(tool_name: str, tool_input: dict, workdir: Path) -> str:
    ...
    elif tool_name == "read_database":
        return _tool_read_database(
            db_path = tool_input["db_path"],
            query   = tool_input["query"],
            workdir = workdir,
        )
```

### Step 4：加入安全測試

```python
# 在 tests/test_core.py 加入
class TestReadDatabase(unittest.TestCase):
    def test_blocks_drop_statement(self):
        with self.assertRaises(ValueError):
            _tool_read_database("test.db", "DROP TABLE users", workdir=tmpdir)

    def test_blocks_path_traversal(self):
        with self.assertRaises(SecurityError):
            _tool_read_database("../../etc/passwd", "SELECT 1", workdir=tmpdir)
```

---

## 如何修改 ship 流水線

`/ship` 的流水線定義在 `core/web_orchestrator.py` 的 `WebOrchestrator.run()` 方法。

### 新增一個 Phase

在適當位置插入新的 Phase：

```python
# Phase X：你的新 Phase
print(f"\n{'='*60}")
print(f"Phase X — YOUR_AGENT（你的職責說明）")
print(f"{'='*60}\n")

phase_x_result = await self._run_phase(
    phase_num  = X,
    agent_name = "YOUR_AGENT",
    prompt     = self._build_phase_x_prompt(previous_results),
    schema     = PhaseXOutput,    # 結構化輸出 Schema（可選）
)

# 儲存 checkpoint
self.checkpoint.save(X, {"phase_x": phase_x_result})
```

**注意：**
- Phase 數字必須連續，並更新 `PhaseCheckpoint` 的版本號
- 新增 Phase 前要想清楚：這個 Phase 在哪裡取得 input？output 給誰？
- 如果不需要 API 呼叫（純文字轉換），不需要新增 Phase，在現有 Phase 的 prompt 裡加邏輯

### 調整現有 Phase 的 prompt

```python
def _build_phase_2_prompt(self, task_confirmation: dict) -> str:
    return f"""
你是 ECHO，負責撰寫完整的 PRD。

根據任務確認結果：
{json.dumps(task_confirmation, ensure_ascii=False, indent=2)}

**重要：以下是本次任務的 Project Brain 知識：**
{self.brain_context}

撰寫包含以下部分的 PRD：
...
"""
```

---

## 如何擴充 Project Brain

### 新增 L1 工作記憶目錄

在 `core/brain/memory_tool.py` 的 `MEMORY_DIRS` 加入：

```python
MEMORY_DIRS = {
    "pitfalls":  "/memories/pitfalls",
    "decisions": "/memories/decisions",
    "progress":  "/memories/progress",
    "context":   "/memories/context",
    "notes":     "/memories/notes",
    "references": "/memories/references",  # 你的新目錄
}
```

### 新增 L3 節點類型

在 `core/brain/graph.py` 的 `setup_schema()` 加入新類型的處理邏輯（圖譜是通用的，節點類型是字串，無需 schema 變更）。

在 `core/brain/context.py` 的 `ContextEngineer` 加入對新類型的 Context 組裝邏輯。

### 新增 v4.0 功能模組

建立 `core/brain/your_feature.py`，繼承或整合現有模組：

```python
"""core/brain/your_feature.py"""

class YourFeature:
    def __init__(self, graph, brain_dir: Path):
        self.graph     = graph
        self.brain_dir = brain_dir

    def run(self) -> YourResult:
        ...
```

在 `core/brain/engine.py` 加入懶初始化屬性：

```python
@property
def your_feature(self) -> "YourFeature":
    if self._your_feature is None:
        from core.brain.your_feature import YourFeature
        self._your_feature = YourFeature(self.graph, self.brain_dir)
    return self._your_feature
```

在 `core/brain/__init__.py` 加入 export。

---

## 測試規範

### 每個功能都要有測試

- 新增 Agent → 加入對應的 Eval 案例
- 新增工具 → 加入安全性測試（路徑穿越、注入攻擊）
- 新增 Brain 模組 → 加入單元測試

### 測試檔案位置

所有測試在 `tests/test_core.py`，按功能分組（TestClass）：

```python
class TestYourFeature(unittest.TestCase):
    """你的功能的測試說明"""

    def setUp(self):
        """每個 test method 執行前的設定"""
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        """每個 test method 執行後的清理（可選）"""
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_basic_functionality(self):
        """最基本的功能應該正常運作"""
        ...

    def test_edge_case(self):
        """邊界條件應該被正確處理"""
        ...

    def test_security_path_traversal(self):
        """路徑穿越攻擊應該被阻擋"""
        with self.assertRaises((ValueError, SecurityError)):
            your_function(path="../../etc/passwd", ...)
```

### 測試命名規範

```
test_<行為>_<條件>_<預期結果>

test_create_memory_with_valid_path_succeeds
test_create_memory_with_traversal_path_raises_error
test_validate_rules_with_injection_flags_node
```

### 執行測試

```bash
# 全部測試
python -m pytest tests/ -v

# 只跑特定 class
python -m pytest tests/test_core.py::TestBrainRouter -v

# 只跑包含特定字串的 test
python -m pytest tests/ -k "security" -v

# 測試並顯示覆蓋率（需要 pytest-cov）
python -m pytest tests/ --cov=core --cov-report=term-missing
```

### 目標：新增功能不降低通過率

提交前確認：`python -m pytest tests/ -q` 全數通過。

---

## Eval 規範

### 評估案例要反映真實使用

不要寫太容易的案例（任何回應都能通過），也不要太難（即使是正確答案也會失敗）。

**好的案例：**
```json
{
  "prompt": "為圖片上傳功能列出所有需要驗證的邊界條件。",
  "expected_keywords": ["空檔案", "檔案大小", "MIME type", "惡意檔案"],
  "rubric": {"min_length": 200, "pass_threshold": 0.6}
}
```

**不好的案例（太容易）：**
```json
{
  "prompt": "說明什麼是 REST API。",
  "expected_keywords": ["HTTP", "URL"],
  "rubric": {"min_length": 50, "pass_threshold": 0.3}
}
```

### 每次修改 system_prompt 後要跑 Evals

```bash
# 修改了 ECHO 的 system prompt 後
python -m core.evals run --suite prd_quality

# 確認沒有 regression（平均分沒有下降）
python -m core.evals compare --suite prd_quality --last 2
```

---

## 程式碼風格

### Python 風格

- 使用 **Black** 格式化（行寬 100）
- **isort** 整理 import 順序
- **mypy** 型別提示（嚴格模式對新程式碼）

```bash
black core/ agents/ tests/ --line-length 100
isort core/ agents/ tests/
mypy core/brain/ --ignore-missing-imports
```

### 命名規範

```python
# 類別：PascalCase
class BrainRouter:

# 函數和變數：snake_case
def query_all_layers():
    max_tokens = 3_000

# 常數：UPPER_SNAKE_CASE
MAX_CONTEXT_TOKENS = 3_000
PATH_PREFIX = "/memories"

# 私有方法：_prefix
def _validate_path(self):
```

### 安全相關

- 所有處理用戶輸入的函數必須有**輸入驗證**
- 所有檔案操作必須有**路徑驗證**
- 所有外部命令使用 **argv 陣列**（不用 shell=True）
- 敏感操作需要**記錄到日誌**（logger.info/warning）
- SQL 查詢必須**參數化**（不用字串拼接）

### Docstring 格式

```python
def validate_path(workdir: Path, user_path: str) -> Path:
    """
    驗證路徑是否在 workdir 內，防止路徑穿越攻擊。

    Args:
        workdir:   允許操作的根目錄
        user_path: 用戶提供的路徑（可能包含 ../ 等攻擊）

    Returns:
        Path: 驗證後的絕對路徑

    Raises:
        SecurityError: 路徑在 workdir 外
        ValueError:    路徑格式無效
    """
```

---

## 提交規範

遵循 Conventional Commits 格式：

```
<type>(<scope>): <description>

<body>（可選，說明為什麼這樣做）

<footer>（可選，如 BREAKING CHANGE）
```

**Type：**

| Type | 說明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修復 bug |
| `refactor` | 重構（不改功能）|
| `test` | 新增或修改測試 |
| `docs` | 只改文件 |
| `chore` | 工具、設定、依賴 |
| `perf` | 效能改善 |
| `security` | 安全修復 |

**範例：**

```bash
# 新增功能
git commit -m "feat(brain): 新增 KnowledgeValidator 三階段自主驗證"

# 修復 bug
git commit -m "fix(swarm): 修復 DAG 排序中的 cycle detection 缺失"

# 安全修復
git commit -m "security(tools): 禁用 shell=True，改用 argv 陣列防注入"

# 重構
git commit -m "refactor(config): 把散落各處的模型名稱集中到 ModelID enum"
```

---

## Pull Request 流程

### PR 前的自我檢查

```bash
# 1. 所有測試通過
python -m pytest tests/ -q

# 2. 相關的 Evals 通過
python -m core.evals run --suite <你修改的相關 suite>

# 3. 程式碼格式
black core/ agents/ tests/ --line-length 100 --check
isort core/ agents/ --check

# 4. 確認 requirements.txt 同步（新增了套件的話）
pip freeze | grep -f requirements.txt
```

### PR 描述模板

```markdown
## 變更說明

簡短描述這個 PR 做了什麼，以及為什麼。

## 測試

- [ ] `python -m pytest tests/ -q` 全數通過（目前 139/139）
- [ ] 相關的 Eval 套件通過
- [ ] 新增的功能有對應的測試

## 安全考量（如有相關）

- 路徑驗證：✓ / 不適用
- 命令注入防護：✓ / 不適用
- 輸入長度限制：✓ / 不適用

## 相關文件

- [ ] 已更新 AGENTS.md（新增 Agent）
- [ ] 已更新 COMMANDS.md（新增命令）
- [ ] 已更新 ARCHITECTURE.md（架構改變）
- [ ] 已更新 CHANGELOG.md
```
