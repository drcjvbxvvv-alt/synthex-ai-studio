# Project Brain — 命令參考

> 已安裝全局指令：`brain <command>`
> `brain` 自動從當前目錄往上找 `.brain/`，無需 `--workdir`

## 命令總覽

| 命令 | 說明 | 例子 |
|------|------|------|
| `brain setup` | 一鍵初始化（建 db + git hook + MCP）| `brain setup` |
| `brain add` | 加入知識 | `brain add "JWT 必須用 RS256"` |
| `brain ask` | 查詢知識 | `brain ask "JWT 設定"` |
| `brain status` | 記憶庫狀態 | `brain status` |
| `brain sync` | 從最新 commit 自動學習 | `brain sync --quiet` |
| `brain scan` | 掃描 git 歷史提取知識 | `brain scan --all` |
| `brain review` | 審查 KRB 暫存區知識 | `brain review list` |
| `brain serve` | REST API / MCP Server | `brain serve --mcp` |
| `brain webui` | D3.js 瀏覽器視覺化 | `brain webui --port 7890` |
| `brain context` | 查詢（技術名，同 ask）| `brain context "JWT"` |
| `brain index` | 建立向量索引（含進度條）| `brain index` |
| `brain optimize` | VACUUM + ANALYZE + FTS5 rebuild | `brain optimize` |
| `brain clear` | 清除 session 工作記憶 | `brain clear` |
| `brain export` | 匯出知識庫 | `brain export --format neo4j` |
| `brain import` | 匯入知識庫 | `brain import data.json` |
| `brain analytics` | 使用率分析 | `brain analytics --export csv` |
| `brain deprecate` | 廢棄知識節點 | `brain deprecate <id>` |
| `brain lifecycle` | 節點生命週期 | `brain lifecycle <id>` |
| `brain counterfactual` | 反事實影響分析 | `brain counterfactual "換掉 PostgreSQL"` |
| `brain health-report` | 健康報告 | `brain health-report` |
| `brain doctor` | 環境診斷與修復 | `brain doctor --fix` |
| `brain init` | 低階初始化 | （一般用 setup 即可）|
| `brain meta` | 後設知識管理 | `brain meta --list` |

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

## 已移除命令

`learn`, `distill`, `validate`, `export-rules`, `daemon` 等已在 v10.x 清理。
