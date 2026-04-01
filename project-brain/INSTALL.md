# Project Brain — 安裝指南

## 安裝

```bash
pip install project-brain
brain --help
```

## 初始化

```bash
cd /your/project
brain setup
```

完成後：
- 建立 `.brain/brain.db`
- 安裝 git post-commit hook
- 輸出 MCP 設定範例

## 驗證

```bash
brain add "第一條規則"
brain ask "規則"      # 應該找到剛加入的
brain status          # 查看記憶庫狀態
```

## git hook 驗證

```bash
git commit -m "test: verify Brain hook works"
brain status          # L2 情節記憶應增加
```

## MCP 設定（Claude Code）

```json
{
  "mcpServers": {
    "project-brain": {
      "command": "python",
      "args": ["-m", "project_brain.mcp_server"],
      "env": {"BRAIN_WORKDIR": "/your/project"}
    }
  }
}
```

## 環境變數

| 變數 | 說明 |
|------|------|
| `BRAIN_WORKDIR` | 預設專案目錄（省略 --workdir）|
| `ANTHROPIC_API_KEY` | AI 功能（可選）|
| `BRAIN_SYNTHESIZE=1` | 記憶融合模式（opt-in）|
| `BRAIN_LLM_PROVIDER` | `anthropic`（預設）或 `openai`（Ollama）|

## 本地 LLM（Ollama）

```bash
export BRAIN_LLM_PROVIDER=openai
export BRAIN_LLM_BASE_URL=http://localhost:11434/v1
export BRAIN_LLM_MODEL=llama3.2:3b
```

## 多專案

無需設定。`brain` 自動從當前目錄往上找 `.brain/`。
