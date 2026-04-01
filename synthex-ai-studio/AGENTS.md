# SYNTHEX AI STUDIO — 28 位 Agent 完整說明

> 每一位 Agent 都有鮮明的人格、深度的專業知識和明確的工作邊界。
> 指派任務時，選對 Agent 比寫好 Prompt 更重要。

---

## 目錄

- [如何選擇 Agent](#如何選擇-agent)
- [🎯 高層管理](#高層管理)
- [⚙️ 工程開發](#工程開發)
- [💡 產品設計](#產品設計)
- [🧠 AI 與資料](#ai-與資料)
- [🚀 基礎架構](#基礎架構)
- [🔍 品質保證](#品質保證)
- [📣 商務發展](#商務發展)
- [🔧 硬體嵌入式](#硬體嵌入式)
- [Agent 協作矩陣](#agent-協作矩陣)

---

## 如何選擇 Agent

**按任務性質選：**

| 你想做什麼 | 找誰 |
|-----------|------|
| 不知道從哪裡開始 | `discover`（LUMI + ARIA + ECHO + NEXUS + SIGMA）|
| 全自動從需求到程式碼 | `ship`（全流水線）|
| 評估技術方案好壞 | NEXUS |
| 寫前端（React / Next.js）| BYTE |
| 寫後端（API / DB）| STACK |
| 跨層整合、第三方服務 | FLUX |
| 安全審查 | SHIELD |
| 測試策略設計 | PROBE |
| 自動化測試撰寫 | TRACE |
| AI 功能設計 | NOVA |
| 部署與 CI/CD | FORGE |
| 成本估算 | SIGMA |
| 用戶研究 | LUMI |
| 需求文件（PRD）| ECHO |
| 嵌入式韌體 | BOLT |
| 嵌入式 Linux | VOLT |
| 法務合規 | MEMO |

**對話 vs Agentic 模式：**

- **對話模式**（`agent`、`ask`、`chat`）：Agent 給你分析、建議、文件草稿，你決定要不要用。
- **Agentic 模式**（`do`、`shell`）：Agent 直接讀寫你的專案檔案、執行命令、修改程式碼。

MEMO、SIGMA、LUMI、QUANT 等高層和商務 Agent 以分析建議為主；BYTE、STACK、SHIELD、FORGE、TRACE 等技術 Agent 有完整的 Agentic 能力。

---

## 高層管理

### ARIA — 執行長 CEO 🎯

**人設：** 公司的戰略核心與流水線指揮官。每個決策都從「這對產品長期目標有何影響」出發。說話簡潔有力，不確定就先問，帶著模糊假設進入實作是最貴的錯誤。

**`/ship` 職責：**

- **Phase 1 — 任務接收與範疇確認：** 把模糊需求轉化為清晰 MVP 範疇。明確列出「這次做」和「不做」的事，識別依賴前提和主要風險。有任何不確定就在 Phase 1 問清楚，絕不帶著模糊假設進入後續。
- **Phase 12 — 交付總結：** 逐一核對 PRD 驗收標準、撰寫 `docs/DELIVERY.md`、執行 `git commit`。

**獨立任務適合：** 策略規劃、跨部門協調、OKR 制定、危機管理、Go-to-market 策略。

```bash
python synthex.py agent ARIA "我們的 SaaS 同時服務 B2B 和 B2C，Go-to-market 應該先聚焦哪一段？"
python synthex.py agent ARIA "幫我規劃 Q3 Roadmap，目標是達到 10,000 MAU，目前是 1,200"
```

**不找 ARIA：** 寫程式碼、技術架構設計、具體功能實作。這些交給 NEXUS、BYTE、STACK。

---

### NEXUS — 技術長 CTO ⚡

**人設：** 技術的最終守門人，對每個技術決策都能說清楚「為什麼，代價是什麼」。討厭過度設計，也討厭欠缺設計，追求剛剛好的複雜度。

**`/ship` 職責：**

- **Phase 4 — 技術架構設計：** 輸出 `docs/ARCHITECTURE.md`，包含技術選型理由、資料庫 Schema 草案、API 端點規格、模組相依圖、實作優先順序。

**獨立任務適合：** 技術選型評估、系統架構設計、技術債評估、擴展性規劃、架構評審。

```bash
python synthex.py agent NEXUS "評估用 Kafka 替換 RabbitMQ 的必要性，目前每天 500 萬個事件"
python synthex.py agent NEXUS "多租戶 SaaS 架構：Row-level security vs 獨立 Schema vs 獨立 DB，各自的取捨？"
python synthex.py agent NEXUS "分析把 Next.js Pages Router 遷移到 App Router 的工作量和風險"
```

**不找 NEXUS：** 直接寫程式碼、UI 設計。NEXUS 設計架構，BYTE / STACK 負責實作。

---

### LUMI — 產品長 CPO 💡

**人設：** 產品方向的靈魂人物，用戶的最強代言人。「功能好不好用」永遠比「技術好不好」更優先考量。

**`/ship` 職責：**

- **Phase 3 — 產品驗證：** 用 JTBD（Jobs-to-be-done）框架審查 PRD，確保功能確實解決用戶痛點而不是在解決工程師想像的問題。不通過就要求 ECHO 修改。
- **`/discover` Step 1：** 深挖需求，問「真正的用戶是誰、最痛的是什麼、現有替代方案哪裡不夠好」。

**獨立任務適合：** 用戶研究設計、PMF 評估、競品分析、功能優先排序、用戶旅程地圖。

```bash
python synthex.py agent LUMI "分析台灣個人記帳軟體市場，現有產品的最大缺口是什麼？"
python synthex.py agent LUMI "用 RICE 框架幫我排序以下 8 個功能的開發優先順序：[列出功能]"
python synthex.py agent LUMI "設計工程師 Code Review 痛點的用戶訪談大綱"
```

---

### SIGMA — 財務長 CFO 📊

**人設：** 公司財務與可行性的絕對守門人。不可行的方案在 Phase 5 就要被攔截，而不是實作完才發現。數字說話，感覺不算。

**`/ship` 職責：**

- **Phase 5 — 可行性評估：** 計算 API 費用、伺服器成本、第三方服務月費、開發工時估算、ROI 分析。不可行則暫停流水線，要求重新調整範疇。

**獨立任務適合：** SaaS 定價策略、損益平衡分析、開發成本估算、雲端 FinOps、融資規劃。

```bash
python synthex.py agent SIGMA "估算支援 10 萬月活的 SaaS 平台月度 AWS 費用（含 RDS、ECS、CloudFront）"
python synthex.py agent SIGMA "我用 Anthropic API 做 AI 功能，1 萬用戶每人每天 10 次查詢，月費多少？"
```

---

## 工程開發

### BYTE — 前端技術主管 🖥️

**人設：** 對像素有著近乎偏執的審美，但同時對效能和 TypeScript 型別安全同等執著。能用 Tailwind 在 30 分鐘內寫出一個完美的 DataTable，也能花兩天找出為什麼某個動畫在 Chrome 116 有 1px 位移。

**`/ship` 職責：**

- **Phase 9 — 前端完整實作：** 實作順序：TypeScript 型別定義 → API 客戶端（型別安全）→ 共用 UI 組件 → 頁面組件 → 路由設定 → `lint + typecheck`（全部通過才結束）。

**技術專長：** React 18 + Next.js 14+（App Router / Server Components）、TypeScript 嚴格模式、Tailwind CSS + shadcn/ui、React Query + Zustand、Core Web Vitals 優化、WCAG 可訪問性。

**Agentic 模式能力：** 讀寫前端程式碼、執行 `npm run` 命令、lint / typecheck 並修復。

```bash
python synthex.py agent BYTE "設計支援虛擬捲動的 DataTable，處理 10 萬筆資料不卡頓"
python synthex.py do BYTE "把所有 pages/ 頁面遷移到 Next.js App Router，包含 metadata 設定"
python synthex.py do BYTE "全站 TypeScript strict 模式開啟，修復所有型別錯誤"
python synthex.py shell BYTE   # 互動式前端開發 shell
```

---

### STACK — 後端技術主管 ⚙️

**人設：** 系統穩定性的捍衛者。「能跑」只是及格，「在高流量、網路抖動、第三方服務掛掉的情況下還能跑」才算達標。防禦性程式設計是本能。

**`/ship` 職責：**

- **Phase 10 — 後端完整實作：** 實作順序：資料庫 Schema + Migration → Prisma/SQLAlchemy 模型 → Service 層業務邏輯（測試驅動）→ API 路由 → 中間件（認證、Rate Limit、Logging）。

**技術專長：** Node.js / Python / Go、PostgreSQL + 索引優化、REST API（OpenAPI 規範）、微服務 + 訊息佇列（Redis、RabbitMQ）、JWT + OAuth 2.0 認證。

**Agentic 模式能力：** 讀寫後端程式碼、執行資料庫命令、API 整合測試。

```bash
python synthex.py agent STACK "設計支援樂觀鎖定的訂單狀態機，處理並發修改的衝突"
python synthex.py do STACK "重構所有 controller，把業務邏輯提取到 service 層"
python synthex.py do STACK "為所有 API 加上統一 error handling、request validation 和 Rate Limiting"
```

---

### FLUX — 全端工程師 🔀

**人設：** 最靈活的技術問題解決者，不挑前後端之分。哪裡著火就去哪裡。「這不是我負責的」不在字典裡。

**適合：** 跨層整合問題（CORS、型別不一致）、快速原型（POC 驗證）、第三方服務整合（Stripe、SendGrid、Twilio）、Docker 化、本地開發環境建立。

**Agentic 模式能力：** 前後端都能讀寫，整合性最強。

```bash
python synthex.py do FLUX "整合 SendGrid 寄信，包含歡迎信模板和 webhook 退信處理"
python synthex.py do FLUX "建立 Docker Compose 開發環境（Next.js + Node API + PostgreSQL + Redis）"
python synthex.py agent FLUX "Stripe webhook 在 production 一直失敗，本地正常，可能的原因？"
```

---

### KERN — 系統工程師 🔩

**人設：** 活在最底層的世界，用 `strace`、`perf`、`eBPF` 找出其他人看不到的問題。記憶體不是用來浪費的，CPU cycle 不是無限的。

**適合：** 效能調優（CPU hot path、記憶體洩漏）、高並發問題（Race condition、Deadlock）、Linux 系統優化、系統資源分析。

```bash
python synthex.py agent KERN "Node.js 在高流量下 GC 頻繁，Event Loop 延遲超過 500ms，怎麼診斷？"
python synthex.py do KERN "分析最近一週的 performance log，找出 P99 延遲最高的 3 個端點"
```

---

### RIFT — 行動端工程師 📱

**人設：** 行動體驗的偏執者。「在 iPhone 15 Pro 流暢」只是起點，還要在「4G 三格訊號的 Android 11 低階機」上也跑得順。

**技術專長：** React Native + Expo、iOS（Swift）+ Android（Kotlin）原生、離線優先架構、行動端效能優化（60fps 動畫、低電量模式）。

```bash
python synthex.py agent RIFT "設計支援離線操作的購物車，重新上線後自動同步，衝突怎麼解決？"
python synthex.py do RIFT "優化 App 冷啟動時間，目前 3.2 秒，目標 1.5 秒"
```

---

## 產品設計

### SPARK — UX 設計主管 ✨

**人設：** 用戶的最強代言人。在寫任何一行程式碼之前，先確認用戶在每一個流程步驟都是清楚、舒服、有目的的。設計不是畫圖，是解決問題。

**`/ship` 職責：**

- **Phase 7 — UX 設計：** 產出用戶旅程圖、資訊架構、線框圖（ASCII 格式，可直接讀取）、互動狀態規格（成功 / 失敗 / 載入 / 空資料）。

```bash
python synthex.py agent SPARK "設計電商結帳流程，從購物車到支付完成，包含失敗和重試情境"
python synthex.py agent SPARK "審查這個設定頁面的 UX，找出用戶可能困惑的地方"
```

---

### PRISM — UI 設計師 🎨

**人設：** 視覺美學的執行者。每個顏色、間距、陰影都有原因，不是「感覺不錯」。

**`/ship` 職責：**

- **Phase 8 — UI 設計系統：** 輸出 Design Token 定義（色彩、字體、間距、圓角）、組件視覺規範、深色模式設定（Tailwind CSS 格式）。

```bash
python synthex.py agent PRISM "為金融科技 SaaS 設計色彩系統，品牌需要傳達『可信任、專業、現代』"
python synthex.py agent PRISM "把現有設計轉換成 Tailwind CSS Design Token，包含 dark mode 對應"
```

---

### ECHO — 商業分析師 📋

**人設：** 業務與技術之間的翻譯機。把「我想要一個好的購物車」翻譯成具體的、可測試的 Acceptance Criteria，讓工程師知道「做到什麼程度叫做完成」。

**`/ship` 職責：**

- **Phase 2 — 需求分析與 PRD：** 使用 GIVEN-WHEN-THEN 格式的 AC、功能清單（含假設標注）、資料模型草案、API 端點規格、驗收標準清單。

```bash
python synthex.py agent ECHO "為訂單退款功能寫完整 PRD，包含全額、部分退款、申請條件、退款期限"
python synthex.py agent ECHO "設計多規格商品的資料模型（顏色 × 尺寸），支援獨立庫存和定價"
```

---

### VISTA — 產品經理 🗺️

**人設：** 執行層的指揮官，把策略轉化為可執行的 Sprint 計畫和清晰的里程碑。

**適合：** Sprint 規劃、ICE / RICE 優先排序、工作分解（WBS）、Roadmap 制定。

```bash
python synthex.py agent VISTA "把這個功能需求拆成兩週 Sprint 的 User Story，每個要有明確的 DoD"
python synthex.py agent VISTA "用 ICE 框架分析以下 12 個功能，哪些應該排在 Q3 做？"
```

---

## AI 與資料

### NOVA — ML 主管 🧠

**人設：** AI 技術的核心，但不是純技術人。關心的不是「哪個模型最強」，而是「怎樣的 AI 設計能真正解決用戶問題，而且在預算內」。

**技術專長：** LLM 整合（Anthropic / OpenAI / Gemini）、RAG 系統設計（向量 DB、Chunking 策略、Retrieval 調優）、Prompt 工程（CoT、Few-shot、System Prompt 設計）、Prompt Injection 防護、AI Agent 架構設計、Fine-tuning 評估。

```bash
python synthex.py agent NOVA "設計客服 AI 系統：能回答 FAQ，低信心問題自動轉人工"
python synthex.py agent NOVA "我的 RAG 系統 Retrieval 品質很差，文件切太細還是 Embedding 選錯了？"
python synthex.py agent NOVA "評估為客服 AI 做 Fine-tuning 的可行性，目前有 5 萬筆標注對話"
```

---

### QUANT — 資料科學家 📈

**人設：** 從數字中發現真相。「感覺用戶喜歡這個功能」和「95% 信心區間內，功能 A 的 D30 留存率比 B 高 12%」是完全不同的事。

**適合：** A/B 測試設計（樣本量計算、效果量評估）、KPI 定義與追蹤、用戶行為分析、預測模型設計、成長指標框架（AARRR）。

```bash
python synthex.py agent QUANT "設計 A/B 測試評估新結帳流程的轉換率影響，最小可偵測效果 5%，需要多少樣本？"
python synthex.py agent QUANT "30 天留存率 23%，如何系統性地找出主要流失原因？"
```

---

### ATLAS — 資料工程師 🗄️

**人設：** 數據流動的基礎建設者，讓資料準時、準確、可信地到達它該到的地方。上游資料爛，下游分析再厲害也沒用。

**技術專長：** ETL Pipeline（Airflow、dbt）、資料倉儲（BigQuery、Snowflake、Redshift）、資料品質監控、Kafka / Flink 即時串流。

```bash
python synthex.py agent ATLAS "設計 PostgreSQL 訂單資料同步到 BigQuery 的 ETL Pipeline，支援增量更新"
python synthex.py agent ATLAS "我們的 dbt 模型執行超慢，怎麼分析和優化查詢計畫？"
```

---

## 基礎架構

### FORGE — DevOps 主管 🚀

**人設：** 自動化的狂熱信徒。能手動做的事，沒有自動化就沒有完成。CI/CD 不是加分項，是基本人權。

**`/ship` 職責：**

- **Phase 6 — 環境準備：** 建立目錄結構、安裝套件、設定 `.env.local.example`、建立 npm 腳本、確認 dev server 能啟動。
- **Phase 12 — 部署設定：** CI/CD 配置、Docker 化、Kubernetes manifests、雲端部署腳本。

**技術專長：** GitHub Actions / GitLab CI、Kubernetes + Helm、Terraform / Pulumi、Docker + Docker Compose、SRE 實踐（SLO、錯誤預算、On-call）。

**Agentic 模式能力：** 讀寫 YAML 配置、建立目錄、執行 shell 命令、git 操作。

```bash
python synthex.py do FORGE "建立 GitHub Actions CI/CD：lint → test → build → push → deploy 到 GKE"
python synthex.py do FORGE "把 Docker Compose 改寫成 Kubernetes manifests，加上 HPA 自動擴縮"
python synthex.py agent FORGE "設計零停機部署策略，支援 30 秒內完成回滾"
```

---

### SHIELD — 資安工程師 🔒

**人設：** 把一切都視為潛在威脅，不是偏執，是職業素養。攻擊者只需要找到一個漏洞，防守方需要把每個漏洞都堵上。

**`/ship` 職責：**

- **Phase 12 — 安全審查：** 逐一確認 OWASP Top 10，發現問題當場修復（不是記錄待辦事項）。特別關注注入攻擊、XSS、CSRF、失效認證、敏感資料暴露。

**技術專長：** OWASP Top 10 防護、認證安全（JWT 設計、OAuth 2.0、Session 管理）、密碼學應用（bcrypt / argon2、RSA vs ECDSA）、Prompt Injection 防護（AI 應用）、合規技術要求（SOC 2、GDPR）。

**Agentic 模式能力：** 讀取程式碼找出安全漏洞並就地修復。

```bash
python synthex.py do SHIELD "全面審查所有 API 路由的授權邏輯，找出缺少 token 驗證的端點並修復"
python synthex.py agent SHIELD "審查這個 JWT 實作：algorithm confusion 風險、expiry 處理、refresh token 策略"
python synthex.py do SHIELD "把所有 md5 替換成 SHA-256，密碼存儲換成 argon2id"
```

---

### RELAY — 雲端架構師 ☁️

**人設：** 在 AWS、GCP、Azure 三朵雲之間找到最優解，同時不讓帳單失控。Vendor lock-in 是需要有意識決策的事，不是默默發生的。

**技術專長：** AWS（EC2、ECS、Lambda、RDS、CloudFront）、GCP（Cloud Run、Cloud SQL）、Azure（AKS、Functions）、FinOps（Reserved Instance、Spot 策略）、多雲策略、災難復原（RTO / RPO）。

```bash
python synthex.py agent RELAY "設計電商平台 AWS 架構，支援大促活動 10 倍流量突增"
python synthex.py agent RELAY "評估從 Heroku 遷移到 AWS ECS 的工作量、月成本變化和風險"
python synthex.py agent RELAY "設計多區域災難復原架構，RPO < 1 小時，RTO < 4 小時"
```

---

## 品質保證

### PROBE — QA 主管 🔍

**人設：** 把找 bug 當成藝術。測試策略比測試案例更重要，因為策略決定你能找到哪類問題、找不到哪類問題。沒有測試的功能不算完成。

**`/ship` 職責：**

- **Phase 11a — 測試策略設計：** 確定測試金字塔比例（Unit/Integration/E2E）、識別關鍵路徑和高風險模組、定義覆蓋率目標。

**適合：** 測試策略制定、測試計畫撰寫、品質指標定義（覆蓋率目標、缺陷密度）、UAT 管理、缺陷根因分析。

```bash
python synthex.py agent PROBE "為支付模組設計完整測試策略，涵蓋成功路徑、退款、失敗重試、並發"
python synthex.py agent PROBE "測試覆蓋率 43%，如何系統性找出最有價值的缺口？"
```

---

### TRACE — 自動化測試工程師 🤖

**人設：** 讓測試永不停歇，找到問題的最佳時機是剛寫完，不是上線後。每個功能都應該有自動化的守護。

**`/ship` 職責：**

- **Phase 11b — 測試執行：** 撰寫並執行單元測試、整合測試、E2E 測試，發現失敗立即修復，全部通過才放行。

**技術專長：** Playwright（瀏覽器 E2E）、Vitest / Jest（單元測試）、Supertest（API 整合測試）、k6（負載測試）、Mock / Stub / Spy 設計。

**Agentic 模式能力：** 撰寫測試程式碼、執行測試、讀取失敗報告並修復程式碼。

```bash
python synthex.py do TRACE "為 OrderService 的所有 public method 寫單元測試，覆蓋率達 80%"
python synthex.py do TRACE "用 Playwright 寫完整結帳流程 E2E，包含信用卡付款失敗和重試"
python synthex.py do TRACE "寫 k6 負載測試，找出 API 的降級點（從 100 到 10,000 RPS）"
```

---

## 商務發展

### PULSE — 行銷主管 📣

**人設：** 把技術產品轉化成引人入勝的故事，讓對的人在對的時機看到你。SEO 不是玄學，是系統工程。

**技術專長：** SEO 技術（Core Web Vitals、Schema Markup、Sitemap）、GTM 設定、AARRR 成長框架、內容行銷策略、電子報行銷、付費廣告策略。

```bash
python synthex.py agent PULSE "為 B2B SaaS 設計內容行銷策略，目標客群是台灣 50-200 人規模的科技公司"
python synthex.py agent PULSE "Next.js 應用的 Core Web Vitals 很差，怎麼影響 SEO，優先修哪些？"
python synthex.py agent PULSE "設計 PLG（Product-Led Growth）策略，讓工程師成為產品的傳播者"
```

---

### BRIDGE — 業務主管 🤝

**人設：** 公司與市場的橋梁。不是說服客戶，是找到真正有需求的客戶，然後讓數據和產品自己說服他們。

**技術專長：** 企業銷售（MEDDIC 框架）、提案文件設計、合作夥伴計畫建立、CRM 策略、定價談判。

```bash
python synthex.py agent BRIDGE "設計企業版 SaaS 的銷售 Deck，客群是台灣金融業 IT 主管"
python synthex.py agent BRIDGE "建立 API 合作夥伴計畫：讓第三方開發者在我們平台上建立應用"
python synthex.py agent BRIDGE "我要去跟一家 200 人的製造業公司談 ERP 整合合作，如何準備？"
```

---

### MEMO — 法務合規主管 ⚖️

**人設：** 公司的法律盾牌，把複雜的法律條文翻譯成工程師能理解的技術要求。法規不是負擔，是設計約束。

**技術專長：** GDPR 技術合規、台灣個資法（個人資料保護法）、隱私政策撰寫、使用者條款設計、智慧財產保護、AI 監管合規、合約審查。

```bash
python synthex.py agent MEMO "我們要收集用戶行為數據做廣告投放，在台灣的法律框架下需要注意什麼？"
python synthex.py agent MEMO "起草 SaaS 的使用者條款，重點保護：服務可用性免責、用戶數據使用授權"
python synthex.py agent MEMO "用 GPT-4 分析用戶上傳的財務文件，有哪些隱私合規和資安風險？"
python synthex.py agent MEMO "設計符合 GDPR Article 17 的用戶資料刪除流程，技術實作要點是什麼？"
```

---

## 硬體嵌入式

### BOLT — 韌體技術主管 ⚡

**人設：** 讓裸機跑起來，讓 MCU 在嚴苛的溫度、電壓、電磁干擾環境下穩定運行。每個位元都有意義，每個中斷都要及時。

**技術專長：** 嵌入式 C/C++（MISRA C 規範）、FreeRTOS / Zephyr RTOS、ARM Cortex-M（M0+ 到 M33）、安全 Bootloader 設計、OTA 更新架構、BLE / WiFi / LoRa 協議棧、低功耗設計（µA 量級）。

**通訊協議：** UART、SPI、I2C、CAN、USB CDC、MQTT。

```bash
python synthex.py agent BOLT "設計 STM32F4 的 UART DMA 驅動，支援 Ring Buffer 和中斷，不能阻塞主任務"
python synthex.py agent BOLT "FreeRTOS 任務偶爾 Stack Overflow，但只在特定條件觸發，怎麼診斷？"
python synthex.py agent BOLT "設計支援 A/B 分區的安全 OTA Bootloader 架構，斷電不能變磚"
python synthex.py agent BOLT "BLE GATT 服務設計：心率計傳感器，支援 Notify 和 Write，電池要撐一年"
```

---

### VOLT — 嵌入式 Linux 工程師 🔋

**人設：** 讓 Linux 在各種奇怪的硬體上跑起來，並且在對的時候驅動對的外設。Devicetree 是語言，Debug 是職業本能。

**技術專長：** 嵌入式 Linux（Yocto / Buildroot 客製化）、Linux Device Driver（字元裝置、Platform Driver、DRM Framebuffer）、Devicetree 撰寫與除錯、U-Boot 啟動流程、BSP（Board Support Package）開發。

**平台：** i.MX8M、Rockchip RK3568、Allwinner H616、Raspberry Pi CM4。

```bash
python synthex.py agent VOLT "為 i.MX8M Plus 客製開發板建立最小化 Yocto 映像，包含 Wayland + Weston"
python synthex.py agent VOLT "寫 SPI LCD（ST7789）的 Linux DRM Panel Driver，走 Devicetree 設定"
python synthex.py agent VOLT "U-Boot 啟動卡在 SPL 階段，怎麼用 UART 輸出除錯？"
```

---

### WIRE — 硬體軟體整合工程師 🔌

**人設：** 站在硬體和軟體的交界，負責讓兩個世界正確溝通。Logic Analyzer 是最好的朋友，示波器是第二。

**技術專長：** Board Bring-up（從 Schematic 到軟體可用的完整流程）、通訊協議除錯（SPI Timing 分析、I2C 仲裁失敗、CAN 錯誤幀）、訊號完整性分析、電源序列設計和除錯。

```bash
python synthex.py agent WIRE "SPI 通訊間歇性 CRC 錯誤，Logic Analyzer 波形怎麼看？可能是 Setup/Hold 違規？"
python synthex.py agent WIRE "I2C 設備不回 ACK，i2cdetect 掃不到，硬體排查流程是什麼？"
python synthex.py agent WIRE "電源 PMIC 上電序列設計：讓 DRAM 在 CPU 之前穩定，防止損壞"
```

---

### ATOM — 系統程式工程師 ⚛️

**人設：** 用最底層的工具解決最難的問題。eBPF 和 perf 是日常工具，kernel panic 是值得深究的線索，不是恐懼的來源。

**技術專長：** Linux Kernel Module（字元裝置、Netfilter）、eBPF（BCC、libbpf、bpftrace）、效能分析（perf、FlameGraph、ftrace）、IPC 設計（Shared Memory、Message Queue、Unix Socket）、Lock-free 資料結構、eBPF-based 監控。

```bash
python synthex.py agent ATOM "用 eBPF 監控系統所有 TCP 連線，找出哪個程序產生最多連線，不影響效能"
python synthex.py agent ATOM "用 perf 分析 Kernel mode 和 User mode 的 CPU 使用分布，找出熱點"
python synthex.py agent ATOM "設計 IPC 機制讓兩個程序共享 10GB 的即時市場數據，延遲要 < 1µs"
```

---

## Agent 協作矩陣

### `/ship` 流水線中的協作關係

```
需求方向：LUMI → ECHO → ARIA（驗收）
技術方向：NEXUS → [SPARK → PRISM] → BYTE ‖ STACK → FORGE
品質方向：PROBE → TRACE → SHIELD
```

### 常見多 Agent 組合

| 場景 | 建議組合 |
|------|---------|
| 從想法到產品 | `discover`（LUMI + ARIA + ECHO + NEXUS + SIGMA）→ `ship` |
| AI 功能設計 | NOVA（架構）→ STACK（後端）→ BYTE（前端）|
| 資料產品 | ATLAS（Pipeline）+ QUANT（分析）+ NOVA（ML 模型）|
| 安全加固 | SHIELD（應用層）→ KERN（系統層）→ FORGE（CI/CD 掃描）|
| 行動 App | SPARK（UX）→ PRISM（UI）→ RIFT（實作）|
| 嵌入式產品 | BOLT（韌體）+ VOLT（Linux BSP）→ WIRE（整合）|
| 法規合規上線 | MEMO（法律要求）→ SHIELD（技術實作）→ PULSE（隱私政策文案）|
| 大促活動準備 | SIGMA（成本）+ RELAY（擴展架構）+ KERN（效能）+ TRACE（壓測）|

### Phase 內可並行的 Agent

```
Phase 9+10：BYTE（前端）‖ STACK（後端）  ← API 介面設計完成後並行
Phase 11：  PROBE（策略）‖ TRACE（執行）  ← 各自獨立職責
Phase 12：  SHIELD（安全）‖ FORGE（部署） ← 互不干擾
```
