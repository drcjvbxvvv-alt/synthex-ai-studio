# SYNTHEX AI STUDIO

**28 個 AI Agent 組成的自主開發公司。** 從一句需求出發，自動完成 PRD → 架構設計 → 安全審查 → 程式碼實作 → 測試 → 部署的完整開發流程。

> Version: v0.0.0 · Tests: 102/102 · Python 3.11+

---

## 快速開始

```bash
git clone https://github.com/your-org/synthex-ai-studio
cd synthex-ai-studio
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-..."
python synthex.py list
```

---

## 架構

```
synthex.py
├── core/
│   ├── config.py           集中模型管理（ModelID 常數、成本計算）
│   ├── base_agent.py       Agent 基底（CompactionManager / CircuitBreaker / TokenBudget）
│   ├── orchestrator.py     智慧路由（複雜度感知 low/medium/high → Haiku/Sonnet/Opus）
│   ├── swarm.py            DAG 並行調度（Kahn 算法 + asyncio.to_thread）
│   ├── web_orchestrator.py /ship 12-Phase 流水線
│   ├── tools.py            工具箱（檔案 / 命令 / git / 測試）
│   ├── evals.py            品質評估框架
│   ├── mcp_server.py       MCP Server（Claude Code 整合）
│   └── observability.py    OpenTelemetry 追蹤
├── agents/all_agents.py    28 個 Agent 定義
└── evals/suites/           Golden Dataset（JSON）
```

### 模型分層策略

| Tier | 模型 | 適用 Agent | 特性 |
|------|------|-----------|------|
| Opus 4.6 | `claude-opus-4-6` | NEXUS / SIGMA / ARIA / NOVA / ATOM | Extended Thinking、1M context、14.5h 任務 |
| Sonnet 4.6 | `claude-sonnet-4-6` | BYTE / STACK / FLUX / ECHO 等 | 均衡效能、1M context |
| Haiku 4.5 | `claude-haiku-4-5` | RELAY / PROBE / BRIDGE 等 | 快速低成本、高頻任務 |

所有模型字串集中在 `core/config.py` 的 `ModelID` 常數，遷移時一處更改全部生效。

---

## 命令

### 基礎對話與任務

```bash
# 智慧路由 — 自動選擇最適 Agent
python synthex.py ask "設計一個支援 10 萬 QPS 的 API Gateway"

# 指定 Agent 對話
python synthex.py agent NEXUS "評估 gRPC vs REST"

# Agentic 模式（Agent 自主操作檔案系統）
python synthex.py do BYTE "重構 Button.tsx，補上 TypeScript 型別"

# 互動對話
python synthex.py chat STACK
```

### 全自動開發流水線

```bash
# 12-Phase 全自動（PRD → 程式碼 → 測試 → 部署文件）
python synthex.py ship "實作用戶登入，支援 JWT + refresh token"

# 進階選項
python synthex.py ship "加入支付模組" \
  --workdir /path/to/project \
  --budget 5.0 \
  --yes                    # 跳過確認（CI 用）
```

**12 個 Phase：**

| Phase | Agent | 產出 |
|-------|-------|------|
| 1 | ARIA | 任務確認 |
| 2 | ECHO | PRD（用戶故事、AC、NFR）|
| 3 | NEXUS | 技術架構 |
| 4 | SHIELD | 安全審查（OWASP Top 10）|
| 5 | SIGMA | 可行性評估 |
| 6 | LUMI | UX 流程 |
| 7 | BYTE + STACK | 前後端實作 |
| 8 | FLUX | 整合 + Docker |
| 9 | PROBE + TRACE | 測試策略 + 自動化測試 |
| 10 | FORGE | CI/CD Pipeline |
| 11 | RELAY | 部署文件 |
| 12 | ARIA | 最終審查 |

### 多 Agent 協作

```bash
python synthex.py discover "我們要做一個 B2B SaaS"
python synthex.py feature "實作 WebSocket 即時通知" --workdir .
python synthex.py fixbug "登入後 redirect 偶爾失敗"
python synthex.py codereview --workdir .
python synthex.py dept engineering "審查目前 API 設計"
```

### 其他

```bash
python synthex.py init     --workdir /path/to/project
python synthex.py list
python synthex.py workdir  /path/to/project
python synthex.py clear    BYTE
```

---

## Agent 體系

28 個 Agent，7 個部門。詳細技能與使用範例見 [AGENTS.md](AGENTS.md)。

| 部門 | Agent |
|------|-------|
| 🎯 高層管理 | ARIA（CEO）、NEXUS（CTO）、LUMI（CPO）、SIGMA（CFO）|
| ⚙️ 工程開發 | BYTE、STACK、FLUX、KERN、RIFT |
| 💡 產品設計 | SPARK、PRISM、ECHO、VISTA |
| 🧠 AI 與資料 | NOVA、QUANT、ATLAS |
| 🚀 基礎架構 | FORGE、SHIELD、RELAY |
| 🔍 品質安全 | PROBE、TRACE |
| 📣 商務發展 | PULSE、BRIDGE、MEMO |

---

## MCP 整合（Claude Code）

```bash
python -m core.mcp_server --info   # 顯示設定說明
python -m core.mcp_server          # 啟動 stdio server
```

**`~/.claude/claude_desktop_config.json`：**

```json
{
  "mcpServers": {
    "synthex": {
      "command": "python",
      "args": ["-m", "core.mcp_server"],
      "cwd": "/path/to/synthex-ai-studio",
      "env": { "ANTHROPIC_API_KEY": "sk-..." }
    }
  }
}
```

可用 MCP 工具：`synthex_ask` / `synthex_agent` / `synthex_list_agents` / `synthex_ship`

---

## Evals 品質框架

```bash
python -m core.evals run --agent ECHO --suite prd_quality
python -m core.evals compare --baseline v0.0.0 --current HEAD
python -m core.evals report
```

內建 4 個套件，9 個 Golden Dataset 測試案例（`prd_quality` / `architecture_quality` / `security_quality` / `code_quality`）。

---

## 安全設計

| 面向 | 實作 |
|------|------|
| 命令注入 | `_safe_run()` argv 陣列，禁止 `shell=True` |
| 路徑遍歷 | 所有操作限制在 workdir 沙箱 |
| SSRF | URL 驗證 + 私有地址過濾 |
| 原子寫入 | `tempfile + os.replace()`，防中斷損毀 |
| 記憶體洩漏 | `_trim_history()` 硬限制 40 筆對話歷史 |
| 預算控制 | `TokenBudget` + `CircuitBreaker`，防失控燒錢 |
| API Key | 僅從環境變數讀取，絕不寫入任何檔案 |

完整安全政策見 [SECURITY.md](SECURITY.md)。

---

## 開發貢獻

```bash
pip install -r requirements.txt
python -m pytest tests/ -q      # 102 個測試，應全部通過
```

**新增 Agent：**
1. 在 `agents/all_agents.py` 繼承 `BaseAgent`，設定 `name / title / dept / emoji / skills / system_prompt`
2. 登記到 `ALL_AGENTS` 和 `DEPT_AGENTS` 字典
3. 在 `core/config.py` 的 `AGENT_TIER_MAP` 分配模型 Tier

**Beta Header 管理：** 功能 GA 後，將 `core/base_agent.py` 的對應常數設為 `None`：
```python
BETA_INTERLEAVED_THINKING = None  # GA 後設 None
BETA_CONTEXT_MANAGEMENT   = None  # GA 後設 None
```

---

## 版本歷史

見 [CHANGELOG.md](CHANGELOG.md)。

---

*SYNTHEX AI STUDIO v0.0.0*
