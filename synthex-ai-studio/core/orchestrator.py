"""
SYNTHEX Orchestrator — ARIA 決策層，自動路由任務給正確的 Agent
支援：單一 Agent 任務 / 多 Agent 協作 / 智慧路由
"""

import os
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import anthropic
from agents.all_agents import ALL_AGENTS, DEPT_AGENTS, get_agent

RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
PURPLE = "\033[35m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
WHITE  = "\033[97m"


ROUTING_SYSTEM = """你是 SYNTHEX AI STUDIO 的任務路由系統。

根據用戶的任務，決定最合適的 Agent（或多個 Agent 的協作方案）。

可用的 Agent 和其專業：
- ARIA: CEO，策略規劃、公司決策、多部門協調
- NEXUS: CTO，技術架構、技術選型、工程團隊管理
- LUMI: CPO，產品策略、用戶研究、產品路線圖
- SIGMA: CFO，財務分析、預算規劃、ROI評估
- BYTE: 前端工程師，React/TypeScript、UI效能、Design System
- STACK: 後端工程師，API設計、資料庫、微服務架構
- FLUX: 全端工程師，快速原型、全棧功能、Docker
- KERN: 系統工程師，Linux系統、效能調優、並發問題
- RIFT: 行動端工程師，React Native、iOS/Android、行動效能
- SPARK: UX主管，用戶研究、可用性測試、資訊架構
- PRISM: UI設計師，視覺設計、Design Token、品牌設計
- ECHO: 商業分析師，需求分析、PRD撰寫、流程設計
- VISTA: 產品經理，Sprint規劃、Roadmap、功能優先排序
- NOVA: ML主管，深度學習、LLM微調、AI系統設計
- QUANT: 資料科學家，統計分析、預測模型、A/B測試
- ATLAS: 資料工程師，ETL管道、資料倉儲、Kafka
- FORGE: DevOps主管，K8s、CI/CD、基礎架構自動化
- SHIELD: 資安工程師，安全審計、滲透測試、合規
- RELAY: 雲端架構師，AWS/GCP/Azure、成本優化、多雲策略
- PROBE: QA主管，測試策略、品質指標、UAT管理
- TRACE: 自動化測試，Playwright、API測試、效能測試
- PULSE: 行銷主管，內容行銷、SEO、成長策略
- BRIDGE: 業務主管，企業銷售、合夥關係、提案撰寫
- MEMO: 法務合規，合約審查、隱私合規、IP策略

回應格式（只能回應 JSON，不要有其他文字）：
{
  "routing_type": "single" 或 "multi" 或 "sequential",
  "primary_agent": "AGENT_NAME",
  "supporting_agents": ["AGENT_NAME"],  // 協作時才有
  "reasoning": "路由理由（一句話）",
  "task_summary": "任務摘要（一句話，中文）",
  "suggested_approach": "建議的工作方式（一句話）"
}

routing_type 說明：
- single: 一個 Agent 獨立處理
- multi: 多個 Agent 同時各自處理，再整合結果
- sequential: 需要 A 先做，B 再做（有依賴順序）
"""


class Orchestrator:
    """ARIA 驅動的任務路由器和協調者"""

    def __init__(self, workdir: str = None, auto_confirm: bool = False):
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        self.workdir = workdir or os.getcwd()
        self.auto_confirm = auto_confirm
        self._agent_cache = {}

    def _get_cached_agent(self, name: str):
        if name not in self._agent_cache:
            self._agent_cache[name] = get_agent(name, workdir=self.workdir, auto_confirm=self.auto_confirm)
        return self._agent_cache[name]

    def route(self, task: str) -> dict:
        """讓 ARIA 決定哪個 Agent 處理這個任務"""
        self._print_routing(task)
        try:
            resp = self.client.messages.create(
                model="claude-opus-4-5",
                max_tokens=512,
                system=ROUTING_SYSTEM,
                messages=[{"role": "user", "content": task}],
            )
            raw = resp.content[0].text.strip()
            # strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        except Exception as e:
            # fallback to ARIA
            return {
                "routing_type": "single",
                "primary_agent": "ARIA",
                "supporting_agents": [],
                "reasoning": f"路由失敗，交由 ARIA 處理: {e}",
                "task_summary": task[:60],
                "suggested_approach": "直接處理",
            }

    def run(self, task: str, force_agent: str = None, show_routing: bool = True,
            agentic: bool = False, auto_confirm: bool = False) -> str:
        """主入口：自動路由並執行任務"""
        if force_agent:
            agent = self._get_cached_agent(force_agent.upper())
            return agent.run(task) if agentic else agent.chat(task)

        routing = self.route(task)

        if show_routing:
            self._print_routing_result(routing)

        rtype = routing.get("routing_type", "single")

        if rtype == "single":
            agent = self._get_cached_agent(routing["primary_agent"])
            return agent.run(task) if agentic else agent.chat(task)

        elif rtype == "multi":
            return self._run_multi(task, routing, agentic=agentic)

        elif rtype == "sequential":
            return self._run_sequential(task, routing, agentic=agentic)

        else:
            agent = self._get_cached_agent(routing["primary_agent"])
            return agent.chat(task)

    def _run_multi(self, task: str, routing: dict, agentic: bool = False) -> str:
        """多 Agent 並行處理，ARIA 整合結果"""
        all_agents = [routing["primary_agent"]] + routing.get("supporting_agents", [])
        results = {}

        print(f"\n{YELLOW}{BOLD}  ⟳ 多 Agent 協作模式 · {len(all_agents)} 位 Agent{RESET}")

        for agent_name in all_agents:
            agent = self._get_cached_agent(agent_name)
            result = agent.run(task) if agentic else agent.chat(task)
            results[agent_name] = result

        # ARIA synthesizes
        print(f"\n{PURPLE}{BOLD}  ⟳ ARIA 整合所有觀點...{RESET}")
        synthesis_prompt = f"""以下是各部門 Agent 對任務「{task}」的分析：

{chr(10).join(f'=== {k} 的觀點 ==={chr(10)}{v}' for k, v in results.items())}

請以 CEO 的視角整合以上觀點，提供：
1. 跨部門洞察和共識
2. 潛在的衝突或矛盾點
3. 最終的行動建議和優先順序"""

        aria = self._get_cached_agent("ARIA")
        return aria.chat(synthesis_prompt)

    def _run_sequential(self, task: str, routing: dict, agentic: bool = False) -> str:
        """串行協作：前一個 Agent 的輸出成為下一個的輸入"""
        all_agents = [routing["primary_agent"]] + routing.get("supporting_agents", [])

        print(f"\n{CYAN}{BOLD}  ⟳ 串行協作模式 · {' → '.join(all_agents)}{RESET}")

        context = ""
        last_result = ""

        for i, agent_name in enumerate(all_agents):
            agent = self._get_cached_agent(agent_name)
            if i == 0:
                last_result = agent.run(task) if agentic else agent.chat(task)
            else:
                enriched = f"前一位同事的分析：\n{last_result}\n\n請基於以上，從你的專業角度補充和深化：\n{task}"
                last_result = agent.run(enriched) if agentic else agent.chat(enriched)
            context += f"\n{agent_name}: {last_result[:200]}..."

        return last_result

    def project(self, project_brief: str) -> dict:
        """完整專案規劃：ARIA 協調所有相關部門"""
        print(f"\n{PURPLE}{BOLD}{'═'*60}")
        print(f"  🎯 SYNTHEX 專案啟動")
        print(f"{'═'*60}{RESET}")

        # Phase 1: NEXUS & LUMI 技術+產品分析
        print(f"\n{CYAN}Phase 1 · 技術與產品評估{RESET}")
        nexus = self._get_cached_agent("NEXUS")
        lumi  = self._get_cached_agent("LUMI")

        tech_analysis = nexus.chat(f"請分析此專案的技術可行性、架構建議和技術風險：\n\n{project_brief}")
        product_analysis = lumi.chat(f"請分析此專案的產品方向、用戶價值和PMF風險：\n\n{project_brief}")

        # Phase 2: SIGMA & FORGE 資源評估
        print(f"\n{CYAN}Phase 2 · 資源與基礎架構規劃{RESET}")
        sigma = self._get_cached_agent("SIGMA")
        forge = self._get_cached_agent("FORGE")

        financial_analysis = sigma.chat(f"請評估此專案的預算需求、ROI預測和財務風險：\n\n{project_brief}")
        infra_plan = forge.chat(f"請規劃此專案的基礎架構、CI/CD和部署策略：\n\n{project_brief}")

        # Phase 3: ARIA 整合輸出完整計畫
        print(f"\n{CYAN}Phase 3 · ARIA 整合專案計畫{RESET}")
        synthesis = f"""
以下是各部門對專案「{project_brief[:100]}...」的評估：

【CTO NEXUS 技術分析】
{tech_analysis[:800]}

【CPO LUMI 產品分析】
{product_analysis[:800]}

【CFO SIGMA 財務分析】
{financial_analysis[:800]}

【DevOps FORGE 基礎架構】
{infra_plan[:800]}

請作為 CEO 整合以上資訊，產出：
1. 專案可行性評估（Go/No-Go）
2. 3個月里程碑計畫
3. 需要招募或強化的 Agent 能力
4. 最大風險和緩解策略
5. 立即可執行的下一步（Next 3 actions）
"""
        aria = self._get_cached_agent("ARIA")
        final_plan = aria.chat(synthesis)

        return {
            "tech_analysis": tech_analysis,
            "product_analysis": product_analysis,
            "financial_analysis": financial_analysis,
            "infra_plan": infra_plan,
            "final_plan": final_plan,
        }

    # ─── Display Helpers ──────────────────────────────────────────────────────

    def _print_routing(self, task: str):
        print(f"\n{DIM}  🔀 分析任務並路由... · \"{task[:60]}{'...' if len(task)>60 else ''}\"{RESET}")

    def _print_routing_result(self, r: dict):
        print(f"\n{CYAN}{'─'*50}")
        print(f"  路由決策：{r.get('task_summary', '')}")
        print(f"  主責 Agent：{BOLD}{r.get('primary_agent', '?')}{RESET}{CYAN}")
        if r.get('supporting_agents'):
            print(f"  協作 Agent：{', '.join(r['supporting_agents'])}")
        print(f"  模式：{r.get('routing_type', '?')} · {r.get('reasoning', '')}")
        print(f"{'─'*50}{RESET}")

    def list_agents(self):
        """顯示所有可用 Agent"""
        dept_names = {
            "exec": "🎯 高層管理",
            "engineering": "⚙️  工程開發",
            "product": "💡 產品設計",
            "ai_data": "🧠 AI 與資料",
            "devops": "🚀 基礎架構",
            "qa": "🔍 品質安全",
            "biz": "📣 商務發展",
        }
        print(f"\n{BOLD}SYNTHEX AI STUDIO — 全體 Agent{RESET}\n")
        for dept, agents in DEPT_AGENTS.items():
            print(f"{CYAN}{dept_names.get(dept, dept)}{RESET}")
            for name in agents:
                cls = ALL_AGENTS[name]
                print(f"  {cls.emoji}  {BOLD}{name:<8}{RESET} {cls.title}")
            print()
