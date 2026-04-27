# Project Brain — 命令參考

> 版本：v1.0（v0.43.0）
> 已安裝全局指令：`brain <command>`
> `brain` 自動從當前目錄往上找 `.brain/`，無需 `--workdir`

## 命令總覽

> **狀態說明**：🟢 端對端可用 · 🟡 架構就緒（需手動步驟）· 🔴 實驗性

| 狀態 | 命令 | 說明 | 例子 |
|------|------|------|------|
| 🟢 | `brain setup` | 一鍵初始化（建 db + git hook + MCP）| `brain setup` |
| 🟢 | `brain init` | 低階初始化 | （一般用 setup 即可）|
| 🟢 | `brain add` | 加入知識 | `brain add "JWT 必須用 RS256"` |
| 🟢 | `brain ask` | 查詢知識 | `brain ask "JWT 設定"` |
| 🟢 | `brain context` | 查詢（技術名，同 ask）| `brain context "JWT"` |
| 🟢 | `brain search` | 純語意搜尋（不組裝 Context）| `brain search "JWT 設定"` |
| 🟢 | `brain status` | 記憶庫狀態（含飛輪健康度）| `brain status` |
| 🟢 | `brain health` | 一鍵診斷：DB / schema / signal queue | `brain health --json` |
| 🟢 | `brain validate` | 三階段知識驗證（Rule + Code + LLM）| `brain validate --ci` |
| 🟢 | `brain pipeline-stats` | Pipeline 運行統計 | `brain pipeline-stats --json` |
| 🟢 | `brain sync` | 從最新 commit 自動學習 | `brain sync --quiet` |
| 🟢 | `brain scan` | 掃描 git 歷史提取知識 | `brain scan --all` |
| 🟢 | `brain review` | 審查 KRB 暫存區知識 | `brain review list` |
| 🟢 | `brain webui` | D3.js 瀏覽器視覺化（含行內編輯）| `brain webui --port 7890` |
| 🟢 | `brain serve` | REST API / MCP Server | `brain serve --mcp` |
| 🟢 | `brain doctor` | 環境診斷與自動修復 | `brain doctor --fix` |
| 🟢 | `brain config` | 顯示並驗證所有設定來源 | `brain config` |
| 🟢 | `brain optimize` | VACUUM + ANALYZE + FTS5 rebuild | `brain optimize` |
| 🟢 | `brain clear` | 清除 session 工作記憶 | `brain clear` |
| 🟢 | `brain export` | 匯出知識庫 | `brain export --format json` |
| 🟢 | `brain import` | 匯入知識庫 | `brain import data.json` |
| 🟡 | `brain index` | 建立向量索引（需 sentence-transformers）| `brain index` |

---

## brain add 詳細說明

```bash
# 快速模式（位置參數）
brain add "JWT 必須使用 RS256"

# 完整模式
brain add "JWT 規則" \
  --kind Rule \
  --scope auth \
  --confidence 0.9 \
  --content "RS256 是非對稱加密，可跨服務安全共享公鑰"
```

**kind 類型**：`Note`（預設）/ `Rule` / `Pitfall` / `Decision` / `ADR` / `Component`

**scope 範例**：`auth` / `payment_service` / `user_profile` / `global`（預設）

---

## brain health 詳細說明

```bash
# 互動式健康報告（彩色輸出）
brain health

# JSON 格式輸出（供 CI 或腳本解析）
brain health --json

# 指定專案目錄
brain health --workdir /path/to/project
```

**JSON 輸出結構**（`d["summary"]["overall"]`，非頂層 `overall`）：

```json
{
  "version": "0.43.0",
  "brain_dir": "/your/project/.brain",
  "checks": [
    {"level": "ok",   "label": "brain.db",        "message": "20 nodes, 8 edges"},
    {"level": "ok",   "label": "schema",           "message": "v26, up to date"},
    {"level": "warn", "label": "signal_queue",     "message": "3 pending signals"},
    {"level": "ok",   "label": "krb_staging",      "message": "0 pending staged"}
  ],
  "summary": {
    "overall": "warn",
    "ok": 3,
    "warn": 1,
    "error": 0
  }
}
```

**CI 整合**（`.github/workflows/ci.yml`）：

```bash
brain health --json | python - <<'PYEOF'
import json, sys
d = json.load(sys.stdin)
overall = d["summary"]["overall"]   # 注意：不是 d["overall"]
sys.exit(0 if overall in ("ok", "warn") else 1)
PYEOF
```

---

## brain validate 詳細說明

```bash
# 互動式三階段驗證（Rule + Code + LLM）
brain validate

# CI 模式（跳過 LLM，只跑 Rule + Code，輸出 JSON，exit 1 if failed）
brain validate --ci

# 輸出 JSON 報告到檔案
brain validate --ci --output /tmp/validate-report.json

# 限制 LLM API 呼叫數
brain validate --max-api-calls 5
```

**三個驗證階段**：

| 階段 | 需要 LLM | 說明 |
|------|---------|------|
| Stage 1: Rule | 否 | 結構規則（信心範圍、必要欄位、標籤格式） |
| Stage 2: Code | 否 | code 比對（Pitfall 節點不能沒有 content）|
| Stage 3: LLM  | 是 | 語意一致性檢查（CI 模式略過）|

**CI 整合**：

```bash
brain validate --ci --output /tmp/report.json
python -c "
import json, sys
d = json.load(open('/tmp/report.json'))
sys.exit(0 if d['passed'] else 1)
"
```

---

## brain pipeline-stats 詳細說明

```bash
# 顯示過去 7 天 Pipeline 統計
brain pipeline-stats

# 指定時間窗口（天）
brain pipeline-stats --days 30

# JSON 格式（供 dashboard 解析）
brain pipeline-stats --json

# Prometheus text format（供 Prometheus scrape）
brain pipeline-stats --prometheus
```

**輸出範例**：

```
Pipeline Stats（過去 7 天）
────────────────────────────────────────────
  訊號隊列
    pending:    2    processing: 0    done: 47    failed: 1
    新增訊號:   50   |  成功處理: 47  |  失敗率: 2.1%

  知識提取
    add:        31   skip: 16   failed: 1
    API 呼叫:   31   avg confidence: 0.74

  訊號種類分布
    git_commit:     41    task_complete:  7    manual: 2
```

**Prometheus 格式**（`--prometheus`）：

```
# HELP brain_signals_total Total signals by status
brain_signals_total{status="done"} 47
brain_signals_total{status="failed"} 1
brain_pipeline_add_total 31
brain_pipeline_skip_total 16
```

---

## brain doctor 詳細說明

```bash
# 完整健康檢查（環境、資料庫、Git、MCP、套件、向量搜尋引擎）
brain doctor

# 自動修復可修復的問題（git hook、MCP 設定）
brain doctor --fix
```

**向量搜尋引擎驗證（三層）**：

```
向量搜尋引擎
────────────────────────────────────────────
✓  Layer 1  套件已安裝  (sqlite-vec 0.1.9)
✓  Layer 2  SQLite C 擴充載入成功
✓  Layer 3  vec_distance_cosine 運算正確  (dist=0.0000)
✓  搜尋路徑  C 擴充加速  （FTS5 × 0.4 + 向量 × 0.6）
✓  Embedding  LocalTFIDF  (256 dim，零依賴)
```

若 Layer 2 失敗（`enable_load_extension` 被禁用），修復方式：

```bash
# pyenv 用戶（重新編譯 Python）
PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' \
  pyenv install --force $(pyenv version-name)

# 或改用 Homebrew Python（已內建擴充支援）
brew install python@3.12
```

---

## brain review 詳細說明

`brain scan` 提取的知識先進 KRB Staging 暫存區，需人工審核才進入 L3：

```bash
# 列出待審清單
brain review list

# 核准（進入 L3）
brain review approve <node_id>

# 駁回（附上原因）
brain review reject <node_id> --reason "資訊不正確"
```

---

## brain scan 詳細說明

```bash
# 掃描最近 100 筆 commit（預設）
brain scan

# 掃描全部歷史
brain scan --all

# 指定數量
brain scan --limit 50
```

提取的知識進入 KRB 暫存區，用 `brain review list` 審查。

---

## brain ask 輸出說明

```
🧠 相關知識注入
─────────────────
⛓ 因果關係（Brain 預先推導）
  🛡 [JWT RS256] PREVENTS [Token 過期漏洞]

### ⚠ 已知踩坑：Token 過期未驗證
JWT exp 欄位必須驗證...

### 📌 業務規則：JWT RS256
必須使用 RS256 非對稱加密...
```

---

## 環境變數

| 變數 | 預設 | 說明 |
|------|------|------|
| `BRAIN_WORKDIR` | 當前目錄 | 省略 --workdir |
| `ANTHROPIC_API_KEY` | — | AI 功能（scan / 知識提取）|
| `BRAIN_SYNTHESIZE` | `0` | `1` = 記憶融合模式（opt-in）|
| `BRAIN_LLM_PROVIDER` | `anthropic` | `openai` = Ollama 本地 LLM |
| `BRAIN_LLM_BASE_URL` | `http://localhost:11434/v1` | 本地 LLM 端點 |
| `BRAIN_LLM_MODEL` | `claude-haiku-4-5-20251001` | 模型名稱 |
| `BRAIN_API_KEY` | — | `brain serve` API 認證 |
| `BRAIN_MAX_TOKENS` | `6000` | Context 最大 token 預算 |
| `BRAIN_EXPAND_LIMIT` | `15` | 查詢展開詞彙上限（減少同義詞雜訊）|
| `BRAIN_DEDUP_THRESHOLD` | `0.85` | 語意去重 cosine 閾值（0.70 更積極）|
| `BRAIN_RATE_LIMIT_RPM` | `60` | MCP 每分鐘呼叫上限 |
| `BRAIN_EMBED_PROVIDER` | 自動偵測 | `none` = 停用向量，純 FTS5 |

---

---

## brain optimize 詳細說明

```bash
# 執行完整資料庫維護
brain optimize
```

輸出範例：
```
⚙ brain optimize — 正在最佳化知識庫...
✓ VACUUM + ANALYZE 完成
✓ FTS5 索引重建：ok
磁碟使用：12.3 KB → 4.1 KB  節省 8.2 KB
```

---

## brain clear 詳細說明

```bash
# 清除當前 session 工作記憶（安全，L1a 非持久化條目）
brain clear

# 清除所有 L3 知識節點（危險操作，需雙重確認）
brain clear --all --yes
```

---

## brain export / brain import 詳細說明

```bash
# 匯出為 JSON
brain export --format json --output backup.json

# 匯出為 Neo4j Cypher
brain export --format neo4j --output knowledge.cypher

# 匯入（互動式衝突解決）
brain import backup.json --merge-strategy interactive
# merge-strategy 選項：skip / overwrite / confidence_wins / interactive
```

---

## brain analytics 詳細說明

```bash
# 顯示使用率統計
brain analytics

# 匯出 CSV
brain analytics --export csv --output usage.csv
```

CSV 欄位：`node_id` / `title` / `type` / `scope` / `access_count` / `last_accessed` / `confidence`

---

## brain deprecate / brain lifecycle 詳細說明

```bash
# 廢棄節點（設 is_deprecated=1，建立 REPLACED_BY 邊）
brain deprecate <node_id> [--replaced-by <new_id>]

# 查看節點生命週期
brain lifecycle <node_id>
```

---

## brain counterfactual 詳細說明

```bash
# 分析假設變更的影響
brain counterfactual "如果我們用 NoSQL 代替 PostgreSQL"
# 輸出：受影響的知識節點，依影響分數排序
```

---

## 已移除 / 隱藏命令

以下命令存在但標記為 `==SUPPRESS==`（進階 / 實驗性，不在主要 help 中顯示）：

`analytics`, `backfill-git`, `deprecated`, `deprecate`, `fed`, `history`,
`index`, `lifecycle`, `link-issue`, `meta`, `migrate`, `report`, `restore`,
`rollback`, `session`, `timeline`

舊版命令（已完全移除）：
- `learn`, `export-rules`, `daemon` — 已在 v0.10.x 清理

`distill` — 待實作（D-01，需 GPU ≥16GB）。計劃：從 L3 知識庫生成 Q&A 訓練集，
搭配 [Axolotl](https://github.com/OpenAccess-AI-Collective/axolotl) 做 LoRA 微調。

---

## 向量索引說明（TECH-03）

`brain index` 建立 dense vector 索引（sqlite-vec / HNSW）。

| 節點數量 | 建議索引類型 | 說明 |
|---------|------------|------|
| < 2000 | sqlite-vec（預設）| 線性掃描，無需額外依賴 |
| ≥ 2000 | HNSW（建議切換）| 大幅降低查詢延遲，需 `pip install hnswlib` |

切換方式：在 `.brain/config.json` 設定 `"vector_backend": "hnsw"`。
