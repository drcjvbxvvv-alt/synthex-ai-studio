"""
project_brain.interfaces — 外部介面（ARCHITECTURE_REVIEW.md §6.2）

包含所有對外暴露介面：
    cli.py          brain CLI 入口 + 子命令分派
    cli_*.py        CLI 子命令模組
    mcp_server.py   Model Context Protocol 伺服器
    api_server.py   REST API 伺服器
    web_ui/         Web UI 靜態檔 + Flask server

本 __init__ 刻意保持空白以避免任何 side-effect 載入。
"""
