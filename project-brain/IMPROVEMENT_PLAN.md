# Project Brain — 改善規劃書

> **當前版本**：v0.11.0（2026-04-04）
> **文件用途**：待辦改善項目。已完成項目見 `CHANGELOG.md`。

---

## 待辦項目

| 優先 | ID | 影響 | 阻塞條件 | 狀態 |
|------|----|------|---------|------|
| ⏳ | REV-02 | 衰減效用幫助還是傷害召回率，目前未知 | 90 天真實使用數據 | 等待 |

**所有其他改善項目已完成**，詳見 `CHANGELOG.md`（v0.7.0–v0.11.0）。

---

## REV-02 — Decay 實際效用未量測

**問題**：無法驗證衰減是幫助還是傷害召回率。目前沒有基準數據可判斷 DecayEngine 是否讓「舊而有效」的知識被誤淘汰。

**量測方案**：
1. 對比有/無衰減兩組知識庫的召回率
2. 統計 `brain report` 中過時節點排前 3 的比例
3. 追蹤 deprecated 節點在被清除前的 access_count

**執行條件**：需 90 天以上真實使用數據（`brain_db.traces` + `analytics_engine`）。

詳見 `tests/TEST_PLAN.md` § 7 — REV-02 衰減效用量測

---

## 版本路線圖

| 版本 | 主題 | 狀態 |
|------|------|------|
| **v0.7.0** | 正確性優先（PERF-03/04, BUG-A03, REF-04, BUG-B01/B02） | ✅ 完成 |
| **v0.8.0** | 知識自適應（DEEP-05, ARCH-05, ARCH-06, FEAT-01） | ✅ 完成 |
| **v0.9.0** | 深化功能（DEEP-04, FED-01/02, CLI-02, FEAT-04, OBS-01） | ✅ 完成 |
| **v0.10.0** | 長期穩定（REF-01, CLI-01, ARCH-04） | ✅ 完成 |
| **v0.11.0** | AI 全自主（KRB-01, FEAT-03, BUG-C01/02/03） | ✅ 完成 |
| **v0.12.0** | 量測驗證（REV-02） | ⏳ 等待 90 天數據 |

---

## 架構完整度（v0.11.0）

| 層 / 模組 | 完整度 |
|----------|--------|
| L1a SessionStore | ✅ FEAT-04 session archive |
| L2 Episodes / Temporal | ✅ FEAT-03 `nodes_at_time()`；`brain history --at` |
| L3 KnowledgeGraph | ✅ |
| BrainDB | ✅ SCHEMA_VERSION=20；v14–v20 遷移全數完成 |
| DecayEngine | ✅ 7/7 因子（含 F6 採用率）；CONFLICTS_WITH edges |
| ContextEngineer | ✅ `[已棄用]` 標記；即時衰減 |
| NudgeEngine | ✅ `auto_resolve_batch()`；rule-based + LLM-assisted |
| ConflictResolver | ✅ LLM/Ollama 仲裁；非對稱 confidence 調整 |
| Federation | ✅ FED-01 審計；FED-02 語義去重；CLI-02 fed sync |
| KRB | ✅ KRB-01 AI 全自動裁決；source-based confidence；audit log |
| MCP Server | ✅ `report_knowledge_outcome` emit 閉環 |
| API Server | ✅ `GET /v1/knowledge/deprecated`；`POST /v1/knowledge/<id>/outcome` |
| CLI | ✅ history/restore/deprecated/session/fed/review 全部實裝 |
| 可觀測性 | ✅ structlog + `GET /v1/metrics` Prometheus |
| Analytics | ✅ `query_hit_rate()`（traces v20）；`useful_knowledge_rate()`（events emit） |
