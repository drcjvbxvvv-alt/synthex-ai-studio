# SYNTHEX AI STUDIO — 品質評估框架（Evals）

> 你不知道 AI 輸出品質如何，除非你系統性地量化它。

---

## 目錄

- [為什麼需要 Evals](#為什麼需要-evals)
- [快速開始](#快速開始)
- [評估套件（Suites）](#評估套件suites)
- [案例格式（Case Schema）](#案例格式case-schema)
- [EvalRunner — 執行引擎](#evalrunner--執行引擎)
- [EvalScorer — 評分系統](#evalscorer--評分系統)
- [新增評估案例](#新增評估案例)
- [新增評估套件](#新增評估套件)
- [CI/CD 整合](#cicd-整合)
- [評估結果解讀](#評估結果解讀)

---

## 為什麼需要 Evals

當你修改了一個 Agent 的 system prompt，你怎麼知道品質有沒有變差？

不運行 Evals，你只能：
- 主觀覺得「看起來還好」
- 每次改完手動測試幾個例子
- 等用戶反映問題再發現

Evals 讓你能夠：

```
改了 ECHO 的 PRD system prompt
    ↓
python -m core.evals run --suite prd_quality
    ↓
Suite: prd_quality | 3/3 通過 | 平均分 0.78 → 0.82（+0.04）✓
    ↓
確信改動是改善，而不是在猜
```

---

## 快速開始

```bash
cd ~/tools/synthex-ai-studio

# 執行所有評估套件
python -m core.evals run

# 執行特定套件
python -m core.evals run --suite prd_quality
python -m core.evals run --suite security_quality

# 執行單一案例
python -m core.evals run --case prd-001

# 列出所有可用套件
python -m core.evals list

# 查看歷史結果
python -m core.evals history --suite prd_quality
python -m core.evals history --last 10

# 比較兩次結果
python -m core.evals compare --run-a abc123 --run-b def456
```

---

## 評估套件（Suites）

目前有 4 個內建套件，位於 `evals/suites/`：

### `prd_quality` — PRD 撰寫品質（ECHO）

測試 ECHO 在需求分析和 PRD 撰寫上的品質。

| 案例 | 測試點 |
|------|--------|
| prd-001 | 基本 PRD 完整性：用戶故事、驗收條件、優先排序 |
| prd-002 | 邊界條件分析能力：圖片上傳的各種失敗情境 |
| prd-003 | 非功能性需求（NFR）：效能、安全、可用性指標 |

**評分標準：**
- 包含用戶故事（GIVEN-WHEN-THEN 格式）
- 有明確的驗收條件
- 有優先順序標注（P0/P1/P2）
- 不包含 "TBD"、"待填寫" 等佔位文字
- 長度 ≥ 300 字元

---

### `architecture_quality` — 技術架構品質（NEXUS）

測試 NEXUS 在技術決策和架構設計上的品質。

| 案例 | 測試點 |
|------|--------|
| arch-001 | 資料庫選型：PostgreSQL vs MongoDB 的取捨分析 |
| arch-002 | 擴展性設計：支援 100 萬用戶的認證系統架構 |

**評分標準：**
- 技術決策有明確的「理由」和「代價」
- 不只列出選項，有明確的建議
- 考慮到擴展性、維護性
- 包含具體的技術名詞（不是泛泛而談）

---

### `security_quality` — 安全審查品質（SHIELD）

測試 SHIELD 識別安全漏洞和提供修復建議的能力。

| 案例 | 測試點 |
|------|--------|
| sec-001 | SQL Injection：識別字串拼接 SQL 並給出參數化方案 |
| sec-002 | JWT 安全：algorithm confusion、expiry、密鑰管理 |

**評分標準：**
- 正確識別安全問題類型
- 提供具體的修復程式碼（不只是描述問題）
- 提到相關的 OWASP 條目
- 不能說「看起來安全」或「沒有問題」

---

### `code_quality` — 程式碼品質（BYTE + STACK）

測試工程 Agent 的程式碼輸出品質。

| 案例 | 測試點 |
|------|--------|
| code-001 | TypeScript 嚴格型別：BYTE 寫的 React 組件是否有型別安全 |
| code-002 | 後端錯誤處理：STACK 的 API 路由是否有完整的錯誤處理 |

---

## 案例格式（Case Schema）

每個評估案例是一個 JSON 物件：

```json
{
  "case_id":  "prd-001",          // 唯一 ID，用於 --case 篩選
  "suite":    "prd_quality",      // 所屬套件名稱
  "agent":    "ECHO",             // 由哪個 Agent 執行

  "prompt":   "為一個簡單的待辦事項 App 寫一份 PRD，包含用戶故事和 AC。",
  "context":  "",                 // 可選：提供額外上下文（模擬 Project Brain 注入）

  // 關鍵字評分
  "expected_keywords": ["用戶故事", "驗收條件", "P0", "AC"],  // 應該出現
  "forbidden_keywords": ["lorem ipsum", "待填寫", "TBD"],      // 不應該出現

  // 評分規則
  "rubric": {
    "min_length": 300,          // 輸出最少字元數
    "pass_threshold": 0.6,      // 通過所需的最低分（0-1）
    "criteria": {               // 自訂評分標準（可選）
      "has_user_story": {"contains": "作為"},
      "has_given_when": {"contains": "Given"}
    }
  },

  "tags": ["prd", "basic"]      // 用於篩選執行特定類別
}
```

### 完整欄位說明

| 欄位 | 必填 | 說明 |
|------|------|------|
| `case_id` | ✓ | 唯一識別符，建議用 `suite-NNN` 格式 |
| `suite` | ✓ | 所屬套件，對應 `evals/suites/<suite>.json` |
| `agent` | ✓ | 執行的 Agent 名稱（大寫）|
| `prompt` | ✓ | 給 Agent 的任務描述 |
| `context` | — | 額外 context（模擬 Brain 注入），預設 "" |
| `expected_keywords` | ✓ | 輸出中應該包含的關鍵字列表 |
| `forbidden_keywords` | ✓ | 輸出中不應該包含的關鍵字（可為空列表）|
| `rubric.min_length` | ✓ | 輸出的最小字元數（過短直接失敗）|
| `rubric.pass_threshold` | ✓ | 通過分數（0.0 ~ 1.0）|
| `rubric.criteria` | — | 額外評分規則，每條規則格式：`{"contains": "關鍵字"}` |
| `tags` | — | 標籤，用於 `--tag` 篩選執行 |

---

## EvalRunner — 執行引擎

`EvalRunner` 負責載入案例並調用 Agent 執行（`core/evals.py`）：

```python
from core.evals import EvalRunner, EvalCase

runner = EvalRunner(workdir=Path("."))

# 執行單一案例
result = runner.run_case(EvalCase.from_dict(case_data))

# 執行整個套件
suite_results = runner.run_suite("prd_quality")
print(f"通過：{suite_results.pass_count} / {suite_results.total_count}")
```

**執行流程：**

```
載入 evals/suites/<suite>.json
    ↓
for each case:
    agent = get_agent(case.agent)
    response = agent.chat(case.prompt, system_context=case.context)
    score = EvalScorer.score(response, case.rubric)
    → 儲存到 evals/results.db（SQLite）
    ↓
彙總結果
    → 輸出 pass/fail 統計
    → 更新 evals/results.db
```

---

## EvalScorer — 評分系統

`EvalScorer` 把 Agent 的原始輸出轉換成可比較的分數（`core/evals.py`）：

```python
class EvalScorer:
    @staticmethod
    def score(response: str, rubric: dict) -> EvalScore:
        """
        Returns:
            EvalScore:
                score:      float 0.0 ~ 1.0
                passed:     bool
                details:    dict  各項目的得分明細
                reasoning:  str   失敗原因說明
        """
```

### 評分算法

1. **長度檢查（20% 權重）：** 輸出字元數 >= `min_length` 才得分
2. **關鍵字命中（50% 權重）：** `expected_keywords` 命中比例
3. **禁用詞懲罰（-20%）：** 每個 `forbidden_keyword` 出現扣 20%
4. **自訂標準（30% 權重）：** `rubric.criteria` 裡的每個條件是否滿足

```
final_score = (
    length_score   × 0.2 +
    keyword_score  × 0.5 +
    criteria_score × 0.3
) - forbidden_penalty

passed = final_score >= pass_threshold
```

---

## 新增評估案例

在對應的 `evals/suites/<suite>.json` 加入新案例：

```bash
# 例如：為 prd_quality 新增一個測試多語言需求的案例
```

在 `evals/suites/prd_quality.json` 加入：

```json
{
  "case_id": "prd-004",
  "suite": "prd_quality",
  "agent": "ECHO",
  "prompt": "為一個需要支援英文和繁體中文的用戶設定頁面寫 PRD。",
  "context": "",
  "expected_keywords": ["i18n", "locale", "繁體中文", "英文"],
  "forbidden_keywords": ["TBD", "待確認"],
  "rubric": {
    "min_length": 250,
    "pass_threshold": 0.6,
    "criteria": {
      "mentions_i18n": {"contains": "i18n"},
      "mentions_fallback": {"contains": "語言偵測"}
    }
  },
  "tags": ["prd", "i18n"]
}
```

**好的評估案例的特徵：**
- `expected_keywords` 是具體的，不是泛用的（用「參數化查詢」而非「安全」）
- `forbidden_keywords` 是真正會降低品質的字詞
- `pass_threshold` 基於實際測試，不是隨便填
- 一個案例測試一個能力點，不是測所有東西

---

## 新增評估套件

### Step 1：建立 JSON 檔案

```bash
touch evals/suites/ux_quality.json
```

```json
[
  {
    "case_id": "ux-001",
    "suite": "ux_quality",
    "agent": "SPARK",
    "prompt": "設計電商平台首頁的 UX，目標用戶是 35-50 歲的家庭主婦。",
    "context": "",
    "expected_keywords": ["用戶旅程", "資訊架構", "首頁", "分類"],
    "forbidden_keywords": ["待設計", "略"],
    "rubric": {
      "min_length": 300,
      "pass_threshold": 0.65,
      "criteria": {
        "has_journey": {"contains": "旅程"},
        "considers_mobile": {"contains": "手機"}
      }
    },
    "tags": ["ux", "ecommerce"]
  }
]
```

### Step 2：執行新套件

```bash
python -m core.evals run --suite ux_quality
```

---

## CI/CD 整合

在 GitHub Actions 中加入 Evals 自動執行：

```yaml
# .github/workflows/evals.yml
name: Agent Quality Evals

on:
  push:
    paths:
      - 'agents/all_agents.py'   # Agent system prompt 改動時觸發
      - 'core/base_agent.py'     # 基底類別改動時
      - 'evals/**'               # Eval 本身改動時

jobs:
  evals:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Run Evals
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          python -m core.evals run --fail-on-regression
          # --fail-on-regression：如果平均分比上次下降 > 5%，exit code = 1

      - name: Upload results
        uses: actions/upload-artifact@v4
        with:
          name: eval-results
          path: evals/results.db
```

### Regression 偵測

`--fail-on-regression` 模式：

```
本次執行平均分：0.74
上次記錄平均分：0.81
差異：-0.07（> 5% 閾值）
→ exit code 1，CI 失敗
→ PR 被阻擋，要求修復
```

---

## 評估結果解讀

### 分數分布

| 分數範圍 | 解讀 | 行動 |
|---------|------|------|
| 0.85 - 1.0 | 優秀 | 繼續維持 |
| 0.70 - 0.84 | 良好 | 觀察是否有改善空間 |
| 0.60 - 0.69 | 及格 | 檢查具體失分點 |
| 0.50 - 0.59 | 不佳 | 需要調整 system prompt |
| < 0.50 | 失敗 | 立即調查 |

### 常見失敗原因

**輸出太短（`min_length` 未達標）：**

Agent 給出了過於簡潔的回答。調整 system prompt，強調「輸出需要完整且詳細，不要省略重要步驟」。

**關鍵字命中率低：**

Agent 理解了問題但沒有使用正確的術語。這可能是 system prompt 的問題，或是 `expected_keywords` 定義太嚴格。先用真實輸出調整關鍵字列表。

**包含 `forbidden_keywords`：**

Agent 輸出了「待填寫」、「TBD」這類佔位文字。在 system prompt 中明確禁止：「絕對不能出現 TBD、待確認、視情況、略等佔位文字，必須給出具體內容」。

**`criteria` 未通過：**

特定評分標準沒有達到，例如 SHIELD 沒有識別出 SQL Injection。查看 Agent 的實際輸出，確認是 Agent 能力問題還是 prompt 問題。

### 查看歷史趨勢

```bash
# 查看 prd_quality 最近 20 次執行的分數變化
python -m core.evals history --suite prd_quality --last 20

# 輸出：
# Run ID  | Time              | Pass | Avg Score
# a1b2c3  | 2026-03-27 10:00  | 3/3  | 0.82
# d4e5f6  | 2026-03-20 14:30  | 2/3  | 0.71  ← 這次下降了
# g7h8i9  | 2026-03-15 09:15  | 3/3  | 0.79
```

找出分數下降的版本，用 `git diff` 查看當天的 commit 內容。

### 資料庫直接查詢

評估結果儲存在 `evals/results.db`（SQLite），可以直接查詢：

```sql
-- 最近一週的通過率趨勢
SELECT
    DATE(run_at) as date,
    suite,
    COUNT(*) as total,
    SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) as passed,
    AVG(score) as avg_score
FROM eval_results
WHERE run_at > datetime('now', '-7 days')
GROUP BY date, suite
ORDER BY date DESC;
```
