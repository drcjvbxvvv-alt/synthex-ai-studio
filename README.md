<div align="center">

```
  ███████╗██╗   ██╗███╗   ██╗████████╗██╗  ██╗███████╗██╗  ██╗
  ██╔════╝╚██╗ ██╔╝████╗  ██║╚══██╔══╝██║  ██║██╔════╝╚██╗██╔╝
  ███████╗ ╚████╔╝ ██╔██╗ ██║   ██║   ███████║█████╗   ╚███╔╝
  ╚════██║  ╚██╔╝  ██║╚██╗██║   ██║   ██╔══██║██╔══╝   ██╔██╗
  ███████║   ██║   ██║ ╚████║   ██║   ██║  ██║███████╗██╔╝ ██╗
  ╚══════╝   ╚═╝   ╚═╝  ╚═══╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
```

**Autonomous AI Development Studio**

28 specialized agents · 12-phase pipeline · Long-term memory across every session

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-197%20passed-22C55E?style=flat-square)](#)
[![Agents](https://img.shields.io/badge/Agents-28-7C3AED?style=flat-square)](#agents)
[![Memory Layers](https://img.shields.io/badge/Memory-L1%20%2F%20L2%20%2F%20L3-3B82F6?style=flat-square)](#project-brain)

[English](#overview) · [中文](#概述)

</div>

---

## Overview

SYNTHEX AI STUDIO coordinates 28 AI agents across 7 departments — mirroring the structure of a technology company — to carry out software development tasks end-to-end.

**Project Brain** is the embedded long-term memory layer. Every decision, pitfall, and architectural rule is captured and made available to any LLM tool: Cursor, Ollama, or your own code via an OpenAI-compatible API.

```bash
python synthex.py ship "Build a subscription billing system with Stripe"
```

```
Phase 1   Requirements analysis    NEXUS · ARIA
Phase 2   Security assessment      SHIELD · GUARDIAN
Phase 3   System architecture      NEXUS · ATLAS
Phase 4   Data layer               BYTE
Phase 5–8 Implementation           FORGE · CIRCUIT · BYTE  ← parallel
Phase 9   Test coverage            QA · GUARDIAN
Phase 10  Security hardening       SHIELD · ANCHOR
Phase 11  Documentation            SCRIBE
Phase 12  Deployment               INFRA · TITAN
```

---

## What's in this release

```
synthex-release/
├── synthex-ai-studio/     ← Install once, use across all projects
│   ├── synthex.py           SYNTHEX CLI entry point
│   ├── brain.py             Project Brain standalone CLI
│   ├── core/                Engine, agents, tools, memory system
│   └── tests/               197 tests
│
├── project-template/      ← Copy into each project you work on
│   ├── CLAUDE.md             AI operating rules for Claude Code
│   └── agents/               Role handbooks for all 28 agents
│
└── vscode-extension/      ← Optional editor integration
```

---

## Quick Start

```bash
cd synthex-ai-studio
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
```

```bash
# Full 12-phase pipeline
python synthex.py ship "Build a REST API for user authentication with JWT"

# Direct agent interaction
python synthex.py ask NEXUS "How should I structure a payment microservice?"
python synthex.py agent SHIELD "Security audit of auth.py"
```

**Set up project memory:**

```bash
python brain.py init --workdir /your/project
python brain.py scan                          # learn from git history
python brain.py context "implement payments"  # verify injection
python brain.py serve --port 7891             # OpenAI-compatible API
```

---

## Two Systems, One Workflow

|  | **SYNTHEX AI STUDIO** | **Project Brain** |
|--|--|--|
| Purpose | Execute development tasks | Persist knowledge across sessions |
| Trigger | On demand | On every commit, continuously |
| API key | Required | Optional (local LLMs supported) |
| LLM lock-in | No | No — works with any LLM |

They are fully independent. Use Project Brain with Cursor and never touch `synthex.py`.

---

## Agents

<details>
<summary><strong>Executive · Engineering · Product</strong></summary>

| Agent | Role |
|-------|------|
| **NEXUS** | Chief Architect |
| **ARIA** | Product Manager |
| **ATLAS** | CTO |
| **BYTE** | Backend / Database |
| **FORGE** | Core Implementation |
| **CIRCUIT** | Full-stack |
| **SPARK** | Performance |
| **FLUX** | API Design |
| **ECHO** | System Integration |
| **PIXEL** | UI Design |
| **UX** | User Experience |
| **SCRIBE** | Documentation |

</details>

<details>
<summary><strong>AI · Infrastructure · Security · QA · Business</strong></summary>

| Agent | Role |
|-------|------|
| **CIPHER** | AI/ML Integration |
| **LENS** | Data Engineering |
| **SAGE** | Data Science |
| **ORACLE** | Predictive Models |
| **INFRA** | DevOps / CI-CD |
| **TITAN** | SRE |
| **VOLT** | Scalability |
| **ANCHOR** | Infrastructure Security |
| **GUARDIAN** | Vulnerability Analysis |
| **SHIELD** | Security Testing (OWASP) |
| **QA** | Quality Engineering |
| **PRISM** | Compliance |
| **VANTAGE** | Business Analysis |
| **PULSE** | Market Analysis |
| **CORTEX** | Embedded Systems |
| **HERALD** | Technical Communication |

</details>

---

## Project Brain

A standalone AI memory system. No lock-in.

```
L1  Working memory    SQLite WAL · REST API · any LLM reads/writes
L2  Episodic memory   Graphiti + FalkorDB · bi-temporal knowledge graph
L3  Semantic memory   SQLite · FTS5 full-text search · decay engine
```

**Quality controls** (v5.1 → v7.0):

| Feature | Command |
|---------|---------|
| Pin critical rules (immune to decay) | `brain pin <id>` |
| Semantic deduplication | `brain dedup` |
| Causal chains (why a rule exists) | `brain add-causal` |
| Applicability & invalidation conditions | `brain meta <id>` |
| Human review before rules go live | `brain review` |

**Connect any LLM:**

```bash
python brain.py export-rules --target cursorrules    # Cursor
python brain.py export-rules --target claude          # Claude Code
python brain.py serve --port 7891                     # Ollama / any OpenAI client
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [synthex-ai-studio/README.md](synthex-ai-studio/README.md) | SYNTHEX commands and agent reference |
| [synthex-ai-studio/PROJECT_BRAIN.md](synthex-ai-studio/PROJECT_BRAIN.md) | Complete Project Brain documentation |
| [synthex-ai-studio/COMMANDS.md](synthex-ai-studio/COMMANDS.md) | Every command with examples |
| [synthex-ai-studio/AGENTS.md](synthex-ai-studio/AGENTS.md) | All 28 agents — capabilities and use cases |
| [synthex-ai-studio/docs/BRAIN_INTEGRATION.md](synthex-ai-studio/docs/BRAIN_INTEGRATION.md) | LLM integration guide + verification checklist |
| [synthex-ai-studio/docs/ARCHITECTURAL_REFLECTION.md](synthex-ai-studio/docs/ARCHITECTURAL_REFLECTION.md) | Design decisions · known limits · maturity tracking |
| [synthex-ai-studio/INSTALL.md](synthex-ai-studio/INSTALL.md) | Installation and deployment |
| [synthex-ai-studio/CHANGELOG.md](synthex-ai-studio/CHANGELOG.md) | Version history |

---

## License

MIT

---

---

<div align="center">

```
  ██████╗ ██████╗  █████╗ ██╗███╗   ██╗
  ██╔══██╗██╔══██╗██╔══██╗██║████╗  ██║
  ██████╔╝██████╔╝███████║██║██╔██╗ ██║
  ██╔══██╗██╔══██╗██╔══██║██║██║╚██╗██║
  ██████╔╝██║  ██║██║  ██║██║██║ ╚████║
  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝
```

**AI  M E M O R Y  S Y S T E M**

Long-term memory for every LLM · v5.0 · Works standalone

</div>

---

## 概述

SYNTHEX AI STUDIO 協調 28 個 AI Agent，跨越 7 個職能部門 — 結構與一家科技公司相同 — 端對端執行軟體開發任務。

**Project Brain** 是內建的長期記憶層。每一個決策、踩坑和架構規則都會被保留，並透過 OpenAI 相容 API 提供給任何 LLM 工具使用：Cursor、Ollama 或你自己的程式碼。

```bash
python synthex.py ship "建立支援 Stripe 的訂閱計費系統"
```

---

## 版本內容

```
synthex-release/
├── synthex-ai-studio/     ← 安裝一次，跨所有專案使用
│   ├── synthex.py           SYNTHEX CLI 入口
│   ├── brain.py             Project Brain 獨立 CLI
│   ├── core/                引擎、Agent、工具、記憶系統
│   └── tests/               197 個測試
│
├── project-template/      ← 複製到每個你工作的專案
│   ├── CLAUDE.md             Claude Code 的 AI 操作規則
│   └── agents/               28 個角色的技能手冊
│
└── vscode-extension/      ← 選填的編輯器整合
```

---

## 快速開始

```bash
cd synthex-ai-studio
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."
```

```bash
# 完整 12 Phase 流水線
python synthex.py ship "建立帶 JWT 的用戶認證 REST API"

# 直接和 Agent 互動
python synthex.py ask NEXUS "支付微服務應該怎麼設計？"
python synthex.py agent SHIELD "審查 auth.py 的安全性"
```

**設定專案記憶：**

```bash
python brain.py init --workdir /your/project
python brain.py scan                           # 從 git 歷史學習
python brain.py context "實作支付退款"         # 驗證知識注入
python brain.py serve --port 7891              # 啟動 OpenAI 相容 API
```

---

## 兩個系統，一個工作流程

|  | **SYNTHEX AI STUDIO** | **Project Brain** |
|--|--|--|
| 目的 | 執行開發任務 | 跨 session 持久化知識 |
| 觸發時機 | 手動，按需執行 | 每次 commit，持續運行 |
| 需要 API Key | 是 | 選填（支援本地 LLM）|
| LLM 鎖定 | 否 | 否 — 任何 LLM 皆可 |

兩者完全獨立。你可以只用 Project Brain 搭配 Cursor，從不執行 `synthex.py`。

---

## 28 個 Agent

<details>
<summary><strong>高層管理 · 工程開發 · 產品設計</strong></summary>

| Agent | 職責 |
|-------|------|
| **NEXUS** | 首席架構師 |
| **ARIA** | 產品經理 |
| **ATLAS** | CTO |
| **BYTE** | 後端 / 資料庫 |
| **FORGE** | 核心功能實作 |
| **CIRCUIT** | 全端工程 |
| **SPARK** | 效能優化 |
| **FLUX** | API 設計 |
| **ECHO** | 系統整合 |
| **PIXEL** | UI 設計 |
| **UX** | 使用者體驗 |
| **SCRIBE** | 技術文件 |

</details>

<details>
<summary><strong>AI · 基礎設施 · 安全 · 品質保證 · 商務</strong></summary>

| Agent | 職責 |
|-------|------|
| **CIPHER** | AI/ML 整合 |
| **LENS** | 資料工程 |
| **SAGE** | 資料科學 |
| **ORACLE** | 預測模型 |
| **INFRA** | DevOps / CI-CD |
| **TITAN** | SRE |
| **VOLT** | 可擴展性 |
| **ANCHOR** | 基礎設施安全 |
| **GUARDIAN** | 漏洞分析 |
| **SHIELD** | 安全測試（OWASP）|
| **QA** | 品質工程 |
| **PRISM** | 合規審查 |
| **VANTAGE** | 商業分析 |
| **PULSE** | 市場分析 |
| **CORTEX** | 嵌入式系統 |
| **HERALD** | 技術傳播 |

</details>

---

## Project Brain 記憶系統

獨立的 AI 記憶系統，無 LLM 鎖定。

```
L1  工作記憶    SQLite WAL · REST API · 任何 LLM 可讀寫
L2  時序記憶    Graphiti + FalkorDB · 雙時態知識圖
L3  語義記憶    SQLite · FTS5 全文搜尋 · 衰減引擎
```

**知識品質機制**（v5.1 → v7.0）：

| 功能 | 命令 |
|------|------|
| 釘選關鍵規則（免疫衰減）| `brain pin <id>` |
| 語意去重 | `brain dedup` |
| 因果鏈（記錄規則存在的原因）| `brain add-causal` |
| 適用條件與失效條件 | `brain meta <id>` |
| 人工審查後才進入知識庫 | `brain review` |

**接入任何 LLM：**

```bash
python brain.py export-rules --target cursorrules    # Cursor
python brain.py export-rules --target claude          # Claude Code
python brain.py serve --port 7891                     # Ollama / 任何 OpenAI 客戶端
```

---

## 文件索引

| 文件 | 說明 |
|------|------|
| [synthex-ai-studio/README.md](synthex-ai-studio/README.md) | SYNTHEX 命令與 Agent 參考 |
| [synthex-ai-studio/PROJECT_BRAIN.md](synthex-ai-studio/PROJECT_BRAIN.md) | Project Brain 完整文件 |
| [synthex-ai-studio/COMMANDS.md](synthex-ai-studio/COMMANDS.md) | 所有命令完整範例 |
| [synthex-ai-studio/docs/BRAIN_INTEGRATION.md](synthex-ai-studio/docs/BRAIN_INTEGRATION.md) | LLM 整合指南 + 驗證清單 |
| [synthex-ai-studio/docs/ARCHITECTURAL_REFLECTION.md](synthex-ai-studio/docs/ARCHITECTURAL_REFLECTION.md) | 架構決策 · 缺陷分析 · 成熟度追蹤 |
| [synthex-ai-studio/CHANGELOG.md](synthex-ai-studio/CHANGELOG.md) | 版本歷史 |

---

## 授權

MIT

---

<div align="center">
<sub>SYNTHEX AI STUDIO · Project Brain · v5.0</sub>
</div>
