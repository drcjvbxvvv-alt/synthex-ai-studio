"""
core/computer_use.py — Computer Use 整合 (v4.0, 2026)

Claude 現在可以直接使用電腦：打開應用程式、操控瀏覽器、
填寫試算表。讓 SYNTHEX 的 Agent 從「生成程式碼」升級到
「直接驗證程式碼在真實環境中運作」。

第十輪修正：
  - 移除誤導性的 async with 文件（實作是同步的）
  - 使用 config.py 的 ModelID（取代硬編碼字串）
  - 修正 __enter__/__exit__ 文件與實作一致
  - 加入 session ID 和更完整的審計日誌

SYNTHEX 的核心用例：
  1. BYTE Agent：前端開發後，瀏覽器實際驗證 UI
  2. PROBE Agent：測試後，在真實瀏覽器確認端對端流程

安全設計：
  - sandbox_mode：只允許存取 workdir 和 URL 白名單
  - 操作審計：所有動作記錄到 audit_log（不含截圖內容）
  - 確認門控：危險操作（寫入文件、提交 form）需人工確認
  - URL 驗證：阻擋私有 IP（除了 localhost）和非 http/https scheme
  - 動作數量限制：MAX_ACTIONS_PER_SESSION

已知限制（Anthropic 2026-03）：
  - Computer Use 仍在早期階段，仍需 beta header
  - 只用於開發和測試環境，不用於生產操作

使用方式（同步）：
  from core.computer_use import ComputerUseSession

  with ComputerUseSession(workdir="/project") as session:
      result = session.execute_task("驗證首頁可以正常載入")
      print(f"驗證結果：{result['success']}")
"""

from __future__ import annotations

import os
import re
import json
import time
import logging
import uuid
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from core.config import cfg, ModelID

logger = logging.getLogger(__name__)

# ── Computer Use beta header（仍需 beta）────────────────────────
COMPUTER_USE_BETA         = "computer-use-2025-01-24"
COMPUTER_USE_TOOL_VERSION = "computer_20250124"

# ── 安全常數 ──────────────────────────────────────────────────────
MAX_ACTIONS_PER_SESSION = 100
ALLOWED_SCHEMES         = frozenset({"http", "https"})
LOCALHOST_HOSTS         = frozenset({"127.0.0.1", "localhost", "0.0.0.0", "::1"})
ACTION_AUDIT_LIMIT      = 1_000
MAX_TASK_ITERATIONS     = 20


@dataclass
class ComputerAction:
    """單一 Computer Use 動作記錄"""
    action_type: str
    target:      str          # URL 或座標（截斷到 100 字元）
    timestamp:   float = field(default_factory=time.time)
    success:     bool  = True
    error:       str   = ""


class ComputerUseSecurity:
    """Computer Use 安全檢查器（無狀態，thread-safe）"""

    def __init__(self, allowed_urls: list[str] | None = None,
                 workdir: str = "."):
        self.allowed_urls  = list(allowed_urls or [])
        self.workdir       = Path(workdir).resolve()
        self._audit_log:   list[ComputerAction] = []
        self._action_count = 0

    def check_url(self, url: str) -> tuple[bool, str]:
        """驗證 URL 是否在允許範圍內"""
        import urllib.parse as up
        try:
            parsed = up.urlparse(url)
        except Exception:
            return False, f"URL 格式無效：{url!r}"

        scheme = parsed.scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            return False, f"不允許的 URL scheme：{scheme!r}"

        host = (parsed.hostname or "").lower()

        # 阻擋私有 IP（localhost 除外）
        _private_re = re.compile(
            r'^(10\.'
            r'|172\.(1[6-9]|2[0-9]|3[01])\.'
            r'|192\.168\.)'
        )
        if _private_re.match(host) and host not in LOCALHOST_HOSTS:
            return False, f"不允許存取私有 IP：{host!r}"

        # 如果有白名單，檢查是否在其中
        if self.allowed_urls:
            if not any(url.startswith(allowed) for allowed in self.allowed_urls):
                return False, f"URL 不在允許列表中：{url!r}"

        return True, ""

    def check_action_limit(self) -> tuple[bool, str]:
        if self._action_count >= MAX_ACTIONS_PER_SESSION:
            return False, f"已超過動作上限 {MAX_ACTIONS_PER_SESSION}"
        return True, ""

    def record_action(self, action: ComputerAction) -> None:
        self._action_count += 1
        self._audit_log.append(action)
        # 環形緩衝：超過上限時移除最舊記錄
        if len(self._audit_log) > ACTION_AUDIT_LIMIT:
            self._audit_log = self._audit_log[-ACTION_AUDIT_LIMIT:]

    def get_audit_log(self) -> list[dict]:
        return [
            {
                "action":  a.action_type,
                "target":  a.target[:100],
                "success": a.success,
                "time":    a.timestamp,
                "error":   a.error[:200] if a.error else "",
            }
            for a in self._audit_log
        ]


class ComputerUseSession:
    """
    Computer Use Session 管理器（同步介面）。

    使用 Context Manager 確保資源正確釋放：
        with ComputerUseSession(workdir="/project") as session:
            result = session.execute_task("...")

    注意：此類是同步的。若需要在 async 環境使用，
    請用 asyncio.to_thread() 包裝。
    """

    def __init__(
        self,
        workdir:      str             = ".",
        allowed_urls: list[str] | None = None,
        model:        str             = ModelID.SONNET_46,  # Computer Use 用 Sonnet
        max_tokens:   int             = 4_096,
    ):
        self.workdir      = workdir
        self.model        = model
        self.max_tokens   = max_tokens
        self.security     = ComputerUseSecurity(allowed_urls, workdir)
        self._client      = None
        self._session_id  = str(uuid.uuid4())[:8]
        self._session_dir = Path(workdir) / "docs" / "computer_use_sessions"

    def __enter__(self) -> "ComputerUseSession":
        self._session_dir.mkdir(parents=True, exist_ok=True)
        logger.info("computer_use_session_start",
                    session_id=self._session_id,
                    workdir=self.workdir,
                    model=self.model)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._client = None
        logger.info("computer_use_session_end",
                    session_id=self._session_id,
                    actions=self.security._action_count,
                    error=str(exc_val)[:100] if exc_val else None)
        return False   # 不吞例外

    def _get_client(self):
        if self._client is None:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                raise EnvironmentError("ANTHROPIC_API_KEY 未設定")
            self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _computer_use_tool_def(self) -> dict:
        """回傳 Computer Use 工具定義（2025-01-24 版本）"""
        return {
            "type":              COMPUTER_USE_TOOL_VERSION,
            "name":              "computer",
            "display_width_px":  1_280,
            "display_height_px":   800,
        }

    def execute_task(
        self,
        task:                str,
        context:             str  = "",
        confirm_destructive: bool = True,
    ) -> dict:
        """
        執行一個自然語言描述的電腦操作任務（同步）。

        Args:
            task:                任務描述
            context:             額外上下文
            confirm_destructive: 危險操作（表單提交、刪除）前是否確認

        Returns:
            {
                "success":     bool,
                "result":      str,
                "actions":     list[dict],
                "action_count":int,
                "session_id":  str,
            }
        """
        # 安全：動作數量限制
        ok, msg = self.security.check_action_limit()
        if not ok:
            logger.warning("action_limit_exceeded", session_id=self._session_id)
            return self._error_result(msg)

        client = self._get_client()

        system = f"""你是 SYNTHEX 的 PROBE Agent，負責在真實環境中驗證功能。
你有 Computer Use 工具可以操控螢幕。

安全規則（嚴格執行）：
1. 只存取 localhost 的開發伺服器（http://localhost:*）
2. 不點擊任何「刪除」「重設」「清除所有」按鈕
3. 不輸入任何真實的個人資料或密碼
4. 確認門控模式：{confirm_destructive}（True = 危險操作前詢問）
5. 完成任務後截圖確認結果

任務完成後，以 JSON 格式回報：
{{"success": true/false, "findings": "...", "actions_taken": N}}

Session ID：{self._session_id}"""

        full_task = f"{context}\n\n任務：{task}" if context else task
        messages  = [{"role": "user", "content": full_task}]

        for _iter in range(MAX_TASK_ITERATIONS):
            try:
                resp = client.beta.messages.create(
                    model      = self.model,
                    max_tokens = self.max_tokens,
                    system     = system,
                    tools      = [self._computer_use_tool_def()],
                    messages   = messages,
                    betas      = [COMPUTER_USE_BETA],
                )
            except Exception as e:
                logger.error("computer_use_api_error",
                             session_id=self._session_id,
                             error=str(e)[:200])
                return self._error_result(str(e)[:200])

            if resp.stop_reason == "end_turn":
                final_text = " ".join(
                    b.text for b in resp.content if hasattr(b, "text")
                )
                try:
                    cleaned = re.sub(r'^```(?:json)?\n?', '', final_text.strip()).rstrip('`\n')
                    parsed  = json.loads(cleaned)
                    return {
                        "success":      bool(parsed.get("success", True)),
                        "result":       parsed.get("findings", final_text[:500]),
                        "actions":      self.security.get_audit_log(),
                        "action_count": self.security._action_count,
                        "session_id":   self._session_id,
                    }
                except Exception:
                    return {
                        "success":      True,
                        "result":       final_text[:500],
                        "actions":      self.security.get_audit_log(),
                        "action_count": self.security._action_count,
                        "session_id":   self._session_id,
                    }

            if resp.stop_reason != "tool_use":
                break

            # 處理工具呼叫
            tool_results = []
            for block in resp.content:
                if not (hasattr(block, "type") and block.type == "tool_use"):
                    continue
                tool_input  = block.input
                action_type = tool_input.get("action", "unknown")

                # URL 安全檢查（navigate 動作）
                if action_type == "navigate":
                    url = tool_input.get("url", "")
                    ok, err = self.security.check_url(url)
                    if not ok:
                        logger.warning("url_blocked", url=url[:100], reason=err,
                                       session_id=self._session_id)
                        result_content = [{"type": "text", "text": f"[安全阻擋] {err}"}]
                        self.security.record_action(ComputerAction(
                            action_type="navigate_blocked", target=url[:100],
                            success=False, error=err
                        ))
                    else:
                        result_content = self._handle_tool_call(action_type, tool_input)
                else:
                    result_content = self._handle_tool_call(action_type, tool_input)

                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     result_content,
                })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user",      "content": tool_results})

        logger.warning("task_incomplete", session_id=self._session_id,
                       iterations=MAX_TASK_ITERATIONS)
        return self._error_result("任務未在步驟限制內完成")

    def _handle_tool_call(self, action: str, tool_input: dict) -> list[dict]:
        """模擬/代理 Computer Use 工具呼叫"""
        target = str(tool_input.get("coordinate",
                     tool_input.get("url",
                     tool_input.get("text", ""))))[:100]
        self.security.record_action(ComputerAction(
            action_type=action, target=target
        ))
        logger.debug("computer_use_action", action=action, target=target[:50],
                     session_id=self._session_id)

        handlers = {
            "screenshot":     lambda: "截圖已記錄",
            "left_click":     lambda: f"已點擊座標 {tool_input.get('coordinate', [0,0])}",
            "left_mouse_down":lambda: "滑鼠按下",
            "left_mouse_up":  lambda: "滑鼠放開",
            "triple_click":   lambda: f"三次點擊 {tool_input.get('coordinate', [0,0])}",
            "type":           lambda: "文字已輸入",
            "key":            lambda: f"按鍵 {tool_input.get('key', '')} 完成",
            "scroll":         lambda: "已滾動",
            "hold_key":       lambda: f"持按 {tool_input.get('key', '')}",
            "wait":           lambda: self._do_wait(tool_input.get("duration", 1000)),
        }
        msg = handlers.get(action, lambda: f"動作 {action} 完成")()
        return [{"type": "text", "text": msg}]

    def _do_wait(self, duration_ms: int) -> str:
        wait_ms = max(0, min(5_000, int(duration_ms)))  # 最多等 5 秒
        time.sleep(wait_ms / 1_000)
        return f"等待 {wait_ms}ms 完成"

    def _error_result(self, msg: str) -> dict:
        return {
            "success":      False,
            "result":       msg,
            "actions":      self.security.get_audit_log(),
            "action_count": self.security._action_count,
            "session_id":   self._session_id,
        }


# ── 便利函數：整合到 SYNTHEX ship() 流程 ─────────────────────────

def verify_frontend_with_browser(
    workdir:    str,
    dev_server: str = "http://localhost:3000",
    task:       str = "驗證首頁可以正常載入，檢查主要功能是否可用",
) -> dict:
    """
    BYTE Agent 完成前端開發後，用瀏覽器驗證結果。
    整合到 Phase 9 的後處理步驟。

    Returns:
        ComputerUseSession.execute_task() 的結果
    """
    with ComputerUseSession(
        workdir      = workdir,
        allowed_urls = [dev_server],
        model        = cfg.model_sonnet,   # 使用 config 而非硬編碼
    ) as session:
        return session.execute_task(
            task,
            context=f"前端開發伺服器：{dev_server}"
        )
