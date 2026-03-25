## [v1.1.0] - 2026-03-25

### 🚀 Project Brain v1.1 — 四大子系統與安全性全面升級

本次更新實作了 Project Brain 路線圖中的四大核心子系統，大幅強化語義搜尋、時序推理能力，並提供 Claude Code 與 VS Code 的深度整合。所有子系統皆導入嚴格的安全防護與邊界限制。

#### 🧠 核心子系統與整合

- **1. VectorMemory 語義記憶 (`core/brain/vector_memory.py`)**
  - **功能：** 導入 Chroma 1.5.5 向量記憶，使 Context 搜尋從「關鍵字完全匹配」升級為「語義理解」（例如搜尋「支付 bug」能精準命中「Stripe Webhook 觸發異常」的踩坑記錄）。若 Chroma 不可用，系統會自動降級到 FTS5 而不拋出例外。
  - **安全防護：** 實作路徑遍歷防護（`vector_dir` 嚴格限制於 `.brain/` 內）、控制字元清理、輸入長度上限 8,000 字元、集合上限 50,000 筆（約 200MB），並預設關閉匿名遙測。

- **2. TemporalGraph 時序知識圖譜 (`core/brain/temporal_graph.py`)**
  - **功能：** 實作受 Graphiti 啟發的時序知識圖譜。每條關係邊帶有 `valid_from`、`confidence` 和衰減率 `λ`。信心值公式為：$c(t) = c_0 \times e^{-\lambda \times \text{days}}$。
  - **權重與覆蓋：** 因果關係（`CAUSED_BY`、`SOLVED_BY`）的 $\lambda=0.001$ 幾乎不衰減，確保舊踩坑記錄持續有效；引用關係 $\lambda=0.01$ 衰減較快。矛盾知識不刪除，透過標記 `superseded_by` 保留歷史可審計性。
  - **安全防護：** 全面使用 SQL 參數化查詢防止注入，且時間戳嚴格驗證 ISO 8601 格式。

- **3. MCP Server 協議支援 (`core/brain/mcp_server.py`)**
  - **功能：** 讓 Claude Code 能直接透過 MCP 協議呼叫 Project Brain，無須透過命令列。提供 5 個 Tool（`get_context`、`search_knowledge`、`impact_analysis`、`add_knowledge`、`brain_status`）與 1 個 Resource（`brain://graph/mermaid`）。
  - **安全防護：** 實作滑動視窗 Rate Limiting（60 RPM）、每個參數獨立的型別與長度驗證、啟動時檢查 `workdir` 必須存在 `.brain/` 目錄，並在錯誤訊息中遮蔽系統絕對路徑。
  - **配置方式：** 將以下設定加入 Claude Code 的 `~/.claude.json`：
    ```json
    {
      "mcpServers": {
        "project-brain": {
          "command": "python",
          "args": ["-m", "core.brain.mcp_server"],
          "env": { "BRAIN_WORKDIR": "/your/project" }
        }
      }
    }
    ```

- **4. VS Code Extension 編輯器擴充 (`vscode-extension/`)**
  - **功能：** 在編輯器側欄即時顯示與當前程式碼相關的歷史知識，並支援切換檔案時的 Debounce 自動更新。
  - **安全防護：** 子進程呼叫嚴格使用 `argv` 陣列（不使用 shell string）杜絕指令注入；使用者輸入長度限制 200 字元；`stdout` 緩衝上限設為 50KB 防止記憶體洩漏；每個命令強制 10 秒 timeout；並在 `deactivate()` 時安全釋放所有 EventEmitter 和 Timer。
  - **編譯安裝：**
    ```bash
    cd vscode-extension
    npm install
    npm run compile
    # 在 VS Code 按 F5 啟動開發模式
    ```
