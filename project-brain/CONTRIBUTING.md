# Project Brain — 開發者貢獻指南

> 獨立 AI 記憶系統，歡迎貢獻程式碼、測試、文件和新想法。

---

## 快速開始

```bash
git clone https://github.com/drcjvbxvvv-alt/synthex-ai-studio
cd synthex-ai-studio/project-brain

# 安裝開發依賴
pip install pytest pytest-cov

# 執行測試
python -m pytest tests/ -v

# 啟動開發模式
brain init --workdir .
brain status
```

---

## 程式碼架構邊界（重要）

```
project_brain/   ← 唯一業務邏輯來源（THE single source of truth）
core/brain/      ← 薄整合層，僅做 re-export，不含業務邏輯
```

**黃金規則：**
- 修改任何業務邏輯（知識圖譜、記憶、提取、衰減等）→ 只改 `project_brain/`
- `core/brain/` 每個 .py 只有 2 行：docstring + `from project_brain.X import *`
- 新增模組到 `core/brain/` 僅限於 Synthex orchestration（config 讀取、模型選擇）
- 違反此規則會造成雙重維護負擔，任何 PR 若在 `core/brain/` 加入業務邏輯將被拒絕

---

## 專案結構

```
project-brain/
├── brain.py                  ← CLI entry point, all cmd_* functions here
├── core/brain/               ← Thin adapter only (2-line shims, re-export from project_brain/)
├── project_brain/            ← ALL business logic lives here (single source of truth)
│   ├── engine.py             ← ProjectBrain 門面（主要 API）
│   ├── graph.py              ← L3 知識圖譜（SQLite + FTS5）
│   ├── session_store.py      ← L1a 工作記憶（SQLite WAL）
│   ├── router.py             ← 三層查詢路由（真並行）
│   ├── context.py            ← Context 組裝（重要性加權）
│   ├── extractor.py          ← 知識提取（LLM）
│   ├── review_board.py       ← KRB 人工審查委員會
│   ├── decay_engine.py       ← 知識衰減（Pinning 保護）
│   ├── spaced_repetition.py  ← SR 衰減（訪問次數影響速度）
│   ├── event_bus.py          ← 事件匯流排（git hook / webhook）
│   ├── nudge_engine.py       ← 主動提醒（/v1/nudges）
│   ├── consolidation.py      ← 記憶整合（L1a → L3）
│   ├── condition_watcher.py  ← 條件失效偵測
│   └── web_ui/server.py      ← D3.js 視覺化 Web UI
├── tests/                    ← 完整測試套件
│   ├── test_core.py          ← 核心功能測試
│   ├── test_session_store.py ← L1a 測試
│   ├── test_chaos_and_load.py← Chaos + Load 測試
│   ├── test_web_ui.py        ← Web UI 端點測試
│   ├── test_cli.py           ← CLI 命令測試（E-5）
│   ├── test_api.py           ← REST API 端點測試（E-5）
│   └── test_mcp.py           ← MCP Server 測試（E-5）
└── docs/                     ← 技術文件
```

---

## 開發規範

### 新增 CLI 命令

1. 在 `brain.py` 中加入 `cmd_<name>(args)` 函數
2. 在 `main()` 的 argparse 段加入 `mkp('<name>', '說明')`
3. 在 `dispatch` 字典加入 `'<name>': cmd_<name>`
4. 加入對應測試

```python
# 範例：新增 brain hello 命令
def cmd_hello(args):
    """簡短說明（出現在 --help）"""
    wd = _workdir(args)
    name = args.name or "World"
    print(f"\n{G}Hello, {name}!{R}")

# argparse
p = mkp('hello', '打招呼命令（示範用）')
p.add_argument('--name', default='', help='名稱')

# dispatch
'hello': cmd_hello,
```

### 新增核心模組

```python
# project_brain/my_module.py
"""模組說明（會顯示在 help(module)）"""

class MyEngine:
    def __init__(self, graph):
        self.graph = graph

    def do_something(self) -> dict:
        """清楚的方法說明"""
        ...
```

### 測試規範

```python
class TestMyEngine:
    def test_basic_case(self, tmp_path):
        from project_brain.my_module import MyEngine
        from project_brain.graph import KnowledgeGraph
        g = KnowledgeGraph(tmp_path)
        engine = MyEngine(g)
        result = engine.do_something()
        assert isinstance(result, dict)

    def test_error_handling(self, tmp_path, monkeypatch):
        """測試錯誤情況"""
        ...
```

---

## 測試

```bash
# 全部測試
python -m pytest tests/ -v

# 只跑特定測試
python -m pytest tests/test_core.py -v -k "V81"

# 覆蓋率報告
python -m pytest tests/ --cov=project_brain --cov-report=term-missing

# Chaos 測試
python -m pytest tests/test_chaos_and_load.py -v
```

---

## 提交規範

```
<type>(<scope>): <描述>

type: feat | fix | docs | test | refactor | perf
scope: brain | graph | sr | eventbus | nudge | webui | cli

範例：
feat(sr): 加入訪問次數影響衰減速度
fix(cli): dedup 命令加入 --dry-run 旗標
docs(install): 更新 MCP Server 安裝說明
test(webui): 補上端點覆蓋率至 76%
```

---

## 環境變數（開發用）

```bash
# LLM 設定
export ANTHROPIC_API_KEY=sk-ant-...   # Anthropic（scan/learn/validate 需要）
# 或使用本地免費 LLM
export BRAIN_LLM_PROVIDER=openai
export BRAIN_LLM_BASE_URL=http://localhost:11434/v1
export BRAIN_LLM_MODEL=llama3.1:8b

# Brain 設定
export BRAIN_WORKDIR=/your/project    # 省略 --workdir
export BRAIN_MAX_TOKENS=6000          # Context 最大 token 預算
export BRAIN_EXPAND_LIMIT=15          # 查詢展開詞彙上限
export BRAIN_DEDUP_THRESHOLD=0.85     # 語意去重閾值（0.70 更積極）
export BRAIN_RATE_LIMIT_RPM=60        # MCP 每分鐘呼叫上限

# 測試用（跳過昂貴的 LLM 呼叫）
export BRAIN_SKIP_LLM=1
```

---

## 架構決策記錄

重要決策記錄在 `docs/BRAIN_MASTER.md`，修改核心架構前請先閱讀。

主要約束：
- **SQLite 單寫者**：不使用多進程寫入，用 WAL + busy_timeout 處理並行
- **單一共享連線**：`brain_db.py` 和 `graph.py` 使用單一 `_conn_obj`（`check_same_thread=False`）+ `threading.RLock` 寫入鎖，不再使用 `threading.local()`（ARCH-02）
- **懶加載 graphiti**：`project_brain/__init__.py` 不匯入 graphiti，避免冷啟動代價
- **KRB 人工把關**：所有 AI 自動提取的知識必須先進 Staging，不直接入庫
- **鎖重入禁止**：`engine.py` 的 `_init_lock` 是非可重入鎖，不得在持鎖狀態下呼叫其他需要同一鎖的屬性（見 BUG-01 根因）
- **core/ 不含業務邏輯**：`core/brain/` 每個檔案只能是 2 行 re-export shim，不得包含任何邏輯

---

## 品質門檻與驗收標準（DIR-01）

每個 minor 版本發布前，以下指標必須達標：

| 指標 | 門檻 | 量測方法 |
|------|------|---------|
| `get_context` 召回率 | ≥ 60%（sentence-transformers 環境）| `python -m pytest tests/benchmarks/benchmark_recall.py` |
| Chaos test 通過率 | 100% | `python -m pytest -m chaos` |
| 靜默失效路徑 | 0 | `grep -rn 'except' project_brain/ --include='*.py' \| grep -v logger` |
| Migration 可觀察率 | 100% | 故意設定錯誤 schema 後執行 `brain doctor`，確認有 warning |

---

## 發布前隨機審計清單（DIR-03）

每次版本發布前執行：

1. **隨機抽查 3 個 CHANGELOG 中標記「完成」的項目**
   - 找到對應的 commit hash（`git log --oneline | grep <item>`）
   - 找到對應的程式碼行號（`grep -n <function> project_brain/`）
   - 確認行為符合描述

2. **執行四維指標核查**

   ```bash
   # 飛輪：知識庫自然成長率（目標 ≥ 5 節點/7天）
   sqlite3 .brain/brain.db \
     "SELECT COUNT(*) FROM nodes WHERE tags LIKE '%auto:complete_task%' \
      AND created_at >= datetime('now','-7 days')"

   # 飛輪：NudgeEngine 命中率（目標 ≥ 30%）
   sqlite3 .brain/brain.db \
     "SELECT
       CAST(SUM(CASE WHEN event_type='nudge_triggered' THEN 1 ELSE 0 END) AS REAL)
       / NULLIF(SUM(CASE WHEN event_type='get_context' THEN 1 ELSE 0 END),0) AS hit_rate
     FROM events"

   # 技術誠實性：召回率
   python -m pytest tests/benchmarks/benchmark_recall.py -v
   ```

3. **發布 Gate 核對**
   - [ ] 所有 P0/P1 項目已 ✅
   - [ ] Chaos test 100% 通過
   - [ ] CHANGELOG 版本條目已更新
   - [ ] `pyproject.toml` 版本號已 bump
