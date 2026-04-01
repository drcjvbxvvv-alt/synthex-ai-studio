# Project Brain — 安裝指南

> **推薦配置**：Python（SQLite 擴充版）+ sqlite-vec C 擴充 + Ollama nomic-embed-text
> 此組合提供最高語意召回率與最快搜尋速度，且完全免費、資料不離開本機。

---

## 效能配置對比

在選擇安裝方式之前，先了解不同配置的效能差距：

### Embedding 後端對比

| 配置 | 向量維度 | 語意召回率 | 費用 | 說明 |
|------|---------|-----------|------|------|
| LocalTFIDF（預設 fallback）| 256 dim | ~65% | 免費 | 純 Python hash 投影，只理解關鍵字重疊 |
| **Ollama nomic-embed-text** ⭐ | 768 dim | ~88% | 免費 | 神經網路語意模型，本地執行 |
| OpenAI text-embedding-3-small | 1536 dim | ~90% | 付費 | 雲端 API，$0.02/1M tokens |

> **為什麼 LocalTFIDF 只有 65%？**
> 它使用隨機 hash 投影，本質上只計算詞彙重疊。搜尋「authentication issue」，
> 無法找到「JWT RS256 規則」——因為兩者沒有共同詞彙。
> nomic-embed-text 訓練了語意關聯，知道 JWT ≈ token ≈ authentication。

---

### 向量搜尋引擎對比

sqlite-vec C 擴充 vs 純 Python cosine similarity fallback：

| 知識節點數 | Pure Python cosine | sqlite-vec C 擴充 | 加速倍數 |
|-----------|-------------------|------------------|---------|
| 100 nodes | ~5 ms | <1 ms | ~10× |
| 500 nodes | ~25 ms | ~3 ms | ~8× |
| 1,000 nodes | ~80 ms | ~8 ms | ~10× |
| 5,000 nodes | ~400 ms | ~25 ms | ~16× |

> **為什麼差這麼多？**
> Pure Python cosine 需要在 Python 層面逐一遍歷所有向量（受 GIL 限制）。
> sqlite-vec 是 C 實作的 SQLite 擴充，直接在資料庫引擎內運算，無 Python 開銷。
> 隨著知識庫成長，差距持續擴大。未來版本將支援 ANN 索引（O(log N) 搜尋）。

*以上數據為 768 維向量的典型估算值，實際依硬體而異。*

---

### 完整搜尋模式對比

| 模式 | 召回率 | 速度（1K nodes）| 啟用條件 |
|------|--------|----------------|---------|
| FTS5 純關鍵字 | ~60% | <5 ms | 預設（永遠可用）|
| FTS5 + LocalTFIDF + Python cosine | ~68% | ~80 ms | 無需設定 |
| FTS5 + LocalTFIDF + sqlite-vec C | ~68% | <10 ms | sqlite-vec 載入成功 |
| **FTS5 + Ollama 768d + sqlite-vec C** ⭐ | **~88%** | **<15 ms** | **推薦配置** |
| FTS5 + OpenAI 1536d + sqlite-vec C | ~90% | <20 ms | 需 API Key |

---

## 推薦安裝步驟（最佳效能）

### Step 1：確認 Python 已開啟 SQLite 擴充支援

sqlite-vec 需要 Python 編譯時開啟 `--enable-loadable-sqlite-extensions`。

**pyenv 用戶：**

```bash
# 重新編譯 Python（一次性操作）
PYTHON_CONFIGURE_OPTS='--enable-loadable-sqlite-extensions' \
  pyenv install --force $(pyenv version-name)

# 重新建立 virtualenv（如果有）
pyenv virtualenv --force $(pyenv version-name) myenv
```

**Homebrew 用戶（已內建，無需額外設定）：**

```bash
brew install python@3.12
```

**驗證：**

```python
import sqlite3
conn = sqlite3.connect(":memory:")
conn.enable_load_extension(True)   # 若無報錯即代表支援
print("✓ SQLite 擴充支援已開啟")
```

---

### Step 2：安裝 Project Brain

```bash
pip install "project-brain[mcp]"
```

這會安裝：`flask`、`flask-cors`、`sqlite-vec`、`mcp`

---

### Step 3：安裝 Ollama 並拉取語意模型

```bash
# 安裝 Ollama（macOS）
brew install ollama

# 啟動服務
ollama serve &

# 拉取推薦的 embedding 模型（768 維，約 274 MB）
ollama pull nomic-embed-text
```

**為什麼選 nomic-embed-text？**

| 模型 | 維度 | 大小 | 語意品質 |
|------|------|------|---------|
| nomic-embed-text ⭐ | 768 | 274 MB | 高（MTEB Rank #1 開源小模型）|
| mxbai-embed-large | 1024 | 670 MB | 更高（但佔用更多空間）|
| all-minilm | 384 | 46 MB | 中（輕量但品質較低）|

---

### Step 4：初始化專案

```bash
cd /your/project
brain setup
```

完成後：
- 建立 `.brain/brain.db`
- 安裝 git post-commit hook
- 偵測 Claude Code / Cursor 並設定 MCP

---

### Step 5：建立向量索引

```bash
brain index
```

為現有知識節點建立 768 維向量索引。新增的知識（`brain add` / `brain sync`）自動索引。

---

### Step 6：驗證完整效能鏈

```bash
brain doctor
```

全綠代表推薦配置已完整啟用：

```
向量搜尋引擎
────────────────────────────────────────────
✓  Layer 1  套件已安裝  (sqlite-vec 0.1.9)
✓  Layer 2  SQLite C 擴充載入成功
✓  Layer 3  vec_distance_cosine 運算正確  (dist=0.0000)
✓  搜尋路徑  C 擴充加速  （FTS5 × 0.4 + 向量 × 0.6）
✓  Embedding  Ollama  (nomic-embed-text，768 dim，本地免費)
```

---

## 基本安裝（無 Ollama，使用 LocalTFIDF fallback）

若不需要最高語意召回率，或在 CI / 受限環境：

```bash
pip install project-brain
brain setup
```

此配置使用 LocalTFIDF（256 dim，純 Python，零依賴），召回率約 65%，仍優於純關鍵字搜尋。

---

## MCP 設定（Claude Code）

```json
// ~/.claude/settings.json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "project_brain.mcp_server"],
      "env": {"BRAIN_WORKDIR": "/your/project"}
    }
  }
}
```

`brain setup` 會自動偵測並寫入此設定，通常無需手動操作。

---

## 環境變數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `BRAIN_WORKDIR` | 當前目錄 | 預設專案目錄（省略 --workdir）|
| `ANTHROPIC_API_KEY` | — | AI 知識提取（brain scan / sync）|
| `BRAIN_LLM_PROVIDER` | `anthropic` | `openai` = Ollama / LM Studio |
| `BRAIN_LLM_BASE_URL` | `http://localhost:11434/v1` | 本地 LLM 端點 |
| `BRAIN_LLM_MODEL` | `claude-haiku-4-5-20251001` | 知識提取模型 |
| `BRAIN_EMBED_PROVIDER` | 自動偵測 | `none` = 停用向量，純 FTS5 |
| `BRAIN_SYNTHESIZE` | `0` | `1` = 啟用記憶融合（opt-in）|
| `BRAIN_API_KEY` | — | `brain serve` REST API 認證 |

---

## 多專案

`brain` 自動從當前目錄往上找 `.brain/`，類似 git 的 `.git/` 偵測邏輯：

```bash
cd ~/projects/payment-service
brain ask "退款邏輯"    # 使用 payment-service/.brain/

cd ~/projects/auth-service
brain ask "JWT 設定"    # 使用 auth-service/.brain/
```

每個專案擁有獨立記憶庫，互不干擾。
