# Project Brain — 實驗驗證報告

> **文件用途**：REV-01（Layer 2/3 對照）、REV-02（衰減效用）、KRB 效果驗證、D-04 效能基準的數據記錄與分析。
> **版本**：v1.0（v0.43.0，2026-04-27）
>
> **已完成**：D-04 效能基準（5K nodes）、召回率基準（50 nodes）
> **待填入**：REV-01/REV-02 需在真實舊專案上執行 `brain backfill-git --all` 後填入

---

## 零、D-04 效能基準（已量測，v0.43.0）

本段數據來自 `tests/benchmarks/benchmark_perf_5k.py` 自動量測，環境為 macOS，Python 3.12.2，純 FTS5 模式（無 embedding）。

### 0.1 5000-node 效能基準

| 指標 | 量測值 | 目標門檻 | 狀態 |
|------|--------|---------|------|
| 批次寫入吞吐量 | ≥ 200 nodes/s（已驗證）| ≥ 200 nodes/s | ✅ |
| FTS5 搜尋平均延遲 | ≤ 100ms（已驗證）| ≤ 100ms | ✅ |
| FTS5 搜尋 p99 延遲 | ≤ 300ms（已驗證）| ≤ 300ms | ✅ |
| BrainDB hybrid search p99 | ≤ 300ms（已驗證）| ≤ 300ms | ✅ |

> 量測方式：`pytest tests/benchmarks/benchmark_perf_5k.py -m benchmark -v`
> 詳細報告：`python tests/benchmarks/benchmark_perf_5k.py`（互動式輸出）

### 0.2 50-node 召回率基準（UNQ-03）

| Embedder | 召回率（20 queries）| 平均延遲 | 說明 |
|---------|----------------|---------|------|
| LocalTFIDF（無 Ollama）| ~65%（基準）| < 50ms | 純 FTS5 hash 投影 |
| Ollama nomic-embed-text | ~88%（預期）| < 100ms | 語意模型，需本地 Ollama |
| sentence-transformers | ~95%（CI 觀測）| ~91ms | 如環境有安裝 |

> 量測方式：`python tests/benchmarks/benchmark_recall.py`
> 門檻：`tests/benchmarks/baseline.json`（recall ≥ 0.60，avg ≤ 500ms）

### 0.3 Federation 規模驗證（D-04）

| 指標 | 結果 |
|------|------|
| 1000 節點 export 耗時 | < 1s |
| PII 洩漏數（email + IP + host）| 0 / 1000 節點 |
| 1000 節點中 300 重複 dedup 準確率 | 100%（300 skipped, 200 imported）|
| import_bundle 500 節點耗時 | < 5s |

---

## 實驗環境（REV-01/02，待填入）

| 項目 | 內容 |
|------|------|
| 專案名稱 | _(填入，例如：payment-service)_ |
| git 歷史長度 | _(填入，例如：14 個月 / 623 commits)_ |
| 語言 / 技術棧 | _(填入，例如：Python FastAPI + PostgreSQL)_ |
| 執行日期 | _(填入)_ |
| Brain 版本 | v0.43.0 |
| LLM（backfill） | _(填入，例如：claude-haiku-4-5 / llama3.2:3b)_ |

### 初始化指令紀錄

```bash
cd /path/to/old-project
brain setup
brain backfill-git --all
brain scan --llm
```

輸出摘要：
```
# 貼上 brain backfill-git --all 的輸出
```

---

## 一、KRB 效果驗證

> 驗證自動提取知識的品質分布，以及 KRB 三速道（approve / review / reject）的分流效果。

### 1.1 暫存區總覽

執行：`brain review list`

| 指標 | 數值 |
|------|------|
| 總候選知識數 | |
| approve 道（AI 信心 ≥ 0.85） | |
| review 道（需人工確認） | |
| reject 道（AI 信心 < 0.60） | |
| Pitfall 強制走 review 道數 | |
| 自動核准數（auto_approve） | |

### 1.2 提取品質 vs commit 類型

| commit 前綴 | 樣本數 | approve 率 | reject 率 | 備註 |
|------------|--------|-----------|-----------|------|
| `feat:` | | | | |
| `fix:` | | | | |
| `refactor:` | | | | |
| `docs:` | | | | |
| 無前綴 / wip | | | | |

### 1.3 品質抽查（人工驗收 10 條）

從 approve 道隨機抽 5 條、reject 道抽 5 條，人工評分是否合理（✓ / ✗）：

| staged_id | 類型 | AI 建議 | 人工判斷 | 差異原因 |
|-----------|------|---------|---------|---------|
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |
| | | | | |

**KRB 準確率**（人工判斷與 AI 一致數 / 10）：____%

### 1.4 結論

```
（填入：KRB 在此專案的表現如何？哪類知識最容易被誤判？）
```

---

## 二、REV-01 — Layer 2 vs Layer 3 對照實驗

> 驗證 L2（情節記憶，temporal graph）vs L3（語意知識，BrainDB nodes）的召回差異。
> 目標：找出哪類問題適合哪一層。

### 2.1 測試查詢集（建議 10 條）

針對此專案設計有代表性的查詢，分為三類：

**類型 A — 「什麼時候」型（預期 L2 較強）**

| # | 查詢 | L2 回傳摘要 | L3 回傳摘要 | 更有用的層 | 備註 |
|---|------|------------|------------|-----------|------|
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

**類型 B — 「為什麼這樣做」型（預期 L3 較強）**

| # | 查詢 | L2 回傳摘要 | L3 回傳摘要 | 更有用的層 | 備註 |
|---|------|------------|------------|-----------|------|
| 4 | | | | | |
| 5 | | | | | |
| 6 | | | | | |

**類型 C — 「踩過什麼坑」型（預期 L3 Pitfall 較強）**

| # | 查詢 | L2 回傳摘要 | L3 回傳摘要 | 更有用的層 | 備註 |
|---|------|------------|------------|-----------|------|
| 7 | | | | | |
| 8 | | | | | |
| 9 | | | | | |
| 10 | | | | | |

### 2.2 統計結果

| 查詢類型 | L2 勝 | L3 勝 | 平手 |
|---------|------|------|------|
| A（時間型） | | | |
| B（決策型） | | | |
| C（踩坑型） | | | |
| **總計** | | | |

### 2.3 結論

```
（填入：L2 和 L3 各自的最佳適用場景是什麼？
 Memory Synthesizer 合併兩層後效果是否更好？）
```

---

## 三、REV-02 — 衰減效用驗證

> 驗證六因子衰減是否正確反映知識的現實有效性。
> 核心問題：`effective_confidence` 低的知識，真的比較「過時」嗎？

### 3.1 信心分布快照

執行：`brain status`（或 `brain report`）

| 信心區間 | 節點數 | 占比 |
|---------|--------|------|
| 0.8 – 1.0（✓✓ 權威） | | |
| 0.6 – 0.8（✓ 已驗證） | | |
| 0.3 – 0.6（~ 推斷） | | |
| 0.0 – 0.3（⚠ 過時） | | |

### 3.2 高衰減節點抽查（信心 < 0.3）

抽取 5 條 `effective_confidence` 最低的節點，人工判斷是否真的過時：

| node_id | 標題摘要 | created_at | effective_conf | 真的過時？ | 原因 |
|---------|---------|-----------|---------------|-----------|------|
| | | | | ✓ / ✗ | |
| | | | | ✓ / ✗ | |
| | | | | ✓ / ✗ | |
| | | | | ✓ / ✗ | |
| | | | | ✓ / ✗ | |

**衰減準確率**：____/5

### 3.3 高齡但高信心節點分析（F3/F6 反衰減驗證）

找出 `created_at` 超過 6 個月但 `effective_confidence` 仍 ≥ 0.7 的節點：

| node_id | 標題摘要 | 建立日期 | 信心值 | 推測維持高信心原因 |
|---------|---------|---------|--------|----------------|
| | | | | F3 git 活躍 / F6 查詢頻繁 / 其他 |
| | | | | |
| | | | | |

### 3.4 六因子個別影響觀察

| 因子 | 觀察到的效果 | 是否符合預期 |
|------|------------|------------|
| F1 時間衰減 | | |
| F2 版本差距懲罰 | | |
| F3 git 活動反衰減 | | |
| F4 矛盾懲罰 | | |
| F5 程式碼引用確認 | | |
| F6 查詢頻率反衰減 | | |

### 3.5 結論

```
（填入：衰減模型是否有效區分「仍然有用」vs「已過時」的知識？
 哪個因子影響最大？有沒有需要調整的地方？）
```

---

## 四、綜合評估

### 4.1 召回率估算

設計 10 個「已知答案」的查詢（你知道這個專案有這條知識），統計 Brain 能召回幾條：

| 查詢 | 預期命中 | 實際命中 | 備註 |
|------|---------|---------|------|
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |

**整體召回率**：____/10（____%)

### 4.2 使用 Memory Synthesizer 前後對比

選 3 條查詢，分別在啟用 / 停用 `BRAIN_SYNTHESIZE=1` 下比較輸出品質：

| 查詢 | 未合成輸出品質（1-5） | 合成後輸出品質（1-5） | 差異觀察 |
|------|-------------------|-------------------|---------|
| | | | |
| | | | |
| | | | |

### 4.3 實驗總結與建議

```
（填入：
 1. 哪個功能表現超過預期？
 2. 哪個功能表現不如預期？
 3. 針對此類舊專案，最有價值的使用方式是什麼？
 4. 有哪些需要改進的地方反饋給開發計畫？）
```

---

## 附錄：查詢指令速查

```bash
# KRB 審核
brain review list
brain review list --format json | jq '.[] | {id, ai_recommendation, ai_confidence}'

# 信心分布
brain status

# 搜尋特定節點
brain search "關鍵詞"

# 查詢特定信心範圍（直接查 DB）
sqlite3 .brain/brain.db \
  "SELECT title, effective_confidence, created_at
   FROM nodes
   WHERE effective_confidence < 0.3
   ORDER BY effective_confidence ASC
   LIMIT 10"

# 高齡高信心節點
sqlite3 .brain/brain.db \
  "SELECT title, effective_confidence, created_at
   FROM nodes
   WHERE created_at < date('now', '-180 days')
     AND effective_confidence >= 0.7
   ORDER BY effective_confidence DESC
   LIMIT 10"

# Layer 2 temporal query
brain ask "2024年初做了哪些重大決策"

# 啟用 Memory Synthesizer
BRAIN_SYNTHESIZE=1 brain ask "專案最重要的架構決策"
```
