# FastAPI Knowledge Discovery 實驗報告

> **日期**：2026-05-04
> **版本**：v0.60.0
> **來源專案**：FastAPI（7,017 commits, 2018-2026）
> **目的**：量化「Brain 能在開發者踩坑前主動提醒」的能力

---

## 1. 實驗設計

### 1.1 核心問題

> 如果 Brain 知道 FastAPI 的 20 個常見陷阱，
> 當開發者描述一個會踩坑的任務時，Brain 能主動提醒嗎？

### 1.2 資料集

**20 個 FastAPI 真實陷阱**（來自 GitHub Issues）：

| 類別 | 數量 | 範例 |
|------|:---:|------|
| Dependency Injection | 5 | BackgroundTask 存取已關閉的 DB session |
| Async/Performance | 4 | sync def 阻塞 event loop |
| Pydantic/Validation | 4 | response_model 遞迴巢狀無限序列化 |
| Middleware/Deploy | 4 | CORS middleware 順序錯誤 |
| Security/Auth | 3 | OAuth2 scope 未自動驗證 |

**20 個任務描述**（自然語言，不含原始術語）：
- 中文 8 / 英文 10 / 中英混合 2
- 每個任務對應 1~2 個應被提醒的陷阱
- 用語模擬真實開發者向 AI 描述需求

### 1.3 搜尋模式

| 模式 | 引��� | 外部依賴 |
|------|------|:---:|
| FTS5 only | SQLite FTS5 全文搜尋 | 無 |
| Hybrid (TF-IDF) | FTS5 + LocalTFIDFEmbedder | 無 |

---

## 2. 實驗結果

### 2.1 總體指標

| 指標 | FTS5 | Hybrid (TF-IDF) | 差距 |
|------|:---:|:---:|:---:|
| **Context Discovery Rate** | **25%** | **25%** | 0% |
| **Nudge Discovery Rate** | **35%** | **35%** | 0% |
| **Combined (either)** | **35%** | **35%** | 0% |
| Avg Latency | 53 ms | 11 ms | -42ms |

### 2.2 按類別分層

| 類�� | Discovery Rate | 分析 |
|------|:---:|------|
| **Dependency Injection** | **80%** | 任務含 "background"/"session" 等 FTS5 可匹配的關鍵字 |
| **Middleware/Deploy** | **50%** | "CORS"/"rate limit" 部分匹配 |
| **Async/Performance** | **25%** | "async"/"event loop" 僅少量查詢含相關詞 |
| **Pydantic/Validation** | **0%** | 任務描述完全不含 "response_model"/"exclude_unset" 等術語 |
| **Security/Auth** | **0%** | 任務描述用 "管理員權限"/"token refresh" 而非 "OAuth2 scope" |

### 2.3 關鍵發現

#### TF-IDF Hybrid 無改善（0% improvement）

**原因**：LocalTFIDFEmbedder 使用 hash-based random projection，不具備真正的語意理解。它本質上仍是詞彙匹配（只是用不同的數學方式）。

**結論**：要突破 35% 的 discovery rate，需要**真正的語意向量**（sentence-transformers 或 OpenAI embeddings）。

#### FTS5 的能力邊界清晰

| 場景 | FTS5 能力 |
|------|-----------|
| 任務含原始技術詞（"background task", "CORS"） | ✅ 找得到 |
| 任務用場景描述（"email 通知不要阻塞"） | ⚠️ 部分（靠 "background" 匹配） |
| 任務完全換說法（"管理員才能存取"） | ❌ 完全找不到 |

---

## 3. 對企業的價值論述

### 3.1 當前能力（FTS5, 零成本）

> 「20 個已知 FastAPI 陷阱中，Brain 能主動提醒 7 個（35%），
> 尤其在 Dependency Injection 類場景達到 80% 發現率。
> 完全零成本——不需要 GPU、API key、或任何外部服務。」

### 3.2 改進路線圖

| 階段 | 預期 Discovery Rate | 需要什麼 |
|------|:---:|------|
| 現狀（FTS5） | 35% | 無（已具備） |
| +sentence-transformers | ~65-75% | 本地 GPU 或 4GB RAM |
| +Query expansion (LLM) | ~85%+ | API key (Claude Haiku) |

### 3.3 ROI 計算模型

```
前提：
  - 團隊 5 名工程師
  - 每人每週遇到 ~2 次「已知但忘了」的坑
  - 每次平均耗費 2 小時 debug

目前 35% discovery rate:
  節省 = 5人 × 2次/週 × 2小時 × 35% = 7 小時/週

啟用語意搜尋後 (75%):
  節省 = 5人 × 2次/週 × 2小時 × 75% = 15 小時/週

年化效益 = 15h × 50週 × $50/h = $37,500/年（5人團隊）
```

---

## 4. 失敗案例分析

### 完全失敗（0% discovery）的類別

**Pydantic/Validation 失敗原因**：

| 任務描述 | 期望知識 | 為什麼找不到 |
|----------|---------|-------------|
| "回傳使用者資料時包含文章列表" | "response_model circular references" | 「文章列表」vs「circular references」零交集 |
| "API 欄位可選用預設值" | "Optional fields with None default" | 「可選」vs「Optional」不同語言 |

**Security/Auth 失敗原因**：

| 任務描述 | 期望知識 | 為什麼找不到 |
|----------|---------|-------------|
| "實作管理員才能存取的 API" | "OAuth2 scopes not enforced" | 「管理員」vs「OAuth2 scopes」無交集 |
| "token refresh 觸發不正確" | "HTTPBearer returns 403" | 「refresh」vs「403」語意相關但詞彙不同 |

### 共同模式

**所有失敗案例的根因**：任務描述使用的**概念層級**（"管理員權限"）與知識庫的**實作層級**（"OAuth2 scope verification"）不在同一抽象層。

---

## 5. 改進建議

| 優先序 | 措施 | 預期效果 | 成本 |
|--------|------|---------|------|
| **P0** | 啟用 sentence-transformers embedder | +30% discovery rate | 4GB RAM |
| P1 | 知識新增 `description` 欄位（概念層級摘要） | 改善 FTS5 匹配 | 人工 |
| P2 | Query expansion（LLM 擴充查詢詞） | +15% on L3 queries | API 費用 |
| P3 | 同義詞詞典（"管理員"→"admin"→"OAuth2 scope"） | 特定詞改善 | 人工 |

---

## 6. 重現方式

```bash
cd project-brain
pytest tests/experiment/fastapi_knowledge_discovery/test_discovery.py -v -s
```

零依賴，< 2 秒完成。
