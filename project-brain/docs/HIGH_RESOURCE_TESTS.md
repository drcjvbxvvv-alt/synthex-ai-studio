# 高資源測試清單

> 需要 > 16GB RAM、GPU、或外部服務（Ollama）的測試。
> 目前開發機器為 16GB RAM Mac，這些測試暫時跳過，待設備準備好再執行。
>
> **最後更新**：2026-05-02（v0.50.0）

---

## 快速指令

```bash
# 日常開發（跳過所有高資源測試）
pytest tests/unit/ -m "not chaos and not benchmark" -q

# 當設備準備好時，逐項執行：
pytest -m chaos tests/chaos/ -v                        # ① Chaos/Load
pytest -m benchmark tests/benchmarks/ -v               # ② Benchmark
BRAIN_TEST_OLLAMA=1 pytest -m e2e_ollama -v            # ③ Ollama E2E
pytest tests/e2e/test_pipeline_e2e.py -v               # ④ Pipeline E2E（stub）
```

---

## 1. Chaos & Load 測試

### 1a. 100K 節點衰減壓力測試

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/chaos/test_decay_load.py` |
| **Marker** | `@pytest.mark.chaos` |
| **測試** | `TestDecayLoad::test_decay_100k_nodes_completes_within_budget` |
| **資源需求** | RAM 2-4GB（100K SQLite 記錄 + Python 物件） |
| **時間預算** | < 300 秒 |
| **說明** | 建立 100,000 個知識節點，執行 DecayEngine 全庫衰減（O(n) 迭代） |

### 1b. 一般 Chaos/Load 測試

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/chaos/test_chaos_and_load.py` |
| **Marker** | `@pytest.mark.chaos` |
| **測試** | `TestLoadL3Graph`（1000 nodes INSERT）、`TestLoadConcurrent`（20 threads）、`TestB3CRDTPerformance`（250 nodes conflict） |
| **資源需求** | RAM < 1GB，但需要快速 CPU 達成延遲目標 |
| **時間預算** | 各項 < 3s~50ms |
| **說明** | 節點寫入吞吐量、搜尋延遲、並發讀取、衝突偵測效能 |

**執行指令**：
```bash
pytest -m chaos tests/chaos/ -v
```

---

## 2. 效能基準測試

### 2a. 5000 節點效能基準

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/benchmarks/benchmark_perf_5k.py` |
| **Marker** | `@pytest.mark.benchmark` |
| **測試** | `TestPerf5K`：bulk write throughput ≥ 200 nodes/s、FTS5 p99 ≤ 300ms、avg ≤ 100ms、hybrid search p99 ≤ 300ms |
| **資源需求** | RAM 1-2GB（5K nodes + FTS5 indexes） |
| **前置** | 無外部依賴 |

### 2b. Recall 基準測試

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/benchmarks/benchmark_recall.py` |
| **Marker** | `@pytest.mark.benchmark` |
| **測試** | 50 nodes × 20 queries，量測 recall@K / MRR / nDCG |
| **資源需求** | RAM 500MB-1GB（含 sentence-transformers model loading） |
| **前置** | `pip install sentence-transformers`（~2GB model 首次下載） |
| **說明** | 如果 sentence-transformers 不可用，自動 fallback 到 LocalTFIDF（資源需求大幅降低） |

### 2c. Baseline Regression Guard

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/benchmarks/test_baseline_regression.py` |
| **Marker** | `@pytest.mark.benchmark` |
| **測試** | recall 不低於 baseline、latency 不超過 baseline |
| **資源需求** | 同 2b（內部呼叫 `benchmark_recall.compute_metrics()`） |

**執行指令**：
```bash
pytest -m benchmark tests/benchmarks/ -v
```

---

## 3. Ollama E2E 測試

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/e2e/test_pipeline_e2e.py` |
| **Marker** | `@pytest.mark.e2e_ollama` |
| **測試** | `TestPipelineOllama::test_real_judge_git_commit_signal` |
| **資源需求** | Ollama service on `localhost:11434` + `llama3.2:3b` model（~4GB VRAM 或 RAM） |
| **環境變數** | `BRAIN_TEST_OLLAMA=1` |
| **時間預算** | < 15 秒 per signal |
| **說明** | 使用真實 LLM（非 stub）判斷 git commit signal，驗證完整 pipeline 端到端流程 |

**前置設定**：
```bash
# 安裝 Ollama
curl -fsSL https://ollama.com/install.sh | sh

# 拉取測試用模型
ollama pull llama3.2:3b

# 執行測試
BRAIN_TEST_OLLAMA=1 pytest -m e2e_ollama tests/e2e/ -v
```

---

## 4. Embedding 模型測試

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/unit/test_embed_coldstart.py`、`tests/benchmarks/benchmark_recall.py` |
| **Marker** | 無（unit tests 無 marker；benchmark 有 `@pytest.mark.benchmark`） |
| **資源需求** | `pip install sentence-transformers` + 首次載入 ~2GB model |
| **說明** | `MultilingualEmbedder` 使用 `intfloat/multilingual-e5-small`（384 dim），需約 500MB-1GB RAM inference |
| **Fallback** | 不安裝 sentence-transformers 時自動 fallback 到 `LocalTFIDF`（zero-dep，< 10MB） |

**注意**：`test_embed_coldstart.py` 的 unit tests 使用 `BRAIN_EMBED_PROVIDER=tfidf` mock，不需要真實模型。真正吃記憶體的是 benchmark_recall.py 的 `detect_embedder()` 路徑。

---

## 5. D-01 LoRA 蒸餾（未實作，需 GPU）

| 項目 | 值 |
|------|-----|
| **檔案** | `project_brain/engines/knowledge_distiller.py`（架構已設計，待實作） |
| **Marker** | N/A（尚無測試） |
| **資源需求** | **NVIDIA GPU ≥ 16GB VRAM**（RTX 3090 / A100 / T4） |
| **依賴** | `unsloth` 或 `axolotl` + CUDA toolkit |
| **說明** | 從知識庫生成 Q&A 訓練集 → LoRA fine-tuning → adapter → Ollama 載入推論 |
| **狀態** | ROADMAP D-01，blocked on GPU 資源 |

**替代方案**：Google Colab T4（免費 ~15GB VRAM）或 RunPod / Lambda 按需 GPU。

---

## 6. E2E Pipeline 測試（stub judge）

| 項目 | 值 |
|------|-----|
| **檔案** | `tests/e2e/test_pipeline_e2e.py` |
| **Marker** | 無 marker（非 e2e_ollama 的部分） |
| **測試** | `TestSignalToL3Flow`（8 tests）、`TestPipelineLatency`（2 tests）、`TestPipelineWorkerLifecycle`（3 tests） |
| **資源需求** | RAM < 500MB（使用 stub judge，不需 LLM） |
| **時間預算** | single signal < 5s, batch 10 < 30s |
| **說明** | 不需 Ollama，使用 mock judge。資源需求中等，但 latency 測試在慢機器上可能 flaky |

**執行指令**：
```bash
pytest tests/e2e/test_pipeline_e2e.py -v -k "not Ollama"
```

---

## 資源需求等級對照

| 等級 | RAM | GPU | 外部服務 | 對應測試 |
|------|-----|-----|---------|---------|
| **LOW** | < 500MB | 不需要 | 不需要 | 一般 unit tests |
| **MEDIUM** | 500MB-1GB | 不需要 | 不需要 | benchmark_recall (TFIDF), E2E stub |
| **HIGH** | 1-4GB | 不需要 | 不需要 | 5K benchmark, 100K decay, embedding model |
| **VERY HIGH** | 4GB+ | 建議 | Ollama | E2E Ollama, real LLM judge |
| **GPU REQUIRED** | 16GB+ VRAM | **必須** | 不需要 | D-01 LoRA 蒸餾 |

---

## Pytest Markers 速查

```ini
# pytest.ini 中定義
markers =
    chaos:      Chaos & load tests（-m chaos）
    benchmark:  Performance benchmarks（-m benchmark）
    e2e_ollama: 需要 Ollama 的 E2E 測試（BRAIN_TEST_OLLAMA=1）
```

## 環境變數速查

| 變數 | 預設 | 用途 |
|------|------|------|
| `BRAIN_TEST_OLLAMA` | （未設定）| `1` = 啟用 Ollama E2E 測試 |
| `BRAIN_EMBED_PROVIDER` | （自動偵測）| `tfidf` / `none` / `multilingual` |
| `BRAIN_EMBED_LAZY` | （未設定）| `1` = 跳過 embedder test probe |

---

## 設備準備好後的執行順序建議

1. **先跑 benchmark**（最重要的品質門檻）：
   ```bash
   pytest -m benchmark tests/benchmarks/ -v
   ```

2. **再跑 chaos**（壓力測試確認穩定性）：
   ```bash
   pytest -m chaos tests/chaos/ -v
   ```

3. **安裝 Ollama 後跑 E2E**：
   ```bash
   ollama pull llama3.2:3b
   BRAIN_TEST_OLLAMA=1 pytest tests/e2e/ -v
   ```

4. **安裝 sentence-transformers 後跑 embedding recall**：
   ```bash
   pip install sentence-transformers
   BRAIN_EMBED_PROVIDER=multilingual pytest tests/benchmarks/benchmark_recall.py -v
   ```

5. **有 GPU 後實作 D-01 LoRA**（最後）
