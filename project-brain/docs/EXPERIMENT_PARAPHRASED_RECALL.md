# Paraphrased Recall 實驗報告

> **日期**：2026-05-04
> **版本**：v0.60.0
> **搜尋模式**：FTS5 only（零外部依賴）
> **目的**：量化「用戶用自己的話問，Brain 能不能找到正確知識」

---

## 1. 實驗設計

### 1.1 動機

先前 baseline 實驗（標題搜自己）recall@3 = 100%，但這無法代表真實使用場景。
企業用戶不會用知識庫內部的精確措辭提問，他們會：
- 用同義詞（"idempotency_key" → "冪等鍵"）
- 描述場景（"webhook 重複觸發" → "付款會不會扣兩次"）
- 用自然語言問問題（"how to prevent double charging"）

### 1.2 資料集

- **20 組原始知識**（seed nodes）
- **每組 3 個改寫查詢**（共 60 個查詢）
- **改寫難度分級**：
  - Level 1: 同義詞替換（保留關鍵字）
  - Level 2: ���景描述（不用原始術語）
  - Level 3: 自然語言問題（完全換說法）

**語言分佈**：中文 25 / 英文 20 / 中英混合 15
**知識類型分佈**：Rule 30 / Decision 15 / Pitfall 12 / ADR 3

### 1.3 搜尋配置

| 項目 | 值 |
|------|------|
| 搜尋引擎 | SQLite FTS5（零依賴） |
| Top-K | 3 (primary), 5 (secondary) |
| Embedder | 無（BRAIN_EMBED_PROVIDER=none） |
| LLM | 無（BRAIN_RELEVANCE_SELECTOR=keyword） |

---

## 2. 實驗結果

### 2.1 總體指標

| 指標 | 值 | 說明 |
|------|------|------|
| **Paraphrased Recall@3** | **70.0%** | 60 個改寫查詢中 42 個在 top-3 命中 |
| **Paraphrased Recall@5** | **70.0%** | top-5 無額外改善（命中都在前 3） |
| **MRR** | **0.5611** | 命中時平均排在第 1~2 位 |
| **Avg Latency** | **0.1 ms** | 極快（SQLite in-memory） |

### 2.2 與 Baseline 對比

| 場景 | Recall@3 | 差距 |
|------|----------|------|
| Baseline（標題搜自己） | 100% | — |
| **Paraphrased（改寫搜尋）** | **70%** | **-30%** |

**結論**：FTS5 在精確關鍵字匹配時完美，但面對改寫查詢有 30% 的語意落差。
這就是 Hybrid Search（向量搜尋）的價值空間。

### 2.3 按難度分層

| 難度 | Recall@3 | 查詢數 | 命中 |
|------|----------|--------|------|
| **Level 1**（同義詞替換） | **100%** | 20 | 20 |
| **Level 2**（場景描述） | **60%** | 20 | 12 |
| **Level 3**（自然語言問題） | **50%** | 20 | 10 |

**分析**：
- Level 1 全部命中 — FTS5 對關鍵字重疊的查詢表現完美
- Level 2 降至 60% — 缺少原始術語時開始失敗
- Level 3 降至 50% — 完全換說法時只有一半能找到

### 2.4 按語言分層

| 語言 | Recall@3 | 查詢數 | 命中 |
|------|----------|--------|------|
| 中文 | **68%** | 25 | 17 |
| 英文 | **55%** | 20 | 11 |
| 中英混合 | **93%** | 15 | 14 |

**分析**：
- 中英混合最高（93%）— 因為 Level 1 多為混合，且技術詞彙跨語言共享
- 中文（68%）優於英文（55%）— 可能因為中文知識的標題本身含有更多描述性詞彙
- 英文最低（55%）— Level 3 英文問句與中文種子節點交集最小

### 2.5 按知識類型分層

| 類型 | Recall@3 | 查詢數 | 命中 |
|------|----------|--------|------|
| Rule | **80%** | 30 | 24 |
| Decision | **60%** | 15 | 9 |
| Pitfall | **67%** | 12 | 8 |
| ADR | **33%** | 3 | 1 |

**分析**：
- Rule 最高（80%）— 規則類知識標題通常包含行動動詞，FTS5 較易匹配
- ADR 最低（33%）— 樣本小且 ADR 格式固定，改寫後術語差異大

---

## 3. 失敗案例分析（Top Misses）

| 查詢 | 難度 | 語言 | 為什麼找不到 |
|------|------|------|-------------|
| "為什麼不用固定窗口做限流" | L2 | zh | 原始知識標題用 "sliding window"，FTS5 無法匹配 "固定窗口" |
| "container 一直被 OOM kill 怎麼解決的" | L2 | mixed | "OOM kill" 出現在 content 但 FTS5 排名不夠高 |
| "為什麼 VPA 被關掉了" | L3 | zh | "VPA" 只在 content 尾部出現一次，標題是 "memory limit" |
| "how to reduce database queries..." | L3 | en | 原始用 "N+1 query problem"，語意相同但詞彙無交集 |
| "元件卸載時還在跑 API 呼叫會怎樣" | L2 | zh | 原始用 "useEffect cleanup"，中文改寫無重疊 |

**根因**：FTS5 是詞彙匹配引擎，當查詢與知識的**詞彙無交集**時完全失敗。
這正是向量搜尋（Hybrid Search）能解決的問題——語意相似但詞彙不同。

---

## 4. 關鍵結論

### 4.1 FTS5 的能力邊界

| 場景 | FTS5 表現 |
|------|-----------|
| 精確關鍵字 | 100%（完美） |
| 同義詞替換 | 100%（多語言技術詞共享） |
| 場景描述 | 60%（有詞彙重疊就找到，沒有就失敗） |
| 自然語言問題 | 50%（一半靠運氣） |

### 4.2 Hybrid Search 的預期價值

基於失敗案例分析，向量搜尋能覆蓋的場景：
- "固定窗口" ↔ "sliding window"（語意等價，詞彙無交集）
- "OOM kill" ↔ "memory limit"（同一概念的不同表述）
- "元件卸載" ↔ "useEffect cleanup"（中英語意等價）

**預期 Hybrid Recall@3 ≥ 85%**（基於 G-01 結果 97% 在標題查詢場景）

### 4.3 對企業的價值主張

> 「Brain 在純文字搜尋模式下，用戶用自己的話問問題已有 70% 命中率。
> 啟用向量搜尋後，預期提升至 85%+。
> 相比之下，Notion/Wiki 的搜尋依賴精確關鍵字，面對改寫查詢接近 0%。」

---

## 5. 改進方向

| 優先序 | 改進 | 預期效果 |
|--------|------|---------|
| P1 | 啟用 Hybrid Search（sentence-transformers） | recall@3: 70% → ~85% |
| P2 | Content 分段索引（content 切 chunk 入 FTS） | Level 2 改善 |
| P3 | 同義詞詞典（"VPA"↔"Vertical Pod Autoscaler"） | 特定術語改善 |
| P4 | Query expansion（用 LLM 擴充查詢） | Level 3 改善 |

---

## 6. 重現方式

```bash
cd project-brain
pytest tests/experiment/paraphrased_recall/test_paraphrased_recall.py -v -s

# 查看詳細報告
cat tests/experiment/paraphrased_recall/report.json | python -m json.tool
```

零依賴，< 1 秒完成。
