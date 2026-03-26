"""
Web Orchestrator v3 — 完整重構版
P0 修復：文件傳遞取代截斷字串
P1 修復：Phase 斷點續跑 + 結果快取
P1 修復：負載測試整合
P2 修復：ADR 機制 + 契約測試觸發
"""

import os
import json
from pathlib import Path
from datetime import datetime
import anthropic

RESET  = "\033[0m"; BOLD = "\033[1m"; DIM = "\033[2m"
PURPLE = "\033[35m"; CYAN = "\033[96m"; GREEN = "\033[92m"
YELLOW = "\033[93m"; RED = "\033[91m"; BLUE = "\033[34m"

PHASE_COLORS = [PURPLE, BLUE, CYAN, GREEN, YELLOW]


def _phase(n: int, title: str):
    c = PHASE_COLORS[n % len(PHASE_COLORS)]
    print(f"\n{c}{BOLD}{'═'*62}\n  Phase {n} · {title}\n{'═'*62}{RESET}")

def _step(msg: str):  print(f"\n{CYAN}  ▶ {msg}{RESET}")
def _ok(msg: str):    print(f"  {GREEN}✔ {msg}{RESET}")
def _warn(msg: str):  print(f"  {YELLOW}⚠ {msg}{RESET}")


# ══════════════════════════════════════════════════════════════
#  P0-1 修復：文件上下文管理器
#  所有 Phase 的輸出都寫入磁碟，後續 Phase 從磁碟讀取完整內容
#  不再截斷字串傳遞
# ══════════════════════════════════════════════════════════════

class DocContext:
    """
    文件式上下文管理：把每個 Phase 的輸出存成 Markdown 檔案，
    後續 Phase 直接讀完整檔案，不截斷。

    解決問題：
      舊版 prd[:2000] → NEXUS 只看到 PRD 的 30%
      新版 read_doc("PRD") → NEXUS 看到完整 PRD
    """

    def __init__(self, workdir: str):
        self.docs = Path(workdir) / "docs"
        self.docs.mkdir(exist_ok=True)

    def write(self, name: str, content: str, label: str = "") -> Path:
        """
        原子寫入（P0-3 修復）：
        使用 tempfile + os.replace() 確保寫入過程中崩潰不會產生損壞文件。
        write_text() 直接覆寫時，若中途崩潰會留下空白或截斷的文件。
        """
        import tempfile, os as _os
        path   = self.docs / f"{name}.md"
        header = f"# {label or name}\n\n生成時間：{datetime.now().isoformat()}\n\n"
        full   = header + content
        # 原子寫入：先寫 tmp，成功後 rename（同目錄，rename 是原子操作）
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{name}_tmp_",
            suffix=".md",
            dir=str(self.docs),
        )
        try:
            with _os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(full)
            _os.replace(tmp_path, str(path))   # 原子性替換
        except Exception:
            try: _os.unlink(tmp_path)
            except Exception: pass
            raise
        _ok(f"{name}.md 已儲存（{len(content)} 字）")
        return path

    def read(self, name: str) -> str:
        path = self.docs / f"{name}.md"
        if not path.exists():
            return f"[{name}.md 尚未生成]"
        return path.read_text(encoding="utf-8")

    def exists(self, name: str) -> bool:
        return (self.docs / f"{name}.md").exists()

    def read_section(self, name: str, max_chars: int = None) -> str:
        """讀取文件，可選限制大小（僅用於顯示摘要，不用於 Phase 輸入）"""
        content = self.read(name)
        if max_chars and len(content) > max_chars:
            return content[:max_chars] + f"\n\n[... 完整內容見 docs/{name}.md]"
        return content

    def read_summary(self, name: str) -> str:
        """
        P2-1：摘要快取 — 讀取文件的摘要版本。
        首次讀取時產生摘要並快取，後續直接從快取讀取。
        用於「需要了解但不需要完整細節」的 Phase，節省 Token。

        完整文件適合：主要使用者（ECHO→PRD，NEXUS→架構）
        摘要版本適合：參考用途（TRACE 需要知道 PRD 的 AC，但不需要全部）
        """
        summary_path = self.docs / f"{name}_SUMMARY.md"
        if summary_path.exists():
            return summary_path.read_text(encoding="utf-8")

        # 摘要不存在時，用前 800 字 + 結構性提取
        full = self.read(name)
        if len(full) <= 1000:
            return full  # 短文件直接返回

        # 提取重要段落（標題 + 前幾行）
        lines = full.split("\n")
        summary_lines = []
        for line in lines:
            # 保留標題行
            if line.startswith("#") or line.startswith("- ") or line.startswith("□"):
                summary_lines.append(line)
            if len("\n".join(summary_lines)) > 1200:
                break

        summary = f"# {name} 摘要（完整版：docs/{name}.md）\n\n" + "\n".join(summary_lines)
        summary_path.write_text(summary, encoding="utf-8")
        return summary


# ══════════════════════════════════════════════════════════════
#  P0-2：Self-Critique Loop（自我評估品質閉環）
#  讓關鍵 Phase 的輸出在進入下一步前先通過品質評估
# ══════════════════════════════════════════════════════════════

class SelfCritique:
    """
    自我評估迴圈：
    1. 主要 Agent 完成輸出
    2. 評估 Agent 以「挑剔的評審」角色審查輸出
    3. 如果評分不夠，主要 Agent 根據反饋改進
    4. 最多迭代 MAX_CRITIQUE_ROUNDS 次

    適用場景：PRD、技術架構、安全審查等關鍵 Phase
    """

    MAX_ROUNDS = 2   # 最多改 2 輪，避免無限循環

    # 各 Phase 的評估者和標準
    CRITIQUE_CONFIG = {
        "PRD": {
            "reviewer":  "LUMI",
            "criteria":  """評估這份 PRD 的品質（1-10 分）：
1. AC 的具體性（每個 P0 功能是否有 GIVEN-WHEN-THEN 格式的 AC）
2. 邊界條件覆蓋（空狀態、錯誤狀態、並發是否考慮到）
3. 範疇清晰度（不在範疇的功能是否明確列出）
4. 用戶故事品質（是否有真實的用戶價值而非技術描述）

輸出格式：
SCORE: [1-10]
PASS: [true/false]  （分數 >= 7 才通過）
ISSUES:
- [具體問題]
IMPROVEMENTS:
- [具體改進建議]""",
            "pass_threshold": 7,
        },
        "ARCHITECTURE": {
            "reviewer":  "NEXUS",
            "criteria":  """評估這份技術架構的品質（1-10 分）：
1. 分層清晰度（路由層/Service層/Repository層是否分離）
2. API 版本化（是否包含 /api/v1/ 結構）
3. 資料庫設計（Schema 是否有主鍵、時間戳、Index 考量）
4. 風險覆蓋（技術風險是否有緩解方案）
5. ADR 完整性（重要決策是否有對應的 ADR）

輸出格式：
SCORE: [1-10]
PASS: [true/false]  （分數 >= 7 才通過）
ISSUES:
- [具體問題]
IMPROVEMENTS:
- [具體改進建議]""",
            "pass_threshold": 7,
        },
        "SECURITY": {
            "reviewer":  "SHIELD",
            "criteria":  """評估這份安全審查的完整性（1-10 分）：
1. 輸入驗證覆蓋（所有 API 端點是否確認有驗證）
2. 越權存取測試（是否確認了資源擁有者檢查）
3. 敏感資料保護（密碼雜湊、回應過濾是否確認）
4. 依賴漏洞（npm audit 是否執行）
5. Secret 掃描（gitleaks 是否執行）

輸出格式：
SCORE: [1-10]
PASS: [true/false]  （分數 >= 8 才通過）
ISSUES:
- [具體問題]
IMPROVEMENTS:
- [具體改進建議]""",
            "pass_threshold": 8,
        },
    }

    def __init__(self, orchestrator):
        self.orc = orchestrator

    def evaluate(self, doc_name: str, content: str) -> dict:
        """
        對指定文件執行自我評估。
        回傳 {"passed": bool, "score": int, "feedback": str}
        """
        config = self.CRITIQUE_CONFIG.get(doc_name)
        if not config:
            return {"passed": True, "score": 10, "feedback": "（無評估設定，直接通過）"}

        reviewer   = config["reviewer"]
        criteria   = config["criteria"]
        threshold  = config["pass_threshold"]

        print(f"\n  {CYAN}🔍 Self-Critique：{reviewer} 評審 {doc_name}...{RESET}")

        feedback = self.orc._chat(reviewer, f"""
你正在進行程式碼審查角色扮演：以嚴格的技術評審者身份評估以下文件。

待評估文件（{doc_name}）：
{content}

評估標準：
{criteria}

請直接輸出評分結果（嚴格按照格式，不要加其他說明）。
""")

        # 解析評分
        import re
        score_match = re.search(r'SCORE:\s*(\d+)', feedback)
        pass_match  = re.search(r'PASS:\s*(true|false)', feedback, re.IGNORECASE)
        score = int(score_match.group(1)) if score_match else 5
        passed = score >= threshold

        color = GREEN if passed else YELLOW
        print(f"  {color}評分：{score}/10  {'✅ 通過' if passed else '⚠ 需改善'}{RESET}")

        return {"passed": passed, "score": score, "feedback": feedback}

    def critique_loop(self, doc_name: str, ctx: 'DocContext',
                      generate_fn, improve_prompt_fn) -> str:
        """
        執行評估→改善迴圈。

        generate_fn():      產生初始內容的函數
        improve_prompt_fn(feedback): 根據反饋產生改善 prompt 的函數
        回傳最終通過評估的內容
        """
        content = generate_fn()
        ctx.write(doc_name, content, doc_name)

        for round_n in range(self.MAX_ROUNDS):
            result = self.evaluate(doc_name, content)
            if result["passed"]:
                if round_n > 0:
                    _ok(f"{doc_name} 在第 {round_n+1} 輪通過評估（分數：{result['score']}/10）")
                break

            _warn(f"{doc_name} 評分 {result['score']}/10，第 {round_n+1} 輪改善中...")
            improve_prompt = improve_prompt_fn(result["feedback"])
            content = generate_fn() if not improve_prompt else                       self.orc._chat(
                          self.CRITIQUE_CONFIG[doc_name].get("main_agent", "ECHO"),
                          improve_prompt
                      )
            ctx.write(doc_name, content, f"{doc_name}（改善版 {round_n+1}）")
        else:
            _warn(f"{doc_name} 達到最大改善輪數，以目前版本繼續")

        return content


# ══════════════════════════════════════════════════════════════
#  P1-2：Human-in-the-Loop（危險操作確認）
# ══════════════════════════════════════════════════════════════

class HumanGate:
    """
    在關鍵決策點暫停並等待人工確認。
    設計原則：不可逆的操作（刪除、部署、大量覆寫）必須經過人工確認。

    適用場景：
    - Phase 5（SIGMA）評估結論為「❌ 建議重新評估」時
    - 部署到生產環境前
    - 安全審查發現高風險問題時
    """

    def __init__(self, auto_confirm: bool = False):
        self.auto_confirm = auto_confirm

    def ask(self, question: str, context: str = "",
            options: list = None, default: str = "n") -> str:
        """
        暫停流程，等待用戶決定。
        auto_confirm=True 時自動選擇 default（適用於 CI/CD）。
        """
        if self.auto_confirm:
            print(f"\n{CYAN}  🤖 自動確認（auto_confirm=True）：{default}{RESET}")
            return default

        if context:
            print(f"\n{DIM}{context}{RESET}")

        print(f"\n{YELLOW}{BOLD}  ⚠ 需要人工確認{RESET}")
        print(f"  {question}")

        if options:
            for i, opt in enumerate(options, 1):
                print(f"  [{i}] {opt}")
            prompt = f"  選擇 (1-{len(options)})，預設 [{default}]: "
        else:
            prompt = f"  輸入 (y/n)，預設 [{default}]: "

        try:
            ans = input(prompt).strip().lower() or default
        except (KeyboardInterrupt, EOFError):
            ans = default

        return ans

    def confirm_phase_output(self, phase_name: str, summary: str) -> bool:
        """
        在關鍵 Phase 完成後，讓用戶確認輸出是否符合預期。
        如果用戶拒絕，可以重新執行或修改後繼續。
        """
        print(f"\n{CYAN}── Phase {phase_name} 完成 ─────────────────────────{RESET}")
        print(summary[:500])

        ans = self.ask(
            f"Phase {phase_name} 的輸出是否符合預期？",
            options=["繼續下一個 Phase", "重新執行此 Phase", "中止流水線"],
            default="1",
        )

        if ans == "1" or ans == "y":
            return True
        elif ans == "2":
            print(f"{YELLOW}  重新執行 Phase {phase_name}...{RESET}")
            return False
        else:
            print(f"{RED}  流水線已中止。{RESET}")
            raise KeyboardInterrupt("用戶中止流水線")


# ══════════════════════════════════════════════════════════════
#  P1-3：Generator-Critic 品質守門（ARIA 評審每個 Phase）
#  比 Self-Critique 更嚴格：ARIA 作為全局品質守門人
# ══════════════════════════════════════════════════════════════

class GeneratorCritic:
    """
    Generator-Critic 模式：
    - Generator：執行任務的 Agent（ECHO、NEXUS、BYTE 等）
    - Critic：ARIA 作為全局品質守門人

    每個 Phase 完成後，ARIA 評審輸出品質。
    評審維度：完整性、一致性、可執行性、風險覆蓋。

    和 SelfCritique 的差別：
    - SelfCritique：同部門的角色互評（LUMI 評審 ECHO 的 PRD）
    - GeneratorCritic：ARIA 評審所有 Phase（更高層次的一致性確認）
    """

    QUALITY_GATE = {
        # Phase → (最低分數, 評審重點)
        "PRD":          (7,  "功能完整性、AC 可測試性、範疇清晰度"),
        "ARCHITECTURE": (7,  "技術合理性、擴充性設計、風險考量"),
        "UX":           (6,  "用戶旅程完整性、邊界狀態"),
        "UI_SYSTEM":    (6,  "設計一致性、token 完整性"),
        "FRONTEND_IMPL":(7,  "程式碼完整性、型別安全、無 TODO"),
        "BACKEND_IMPL": (7,  "API 完整性、錯誤處理、安全性"),
        "TEST_RESULTS": (8,  "測試覆蓋率、E2E 流程"),
        "SECURITY":     (9,  "高風險問題是否修復"),
    }

    def __init__(self, orchestrator, enabled: bool = True):
        self.orc     = orchestrator
        self.enabled = enabled
        self._scores: dict = {}

    def gate(self, doc_name: str, ctx: 'DocContext') -> bool:
        """
        評審文件品質，低於閾值回傳 False（可選擇重做）。
        記錄所有 Phase 的品質分數。
        """
        if not self.enabled:
            return True

        config = self.QUALITY_GATE.get(doc_name)
        if not config:
            return True

        threshold, focus = config
        content = ctx.read(doc_name)
        if len(content) < 100:
            return True  # 文件太短，跳過評審

        print(f"\n{PURPLE}🎯 Generator-Critic：ARIA 評審 {doc_name}...{RESET}")

        # P1-2：Structured Output — 強制 JSON 格式，取代脆弱的 regex
        review = self.orc._chat("ARIA", f"""
以「全局品質守門人」角色評審以下 {doc_name} 文件。

評審重點：{focus}

文件內容：
{content[:3000]}

評分標準（1-10）：
- 9-10：卓越，超出預期
- 7-8：良好，符合標準
- 5-6：基本可用，有改善空間
- 1-4：不足，需要重做

輸出純 JSON（不加程式碼塊，不加說明）：
{{"score": <1-10整數>, "gate": "<PASS|FAIL>", "summary": "<一句評語>", "top_issue": "<最重要問題或null>"}}

PASS 條件：score >= {threshold}
""")

        import re, json as _json

        # P2-2：多層次解析策略（Structured Output → 正規表達式 → 關鍵字）
        score   = 5
        passed  = False
        summary = ""
        issue   = ""

        # 策略 1：嘗試解析 JSON 格式
        try:
            json_match = re.search(r'\{[^{}]+\}', review, re.DOTALL)
            if json_match:
                parsed = _json.loads(json_match.group())
                score   = int(parsed.get("score", parsed.get("SCORE", 5)))
                gate_val = str(parsed.get("gate", parsed.get("GATE", ""))).upper()
                passed  = gate_val == "PASS" or score >= threshold
                summary = parsed.get("summary", parsed.get("SUMMARY", ""))
                issue   = parsed.get("top_issue", parsed.get("TOP_ISSUE", ""))
        except Exception:
            pass

        # 策略 2：正規表達式（如果 JSON 解析失敗）
        if not summary:
            score_m  = re.search(r'SCORE[:\s]+([1-9]|10)', review, re.IGNORECASE)
            gate_m   = re.search(r'GATE[:\s]+(PASS|FAIL)', review, re.IGNORECASE)
            sum_m    = re.search(r'SUMMARY[:\s]+(.+?)(?:\n|$)', review, re.IGNORECASE)
            issue_m  = re.search(r'TOP_ISSUE[:\s]+(.+?)(?:\n|$)', review, re.IGNORECASE)
            score    = int(score_m.group(1)) if score_m else 5
            passed   = (gate_m.group(1).upper() == "PASS") if gate_m else score >= threshold
            summary  = sum_m.group(1).strip() if sum_m else ""
            issue    = issue_m.group(1).strip() if issue_m else ""

        # 策略 3：關鍵字偵測（最後手段）
        if not summary:
            if any(w in review.lower() for w in ["通過", "pass", "良好", "符合"]):
                passed, score = True, max(score, threshold)
                summary = "自動偵測：通過"
            elif any(w in review.lower() for w in ["失敗", "fail", "問題", "缺少"]):
                passed, score = False, min(score, threshold - 1)
                summary = "自動偵測：需改善"

        self._scores[doc_name] = score
        color = GREEN if passed else YELLOW
        print(f"  {color}ARIA 評分：{score}/10  {'✅ PASS' if passed else '⚠ FAIL'}  {summary}{RESET}")
        if issue and issue != "無":
            print(f"  {DIM}主要問題：{issue}{RESET}")

        return passed

    def quality_report(self) -> str:
        """產出所有 Phase 的品質摘要"""
        if not self._scores:
            return ""
        lines = [f"\n{CYAN}{'─'*50}"]
        lines.append("  📊 Generator-Critic 品質報告")
        lines.append("─" * 50 + RESET)
        total = sum(self._scores.values())
        count = len(self._scores)
        for doc, score in self._scores.items():
            color = GREEN if score >= 7 else (YELLOW if score >= 5 else RED)
            lines.append(f"  {doc:<20} {color}{score}/10{RESET}")
        lines.append(f"  {'平均分':<20} {total/count:.1f}/10")
        return "\n".join(lines)



# ══════════════════════════════════════════════════════════════
#  P1-4：Dynamic Orchestrator（智能路由，不是固定 12 Phase）
#  ARIA 根據需求類型決定需要哪些 Phase
# ══════════════════════════════════════════════════════════════

class DynamicOrchestrator:
    """
    根據需求類型動態決定執行哪些 Phase。

    需求類型判斷：
    - 全新產品 → 完整 12 Phase
    - 功能新增 → 跳過 Phase 1-3，從 Phase 4 開始
    - Bug 修復 → 直接到 Phase 9+12
    - 設計更新 → Phase 7+8，再到 Phase 9
    - API 更新  → Phase 4+10+11+12

    這讓 /ship 不再是死板的流水線，而是根據需求智能選擇路徑。
    """

    PHASE_CATALOG = {
        1:  ("ARIA",         "任務確認與範疇"),
        2:  ("ECHO",         "需求分析與 PRD"),
        3:  ("LUMI",         "產品驗證"),
        4:  ("NEXUS",        "技術架構設計"),
        5:  ("SIGMA",        "可行性評估"),
        6:  ("FORGE",        "環境準備"),
        7:  ("SPARK",        "UX 設計"),
        8:  ("PRISM",        "UI 設計系統"),
        9:  ("BYTE",         "前端實作"),
        10: ("STACK",        "後端實作"),
        11: ("PROBE+TRACE",  "測試"),
        12: ("SHIELD",       "安全審查"),
    }

    SCENARIOS = {
        "full_product":    list(range(1, 13)),         # 全新產品
        "new_feature":     [1, 2, 4, 6, 7, 8, 9, 10, 11, 12],  # 新功能
        "api_only":        [1, 2, 4, 6, 10, 11, 12],  # 純後端 API
        "frontend_only":   [1, 7, 8, 9, 11],          # 純前端更新
        "bug_fix":         [1, 9, 10, 11, 12],         # Bug 修復
        "design_update":   [7, 8, 9, 11],              # 設計更新
        "security_patch":  [12],                       # 安全修補
    }

    def __init__(self, orchestrator):
        self.orc = orchestrator

    def classify_requirement(self, requirement: str) -> str:
        """讓 ARIA 分析需求，決定最適合的執行路徑"""
        result = self.orc._chat("ARIA", f"""
分析以下需求，判斷最適合的執行場景。

需求：{requirement}

場景選項：
- full_product：全新產品（有完整的用戶需求、需要 UI 設計）
- new_feature：在現有產品新增功能（已有程式碼基礎）
- api_only：純後端 API（無 UI，只需要 API 和測試）
- frontend_only：純前端更新（UI 調整、新頁面，無後端變更）
- bug_fix：修復現有 Bug（定位問題、修復、驗證）
- design_update：設計和 UI 更新（無業務邏輯變更）
- security_patch：安全性修補（無功能變更）

只輸出場景名稱，不要任何解釋：
""")
        scenario = result.strip().lower().split()[0]
        if scenario not in self.SCENARIOS:
            scenario = "full_product"
        return scenario

    def get_phases(self, requirement: str, force_full: bool = False) -> list:
        """取得需要執行的 Phase 列表"""
        if force_full:
            return self.SCENARIOS["full_product"]

        scenario = self.classify_requirement(requirement)
        phases   = self.SCENARIOS[scenario]

        print(f"\n{CYAN}🗺 動態路由：{scenario} → Phase {phases}{RESET}")
        return phases


# ══════════════════════════════════════════════════════════════
#  P1-2：Human-in-the-Loop（高風險操作需要人類確認）
# ══════════════════════════════════════════════════════════════

class HumanGate:
    """
    高風險操作在執行前暫停，等待人類審批。

    觸發條件（任一符合就暫停）：
    - 部署到生產環境
    - 刪除資料（不可逆）
    - 費用超過閾值
    - 安全審查發現高風險問題

    auto_approve=True 時跳過（CI/CD 環境用）
    """

    # 需要人類確認的操作類型
    HIGH_RISK_TRIGGERS = {
        "deploy_production": "部署到生產環境",
        "delete_data":       "刪除資料（不可逆）",
        "cost_threshold":    "費用超過預算閾值",
        "security_critical": "安全審查發現嚴重問題",
    }

    def __init__(self, auto_approve: bool = False):
        self.auto_approve = auto_approve
        self._approvals: dict = {}

    def require_approval(self, trigger: str, context: str = "", details: str = "") -> bool:
        """
        請求人類審批。
        回傳 True = 通過，False = 拒絕。
        auto_approve=True 時直接通過。
        """
        if self.auto_approve:
            return True

        label = self.HIGH_RISK_TRIGGERS.get(trigger, trigger)

        print(f"\n{YELLOW}{BOLD}{'═'*62}")
        print(f"  ⚠️  Human-in-the-Loop：需要審批")
        print(f"{'═'*62}{RESET}")
        print(f"  操作：{label}")
        if context:
            print(f"  背景：{context}")
        if details:
            print(f"\n{DIM}  詳情：")
            for line in details.splitlines()[:10]:
                print(f"    {line}")
        print(f"{RESET}")

        try:
            ans = input(f"  是否批准這個操作？[y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = "n"

        approved = ans in ("y", "yes", "是")
        icon = f"{GREEN}✔ 已批准{RESET}" if approved else f"{RED}✖ 已拒絕{RESET}"
        print(f"  {icon}")

        self._approvals[trigger] = approved
        return approved

    def check_security_findings(self, security_report: str) -> bool:
        """分析安全審查報告，如有嚴重問題要求審批"""
        critical_keywords = ["HIGH", "CRITICAL", "嚴重", "高風險", "RCE", "SQL Injection", "XSS"]
        has_critical = any(kw.lower() in security_report.lower() for kw in critical_keywords)

        if has_critical:
            return self.require_approval(
                "security_critical",
                "安全審查發現高風險問題",
                security_report[:500]
            )
        return True


# ══════════════════════════════════════════════════════════════
#  P1-3：Generator-Critic（ARIA 作為全局品質守門人）
# ══════════════════════════════════════════════════════════════

class GeneratorCritic:
    """
    Generator-Critic 模式：
    每個 Phase 完成後，ARIA 以「嚴格 CTO」角色快速審查輸出，
    判斷是否達到「可繼續」的最低品質標準。

    不是追求完美，是防止明顯的問題帶入下個 Phase。
    設計原則：快速（Haiku 模型）+ 明確標準（非主觀）

    和 SelfCritique 的差異：
    - SelfCritique：深度評審，可觸發改善迴圈（Sonnet）
    - GeneratorCritic：快速守門，只判斷 Pass/Fail（Haiku）
    """

    # 各 Phase 的最低品質標準（快速可驗證的條件）
    PHASE_GATES = {
        "PRD": [
            "至少有 3 個 User Story",
            "每個 P0 功能有 AC",
            "有明確的 Out of Scope",
        ],
        "ARCHITECTURE": [
            "有技術選型列表",
            "有目錄結構",
            "有 API 端點設計",
        ],
        "UX": [
            "有用戶旅程描述",
            "有主要頁面的線框說明",
            "有錯誤狀態的處理方式",
        ],
        "FRONTEND_IMPL": [
            "沒有 // TODO 或 placeholder",
            "提到 typecheck 結果",
            "有 lint 結果",
        ],
        "BACKEND_IMPL": [
            "有 API 端點實作",
            "有認證/授權說明",
            "有錯誤處理",
        ],
    }

    def __init__(self, orchestrator):
        self.orc = orchestrator

    def gate_check(self, doc_name: str, content: str) -> tuple[bool, str]:
        """
        快速守門檢查。
        回傳 (通過, 原因說明)
        """
        gates = self.PHASE_GATES.get(doc_name, [])
        if not gates:
            return True, "無守門條件"

        gates_text = "\n".join(f"- {g}" for g in gates)


        # 用 Haiku 快速判斷（便宜、快速）
        verdict = self.orc._chat("ARIA", f"""
你是品質守門人。用一句話判斷以下文件是否達到最低標準。

文件名稱：{doc_name}
文件內容（前 1000 字）：
{content[:1000]}

必須達到的最低標準：
{gates_text}

輸出格式（只輸出這兩行，不要其他文字）：
GATE: PASS 或 GATE: FAIL
REASON: [一句話說明]
""")

        passed = "GATE: PASS" in verdict
        import re
        reason_match = re.search(r'REASON:\s*(.+)', verdict)
        reason = reason_match.group(1) if reason_match else verdict[:80]

        icon = f"{GREEN}✅ GATE PASS{RESET}" if passed else f"{RED}❌ GATE FAIL{RESET}"
        print(f"  {icon}  {doc_name}: {reason}")

        return passed, reason


# ══════════════════════════════════════════════════════════════
#  P1-4：Dynamic Orchestrator（ARIA 動態決定 Phase 組合）
# ══════════════════════════════════════════════════════════════

class DynamicRouter:
    """
    根據需求類型，讓 ARIA 智能決定需要哪些 Phase。

    傳統流水線：固定 12 Phase，不管需求大小都跑一遍。
    動態路由：
      - 小改動（bugfix）→ 直接進 Phase 9+10+11+12
      - 純後端 API → 跳過 Phase 7（SPARK/UX）、Phase 8（PRISM/UI）
      - 已有架構的功能新增 → 跳過 Phase 4（NEXUS），讀現有架構
      - 完整新產品 → 全部 12 Phase

    透過節省不必要的 Phase，減少 30-60% 的成本和時間。
    """

    ROUTE_TEMPLATES = {
        "full":         list(range(1, 13)),         # 完整 12 Phase
        "feature":      [1, 2, 3, 4, 6, 9, 10, 11, 12],  # 跳過 UX/UI
        "backend_only": [1, 2, 4, 5, 6, 10, 11, 12],      # 只有後端
        "bugfix":       [1, 9, 10, 11, 12],                # 快速修復
        "hotfix":       [10, 11, 12],                      # 緊急修復
        "api_only":     [1, 2, 4, 6, 10, 11, 12],         # API 設計和實作
    }

    ROUTE_DESCRIPTIONS = {
        "full":         "完整新產品（所有 Phase）",
        "feature":      "新增功能（跳過 UX/UI 設計）",
        "backend_only": "純後端 API 開發",
        "bugfix":       "Bug 修復",
        "hotfix":       "緊急修復（最小範圍）",
        "api_only":     "API 設計和實作",
    }

    def __init__(self, orchestrator):
        self.orc = orchestrator

    def classify(self, requirement: str, ctx: DocContext = None) -> tuple[str, list[int]]:
        """
        讓 ARIA 分析需求，回傳最適合的路由模板。
        """
        existing_docs = ""
        if ctx:
            for doc in ["ARCHITECTURE", "PRD"]:
                if ctx.exists(doc):
                    existing_docs += f"已有 {doc} 文件。"

        routes_desc = "\n".join(

            f"- {k}: {v} (Phase: {self.ROUTE_TEMPLATES[k]})"
            for k, v in self.ROUTE_DESCRIPTIONS.items()
        )

        analysis = self.orc._chat("ARIA", f"""
分析以下需求，決定最適合的執行路由。

需求：{requirement}
{f'現有文件：{existing_docs}' if existing_docs else ''}

可用路由：
{routes_desc}

輸出格式（只輸出這一行）：
ROUTE: [路由名稱]
""")

        import re
        match = re.search(r'ROUTE:\s*(\w+)', analysis)
        route = match.group(1) if match else "full"

        if route not in self.ROUTE_TEMPLATES:
            route = "full"

        phases = self.ROUTE_TEMPLATES[route]
        desc   = self.ROUTE_DESCRIPTIONS[route]

        print(f"\n{CYAN}🧭 Dynamic Router：{desc}")
        print(f"  執行 Phase：{phases}{RESET}")

        return route, phases


# ══════════════════════════════════════════════════════════════
#  P1-1 修復：Phase 斷點續跑 + 快取
# ══════════════════════════════════════════════════════════════

class PhaseCheckpoint:
    """
    記錄每個 Phase 的完成狀態，支援從中斷點繼續執行。

    狀態儲存在 docs/.ship_state.json：
    {
      "requirement": "...",
      "started_at": "...",
      "phases": {
        "1": {"status": "done", "completed_at": "..."},
        "2": {"status": "done", ...},
        "6": {"status": "failed", "error": "..."},
      }
    }
    """

    def __init__(self, workdir: str, requirement: str):
        self.state_file  = Path(workdir) / "docs" / ".ship_state.json"
        self.requirement = requirement
        self._workdir    = workdir
        self._lock_fd    = None
        self.state       = self._load()
        self._acquire_lock(workdir)   # P0-4：進程鎖防止並發 ship()

    def _acquire_lock(self, workdir: str) -> None:
        try:
            import fcntl
            lock_path = Path(workdir) / ".synthex_ship.lock"
            self._lock_fd = open(str(lock_path), "w")
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            pass   # Windows 無 fcntl
        except OSError:
            _warn("⚠ 偵測到另一個 ship() 進程，可能造成狀態衝突")
            self._lock_fd = None

    def _release_lock(self) -> None:
        if self._lock_fd:
            try:
                import fcntl
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                self._lock_fd.close()
            except Exception: pass
            self._lock_fd = None

    def close(self) -> None:
        self._save()
        self._release_lock()

        # 如果是新需求，重置狀態
        if self.state.get("requirement") != requirement:
            self.state = {
                "requirement": requirement,
                "started_at": datetime.now().isoformat(),
                "phases": {}
            }
            self._save()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        self.state_file.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2)
        )

    def is_done(self, phase: int) -> bool:
        return self.state.get("phases", {}).get(str(phase), {}).get("status") == "done"

    def mark_done(self, phase: int):
        if "phases" not in self.state:
            self.state["phases"] = {}
        self.state["phases"][str(phase)] = {
            "status": "done",
            "completed_at": datetime.now().isoformat()
        }
        self._save()

    def mark_failed(self, phase: int, error: str = ""):
        if "phases" not in self.state:
            self.state["phases"] = {}
        self.state["phases"][str(phase)] = {
            "status": "failed",
            "failed_at": datetime.now().isoformat(),
            "error": error
        }
        self._save()

    def resume_info(self) -> str:
        done = [k for k, v in self.state.get("phases", {}).items()
                if v.get("status") == "done"]
        if done:
            return f"  續跑模式：Phase {', '.join(sorted(done))} 已完成，跳過"
        return ""


# ══════════════════════════════════════════════════════════════
#  主 Orchestrator
# ══════════════════════════════════════════════════════════════

class WebOrchestrator:

    def __init__(self, workdir: str = None, auto_confirm: bool = False,
                 smart_route: bool = False):
        self.workdir      = workdir or os.getcwd()
        self.auto_confirm = auto_confirm
        self.smart_route  = smart_route  # P1-4 動態路由

    def _use_web_tools(self, agent):
        from core.web_tools import WebToolExecutor
        agent.executor = WebToolExecutor(workdir=self.workdir,
                                          auto_confirm=self.auto_confirm)
        return agent

    def _agent(self, name: str):
        from agents.all_agents import get_agent
        import core.tools as ct
        from core.web_tools import get_webdev_tools
        agent = get_agent(name, workdir=self.workdir, auto_confirm=self.auto_confirm)
        orig  = ct.get_tools_for_role
        ct.get_tools_for_role = lambda role: get_webdev_tools(role)
        agent._orig_get_tools = orig
        return self._use_web_tools(agent)

    def _chat(self, name: str, task: str) -> str:
        agent = self._agent(name)
        import core.tools as ct
        try:
            return agent.chat(task)
        finally:
            if hasattr(agent, "_orig_get_tools"):
                ct.get_tools_for_role = agent._orig_get_tools

    def _run(self, name: str, task: str) -> str:
        agent = self._agent(name)
        import core.tools as ct
        try:
            return agent.run(task)
        finally:
            if hasattr(agent, "_orig_get_tools"):
                ct.get_tools_for_role = agent._orig_get_tools

    # ──────────────────────────────────────────────────────────
    #  /ship 主流水線（完整重構）
    # ──────────────────────────────────────────────────────────

    def ship(self, requirement: str, resume: bool = True) -> dict:
        """
        /ship — 13 Phase 完整流水線

        P0 修復：所有 Phase 間的資料傳遞改為讀取完整文件
        P1 修復：支援斷點續跑（resume=True 時跳過已完成的 Phase）
        """
        start    = datetime.now()
        ctx      = DocContext(self.workdir)
        ckpt     = PhaseCheckpoint(self.workdir, requirement)
        critique = SelfCritique(self)              # P0-2 Self-Critique Loop
        gc       = GeneratorCritic(self)           # P1-3 Generator-Critic
        hil      = HumanGate(self.auto_confirm)    # P1-2 Human-in-the-Loop
        router   = DynamicOrchestrator(self)       # P1-4 Dynamic Orchestrator
        results  = {}

        # P1-4：動態路由（根據需求類型選擇 Phase）
        force_full = not resume  # no_resume 時強制完整流程
        active_phases = set(router.get_phases(requirement, force_full=force_full))

        resume_msg = ckpt.resume_info()

        print(f"\n{PURPLE}{BOLD}{'═'*62}")
        print(f"  🚀  SYNTHEX /ship  {'（續跑）' if resume_msg else ''}")
        print(f"  需求：{requirement[:58]}{'...' if len(requirement) > 58 else ''}")
        print(f"  目錄：{self.workdir}")
        if resume_msg:
            print(f"{CYAN}{resume_msg}{RESET}")
        print(f"{'═'*62}{RESET}")

        # ── Phase 1：ARIA 任務確認 ─────────────────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 1 not in active_phases and not ckpt.is_done(1):
            _ok(f"Phase 1（ARIA 任務確認）已被動態路由跳過")
        elif resume and ckpt.is_done(1):
            _ok("Phase 1 已完成，跳過")
        else:
            _phase(1, "ARIA — 任務接收與範疇確認")
            scope = self._chat("ARIA", f"""
執行 /ship 流水線的 Phase 1。

需求：{requirement}

請輸出任務確認報告（嚴格按照你的 Phase 1 格式）。
有任何不確定的地方，在這裡提問，不帶著假設進入後續 Phase。
""")
            ctx.write("SCOPE", scope, "範疇確認")
            results["phase1_scope"] = scope
            if "⚠️ 需要確認" in scope:
                print(f"\n{YELLOW}  ⚠ ARIA 有疑問，流水線暫停{RESET}")
                ckpt.mark_failed(1, "需要使用者確認")
                return results
            ckpt.mark_done(1)

        # ── Phase 2：ECHO 寫 PRD ───────────────────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 2 not in active_phases and not ckpt.is_done(2):
            _ok(f"Phase 2（ECHO PRD）已被動態路由跳過")
        elif resume and ckpt.is_done(2):
            _ok("Phase 2 已完成，跳過")
        else:
            _phase(2, "ECHO — 需求分析與 PRD")
            # P0 修復：傳遞完整範疇，不截斷
            prd = self._chat("ECHO", f"""
執行 /ship 流水線的 Phase 2。

原始需求：{requirement}

ARIA 的範疇確認：
{ctx.read("SCOPE")}

請嚴格按照你的 Phase 2 格式產出完整 PRD。
每個欄位都必須填寫，驗收標準（AC）要具體可驗證。
""")
            # P0-2 + P1-2：Self-Critique — LUMI 評審 PRD 品質
            # P1-2 修復：不用 lambda 捕獲外部變數，改用 Orchestrator 重新呼叫 ECHO
            _prd_ref = [prd]   # 用 list 讓內層函數可以修改

            def _prd_generate():
                return _prd_ref[0]

            def _prd_improve(fb: str) -> str:
                improved = self._chat("ECHO", f"""
LUMI 的評審反饋指出以下問題：
{fb}

請根據以上反饋修訂 PRD，特別注意：
1. 所有 P0 功能的 AC 改為 GIVEN-WHEN-THEN 格式
2. 補上邊界條件（空狀態、錯誤狀態）
3. 補上遺漏的「不在範疇」說明

輸出完整的修訂版 PRD（不要說明，直接輸出）。
""")
                _prd_ref[0] = improved   # 更新參考
                return ""   # 空字串表示已由 improve_fn 直接產生

            prd = critique.critique_loop(
                "PRD", ctx,
                generate_fn=_prd_generate,
                improve_prompt_fn=_prd_improve,
            )
            # P1-3：Generator-Critic 評審 PRD
            if not gc.gate("PRD", ctx) and not self.auto_confirm:
                _warn("PRD 品質未達標，建議修改後重新執行 Phase 2")
            results["phase2_prd"] = prd
            ckpt.mark_done(2)

        # ── Phase 3：LUMI 產品驗證 ────────────────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 3 not in active_phases and not ckpt.is_done(3):
            _ok(f"Phase 3（LUMI 產品驗證）已被動態路由跳過")
        elif resume and ckpt.is_done(3):
            _ok("Phase 3 已完成，跳過")
        else:
            _phase(3, "LUMI — 產品驗證")
            # P0 修復：讀完整 PRD 文件
            validation = self._chat("LUMI", f"""
執行 /ship 流水線的 Phase 3。

請審查以下完整 PRD：

{ctx.read("PRD")}

確認用戶旅程完整性、指出邏輯問題和 UX 風險。
輸出驗證報告（嚴格按照你的 Phase 3 格式）。
""")
            ctx.write("VALIDATION", validation, "產品驗證報告")
            results["phase3_validation"] = validation

            if "需要修改" in validation and "✅ PRD 通過" not in validation:
                _warn("LUMI 要求修改 PRD，ECHO 更新中...")
                revised_prd = self._chat("ECHO", f"""
LUMI 的驗證報告指出以下問題：
{ctx.read("VALIDATION")}

請根據意見更新 PRD，輸出修訂後的完整版本。
""")
                ctx.write("PRD", revised_prd, "Product Requirements Document（修訂版）")
                results["phase2_prd_revised"] = revised_prd
                _ok("PRD 已更新")
            ckpt.mark_done(3)

        # ── Phase 4：NEXUS 技術架構 ───────────────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 4 not in active_phases and not ckpt.is_done(4):
            _ok(f"Phase 4（NEXUS 技術架構）已被動態路由跳過")
        elif resume and ckpt.is_done(4):
            _ok("Phase 4 已完成，跳過")
        else:
            _phase(4, "NEXUS — 技術架構設計")
            # P0 修復：讀完整 PRD，同時讓 NEXUS 掃描專案
            arch = self._run("NEXUS", f"""
執行 /ship 流水線的 Phase 4。

請先用 get_project_info 了解現有技術棧，然後閱讀以下完整 PRD：

{ctx.read("PRD")}

產出完整技術架構文件（嚴格按照你的 Phase 4 格式）。
技術選型必須和現有技術棧相容，說明每個選擇的理由和 trade-off。

P2 要求：
- 為每個重要技術決策建立 ADR 條目（格式：docs/adr/ADR-NNN-title.md）
- ADR 格式：背景 / 決策 / 理由 / 後果
""")
            # P0-2：Self-Critique — NEXUS 複審架構品質
            eval_result = critique.evaluate("ARCHITECTURE", arch)
            if not eval_result["passed"] and eval_result["score"] < 6:
                _warn(f"架構評分 {eval_result['score']}/10，讓 NEXUS 改善...")
                arch = self._chat("NEXUS", f"""
你的架構文件評審反饋（分數：{eval_result['score']}/10）：
{eval_result['feedback']}

請根據反饋改善架構文件，特別注意：
1. 確保三層分離（路由/Service/Repository）在目錄結構中明確
2. 確保所有重要技術決策有 ADR 連結
3. 確保技術風險矩陣完整

輸出完整的改善版架構文件。
""")
                ctx.write("ARCHITECTURE", arch, "技術架構（改善版）")
            # P1-3：Generator-Critic 評審架構文件
            gc.gate("ARCHITECTURE", ctx)
            results["phase4_arch"] = arch
            ckpt.mark_done(4)

        # ── Phase 5：SIGMA 可行性評估 ─────────────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 5 not in active_phases and not ckpt.is_done(5):
            _ok(f"Phase 5（SIGMA 可行性評估）已被動態路由跳過")
        elif resume and ckpt.is_done(5):
            _ok("Phase 5 已完成，跳過")
        else:
            _phase(5, "SIGMA — 可行性評估")
            feasibility = self._chat("SIGMA", f"""
執行 /ship 流水線的 Phase 5。

完整架構設計：
{ctx.read("ARCHITECTURE")}

完整 PRD：
{ctx.read("PRD")}

輸出可行性評估報告（嚴格按照你的 Phase 5 格式）。
""")
            ctx.write("FEASIBILITY", feasibility, "可行性評估")
            results["phase5_feasibility"] = feasibility
            if "❌ 建議重新評估" in feasibility:
                _warn("SIGMA 建議重新評估範疇，流水線暫停")
                ckpt.mark_failed(5, "可行性評估未通過")
                return results
            ckpt.mark_done(5)

        # ── Phase 6：FORGE 環境準備（含可觀測性）────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 6 not in active_phases and not ckpt.is_done(6):
            _ok(f"Phase 6（FORGE 環境準備）已被動態路由跳過")
        elif resume and ckpt.is_done(6):
            _ok("Phase 6 已完成，跳過")
        else:
            _phase(6, "FORGE — 環境準備")
            env_result = self._run("FORGE", f"""
執行 /ship 流水線的 Phase 6。

完整架構要求：
{ctx.read("ARCHITECTURE")}

依序執行：
1. get_project_info 了解現有環境
2. 建立缺少的目錄結構
3. 安裝缺少的依賴套件
4. 安裝並設定 Sentry（npm install @sentry/nextjs）
5. 安裝並設定 PostHog（npm install posthog-js）
6. 建立 .env.local.example（含 Sentry/PostHog key）
7. 確認專案可以啟動
8. 輸出環境就緒報告
""")
            ctx.write("ENV_SETUP", env_result, "環境設定報告")
            results["phase6_env"] = env_result
            ckpt.mark_done(6)

        # ── Phase 7：SPARK UX 設計 ────────────────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 7 not in active_phases and not ckpt.is_done(7):
            _ok(f"Phase 7（SPARK UX 設計）已被動態路由跳過")
        elif resume and ckpt.is_done(7):
            _ok("Phase 7 已完成，跳過")
        else:
            _phase(7, "SPARK — UX 設計")
            ux = self._chat("SPARK", f"""
執行 /ship 流水線的 Phase 7。

完整 PRD（含所有功能和用戶故事）：
{ctx.read("PRD")}

完整技術架構（含頁面路由設計）：
{ctx.read("ARCHITECTURE")}

請產出 docs/UX.md，包含：
1. 每個 P0 功能的用戶旅程地圖（含痛點和情緒）
2. 資訊架構（網站地圖 + 導航設計）
3. 每個主要頁面的 ASCII 線框（桌機 + 手機）
4. 關鍵互動規格（loading/error/empty 三種狀態）
5. 無障礙考量（WCAG 2.1 AA）

嚴格按照你的 SKILL.md 的格式輸出。
""")
            ctx.write("UX", ux, "UX 設計文件")
            # P1-3：Gate check
            passed, reason = gate.gate_check("UX", ux)
            if not passed:
                _warn(f"UX 文件未達標：{reason}，SPARK 補充中...")
                ux += self._chat("SPARK", f"補充以下缺漏後重新輸出完整 UX 文件：{reason}")
                ctx.write("UX", ux, "UX 設計文件（補強版）")
            ckpt.mark_done(7)

        # ── Phase 8：PRISM UI 設計系統 ─────────────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 8 not in active_phases and not ckpt.is_done(8):
            _ok(f"Phase 8（PRISM UI 設計系統）已被動態路由跳過")
        elif resume and ckpt.is_done(8):
            _ok("Phase 8 已完成，跳過")
        else:
            _phase(8, "PRISM — UI 設計系統")
            ui = self._run("PRISM", f"""
執行 /ship 流水線的 Phase 8。

品牌個性（從 UX 文件推導）：
{ctx.read_section("UX", 800)}

CLAUDE.md 設計風格指引：Linear.app 簡潔風

依照你的 SKILL.md 執行：
1. 根據品牌個性決定主色方案（先輸出 A/B 兩個選項說明）
2. 產出完整 src/styles/tokens.css（所有欄位填入真實色碼）
3. 產出完整 src/styles/components.css（所有元件含所有狀態）
4. 產出 docs/DESIGN-SYSTEM.md

BYTE 的所有顏色/間距都只能引用 tokens.css 的變數。
""")
            ctx.write("UI_SYSTEM", ui, "UI 設計系統報告")
            ckpt.mark_done(8)

        # ── Phase 9 + 10：BYTE 前端 + STACK 後端（並行執行）─────
        # P0-1：動態路由 Phase 9+10 的外層跳過
        # P0-1 修復：Phase 9/10 各自獨立路由（api_only 跳 9，frontend_only 跳 10）
        skip_9  = (9  not in active_phases) and not ckpt.is_done(9)
        skip_10 = (10 not in active_phases) and not ckpt.is_done(10)
        if skip_9:  _ok("Phase 9（BYTE 前端）已被動態路由跳過")
        if skip_10: _ok("Phase 10（STACK 後端）已被動態路由跳過")
        if both_done:
            _ok("Phase 7 + 8 已完成，跳過")
            frontend = ctx.read("FRONTEND_IMPL")
            backend  = ctx.read("BACKEND_IMPL")
        else:
            import concurrent.futures, threading

            prd_content  = ctx.read("PRD")
            arch_content = ctx.read("ARCHITECTURE")

            byte_task  = None
            stack_task = None

            def _run_byte():
                if resume and ckpt.is_done(9):
                    _ok("Phase 9 已完成，跳過")
                    return ctx.read("FRONTEND_IMPL")
                _phase(9, "BYTE — 前端實作（並行）")
                result = self._run("BYTE", f"""
執行 /ship 流水線的 Phase 7。

完整 PRD（含所有頁面和路由）：
{prd_content}

完整技術架構（含目錄結構和元件架構）：
{arch_content}

硬性規定：
- 不留任何 // TODO 或 placeholder
- 所有 TypeScript 型別明確定義，不用 any
- 每個組件有 loading/error/empty 三種狀態
- 所有顏色/間距只能用 tokens.css 變數
- 完成後執行 lint 和 typecheck，有錯就修

實作順序：型別定義 → API 客戶端 → 組件 → 頁面 → 路由
""")
                ctx.write("FRONTEND_IMPL", result, "前端實作報告")
                # P1-1：GeneratorCritic 評審前端實作
                gc.gate("FRONTEND_IMPL", ctx)
                ckpt.mark_done(9)
                return result

            def _run_stack():
                if resume and ckpt.is_done(10):
                    _ok("Phase 10 已完成，跳過")
                    return ctx.read("BACKEND_IMPL")
                _phase(10, "STACK — 後端實作（並行）")
                result = self._run("STACK", f"""
執行 /ship 流水線的 Phase 8。

完整 PRD（含所有 API 端點規格）：
{prd_content}

完整技術架構（含資料庫 Schema 和 API 設計）：
{arch_content}

硬性規定：
- 每個 API 端點有完整錯誤處理
- 所有輸入有型別驗證
- 敏感操作有授權檢查
- 遵循三層分離：路由層 → Service 層 → Repository 層
- 完成後測試每個端點

實作順序：資料模型 → Repository → Service → API 路由 → 中間件
""")
                ctx.write("BACKEND_IMPL", result, "後端實作報告")
                # P1-1：GeneratorCritic 評審後端實作
                gc.gate("BACKEND_IMPL", ctx)
                ckpt.mark_done(10)
                return result

            print(f"\n{CYAN}{BOLD}  ⚡ Phase 7 + 8 並行執行（預計節省 30-50% 時間）{RESET}")
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                f7 = pool.submit(_run_byte)
                f8 = pool.submit(_run_stack)
                # P0-4：future.result() 必須有 timeout，防死鎖
                _PHASE_TIMEOUT = 600   # 10 分鐘
                try:
                    frontend = f7.result(timeout=_PHASE_TIMEOUT)
                except __import__('concurrent.futures').TimeoutError:
                    _warn("Phase 9（BYTE 前端）超時，使用空結果繼續")
                    frontend = "[Phase 9 超時]"
                try:
                    backend  = f8.result(timeout=_PHASE_TIMEOUT)
                except __import__('concurrent.futures').TimeoutError:
                    _warn("Phase 10（STACK 後端）超時，使用空結果繼續")
                    backend  = "[Phase 10 超時]"

            results["phase7_frontend"] = frontend
            results["phase8_backend"]  = backend

        # ── Phase 11：PROBE 策略 + TRACE 執行 ───────────────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 11 not in active_phases and not ckpt.is_done(11):
            _ok(f"Phase 11（PROBE+TRACE 測試）已被動態路由跳過")
        elif resume and ckpt.is_done(11):
            _ok("Phase 9 已完成，跳過")
        else:
            _phase(9, "PROBE + TRACE — 完整測試")
            _step("PROBE 制定測試策略...")
            # P0 修復：讀完整 PRD 的驗收標準
            test_strategy = self._chat("PROBE", f"""
執行 /ship 流水線的 Phase 9a，制定完整測試策略。

完整 PRD（含所有驗收標準）：
{ctx.read("PRD")}

前端實作摘要：
{ctx.read_section("FRONTEND_IMPL", 800)}

後端實作摘要：
{ctx.read_section("BACKEND_IMPL", 800)}

輸出完整測試策略，包含：
1. 單元測試目標（核心業務邏輯函數）
2. API 整合測試（每個端點的 happy path + error cases）
3. E2E 測試（最重要的用戶旅程）
4. 契約測試（前後端 API 介面一致性）
5. 負載測試基準（k6，關鍵端點的承載量目標）
6. 品質門禁
""")
            ctx.write("TEST_STRATEGY", test_strategy, "測試策略")

            _step("TRACE 執行所有測試...")
            test_result = self._run("TRACE", f"""
執行 /ship 流水線的 Phase 9b。

依據以下測試策略實作並執行所有測試：
{ctx.read("TEST_STRATEGY")}

工作目錄：{self.workdir}

執行順序：
1. 單元測試 → 修復失敗
2. API 整合測試 → 修復失敗
3. E2E 測試（主要流程）→ 修復失敗
4. lint_and_typecheck → 0 errors

如果有測試失敗：分析原因 → 修復程式碼或測試 → 重跑 → 確認全綠
""")
            ctx.write("TEST_RESULTS", test_result, "測試結果")
            # P1-1：GeneratorCritic 評審測試品質
            gc.gate("TEST_RESULTS", ctx)
            results["phase9_tests"] = test_result
            ckpt.mark_done(11)

        # ── Phase 12：SHIELD 安全審查（含自動化掃描）─────────
        # P1-4 動態路由：跳過不在 active_phases 的 Phase
        if 12 not in active_phases and not ckpt.is_done(12):
            _ok(f"Phase 12（SHIELD 安全審查）已被動態路由跳過")
        elif resume and ckpt.is_done(12):
            _ok("Phase 12 已完成，跳過")
        else:
            _phase(12, "SHIELD — 安全審查與修復")
            security = self._run("SHIELD", f"""
執行 /ship 流水線的 Phase 10。

對 {self.workdir} 執行完整安全審查：

步驟 1：自動化掃描
  - run_command: npm audit（依賴漏洞）
  - run_command: npx semgrep --config=auto src/（SAST 靜態分析）
  - run_command: npx gitleaks detect --source=. --no-git（Secret 掃描）
  如果工具未安裝，先安裝後執行。

步驟 2：程式碼審查
  逐一確認你的安全檢查清單（輸入驗證、越權、敏感資料）

步驟 3：修復
  發現問題立即修復，不是只列出來

輸出安全審查報告（按你的 Phase 10 格式）。
""")
            ctx.write("SECURITY", security, "安全審查報告")
            # P1-1：GeneratorCritic 評審安全審查（最高標準 9/10）
            if not gc.gate("SECURITY", ctx):
                _warn("安全審查品質未達標（9/10），建議重新執行 Phase 12")
            results["phase10_security"] = security
            ckpt.mark_done(12)

        # ── Phase 12：ARIA 交付總結 ───────────────────────────
        _phase(11, "ARIA — 交付總結")
        elapsed = (datetime.now() - start).seconds

        delivery = self._run("FORGE", f"""
執行 /ship 最終收尾。

1. 建立 docs/DELIVERY.md，包含：
   - 完成項目（對應 PRD 驗收標準逐一核對）
   - 新增/修改的檔案清單
   - 啟動方式（本地開發 + 生產環境）
   - 需要手動設定的環境變數
   - 已知限制
   - 下一步建議（P1/P2 功能）

   PRD 路徑：docs/PRD.md
   架構路徑：docs/ARCHITECTURE.md
   測試報告：docs/TEST_RESULTS.md
   安全報告：docs/SECURITY.md
   耗時：{elapsed} 秒

2. git add .
3. git commit -m "feat: {requirement[:60].strip()}"
""")
        ctx.write("DELIVERY", delivery, "交付摘要")
        results["phase11_delivery"] = delivery
        ckpt.mark_done(12)

        # 清除 checkpoint（成功完成）
        if ckpt.state_file.exists():
            ckpt.state_file.unlink()

        # Token 成本報告 + Agent 監控摘要
        try:
            from core.base_agent import get_session_budget, AgentDecisionLog
            budget = get_session_budget()
            print(budget.summary())
            print(budget.per_agent_summary())
            # Agentic Monitoring 摘要
            monitor = AgentDecisionLog(self.workdir)
            print(monitor.summary())
        except Exception:
            pass

        print(f"\n{GREEN}{BOLD}{'═'*62}")
        print(f"  ✅  /ship 完成！耗時 {elapsed} 秒")
        print(f"  📁  {self.workdir}/docs/")
        print(f"  文件：PRD · ARCHITECTURE · TEST_RESULTS · SECURITY · DELIVERY")
        print(f"{'═'*62}{RESET}")

        return results

    # ──────────────────────────────────────────────────────────
    #  其他方法（build、feature、fix、review、discover）
    # ──────────────────────────────────────────────────────────

    def build(self, requirement: str, project_name: str = None) -> dict:
        """舊版 build() — 導向新的 ship()"""
        return self.ship(requirement)

    def feature(self, description: str) -> str:
        _phase(0, f"新功能：{description[:50]}")
        ctx = DocContext(self.workdir)

        _step("ECHO 分析功能規格...")
        spec = self._chat("ECHO", f"""
分析以下功能需求，輸出實作規格：
- 具體的前端需求（頁面、組件、API 呼叫）
- 具體的後端需求（API 端點、資料模型變更）
- 影響的現有檔案
- 測試方案

功能需求：{description}
專案目錄：{self.workdir}
""")
        ctx.write("FEATURE_SPEC", spec, f"功能規格：{description[:40]}")

        _step("FLUX 實作功能...")
        result = self._run("FLUX", f"""
實作以下功能：

功能規格：
{ctx.read("FEATURE_SPEC")}

原始需求：{description}

步驟：
1. get_project_info 了解程式碼結構
2. 實作功能（前後端）
3. lint_and_typecheck
4. git add . && git commit -m "feat: {description[:50]}"
""")
        return result

    def fix(self, error_description: str) -> str:
        _phase(0, "Bug 修復")
        return self._run("STACK", f"""
診斷並修復以下問題：

問題：{error_description}

步驟：
1. get_project_info + search_files 定位問題
2. 分析根本原因
3. 修復
4. lint_and_typecheck
5. git commit -m "fix: {error_description[:40]}"
""")

    def review(self) -> str:
        _phase(0, "全面程式碼審查")
        probe = self._run("PROBE", f"""
對 {self.workdir} 執行全面品質審查：
1. get_project_info 了解結構
2. lint_and_typecheck 靜態分析
3. npm_run('test') 執行測試
4. 審查主要組件品質
5. 列出問題（按嚴重程度）
6. 提供修復建議
""")
        shield = self._chat("SHIELD", f"""
補充安全性分析：

程式碼審查結果摘要：
{probe[:1000]}

專案目錄：{self.workdir}

重點：輸入驗證、授權、敏感資料、CORS、rate limiting
""")
        return probe + "\n\n" + shield

    def discover(self, vague_idea: str) -> dict:
        ctx  = DocContext(self.workdir)
        results = {}

        print(f"\n{CYAN}{BOLD}{'='*62}")
        print(f"  🔍  /discover — 需求深度挖掘")
        print(f"  想法：{vague_idea[:56]}{'...' if len(vague_idea)>56 else ''}")
        print(f"{'='*62}{RESET}")

        _phase(1, "LUMI — 用戶與市場挖掘")
        user_insight = self._chat("LUMI", f"""
深挖以下產品想法的用戶與市場面。

想法：{vague_idea}

分析：
1. 目標用戶（越具體越好）
2. 用戶旅程（Before/During/After）
3. 市場機會和差異化
4. 最危險的假設

直接輸出分析，不要問問題。
""")
        ctx.write("DISCOVER_USER", user_insight, "用戶分析")
        results["user_insight"] = user_insight

        _phase(2, "ARIA — 業務定位與可行性")
        business = self._chat("ARIA", f"""
評估以下產品想法的業務可行性。

想法：{vague_idea}

用戶分析：
{ctx.read("DISCOVER_USER")}

輸出：商業模式建議、MVP 邏輯、風險評估、Go/No-Go 建議
""")
        ctx.write("DISCOVER_BIZ", business, "業務分析")
        results["business"] = business

        _phase(3, "ECHO — 功能邊界釐清")
        features = self._chat("ECHO", f"""
把以下模糊想法轉化成具體功能規格。

想法：{vague_idea}
用戶分析：{ctx.read_section("DISCOVER_USER", 600)}
業務定位：{ctx.read_section("DISCOVER_BIZ", 400)}

輸出：功能清單（標注假設/明確需求）、P0/P1/P2 排序、不做什麼
""")
        ctx.write("DISCOVER_FEATURES", features, "功能分析")
        results["features"] = features

        _phase(4, "NEXUS — 技術現實評估")
        tech = self._chat("NEXUS", f"""
對以下產品進行技術可行性評估。

想法：{vague_idea}
功能分析：{ctx.read_section("DISCOVER_FEATURES", 800)}

輸出：技術複雜度、推薦技術棧、第三方服務費用、MVP 技術範疇
""")
        ctx.write("DISCOVER_TECH", tech, "技術評估")
        results["tech"] = tech

        _phase(5, "SIGMA — 資源規劃")
        resources = self._chat("SIGMA", f"""
整合分析，產出資源規劃。

技術評估：{ctx.read_section("DISCOVER_TECH", 800)}
業務定位：{ctx.read_section("DISCOVER_BIZ", 400)}

輸出：開發時間估算、月營運成本、關鍵里程碑
""")
        ctx.write("DISCOVER_RESOURCES", resources, "資源規劃")
        results["resources"] = resources

        _phase(6, "ARIA — 整合需求書")
        # P0-2 修復：讀完整文件，不截斷
        final = self._chat("ARIA", f"""
整合以下五份完整分析報告，產出最終需求書和可直接執行的 /ship 指令。

=== 用戶分析（完整）===
{ctx.read("DISCOVER_USER")}

=== 業務定位（完整）===
{ctx.read("DISCOVER_BIZ")}

=== 功能分析（完整）===
{ctx.read("DISCOVER_FEATURES")}

=== 技術評估（完整）===
{ctx.read("DISCOVER_TECH")}

=== 資源規劃（完整）===
{ctx.read("DISCOVER_RESOURCES")}

輸出：
1. 產品需求書（一句話定義、目標用戶、MVP 功能、技術決策、成功指標）
2. 可直接執行的 /ship 指令（具體、完整、不需要再問問題）
""")
        ctx.write("DISCOVER_FINAL", final, "需求書")
        results["final"] = final

        _ok(f"需求書已儲存：{ctx.docs}/DISCOVER_FINAL.md")
        print(f"\n{GREEN}  下一步：python synthex.py ship \"（從 DISCOVER_FINAL.md 複製）\"{RESET}")

        return results
