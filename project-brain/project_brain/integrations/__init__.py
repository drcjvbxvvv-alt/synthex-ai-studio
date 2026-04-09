"""
project_brain.integrations — 外部整合（ARCHITECTURE_REVIEW.md §6.2）

包含與外部系統整合的模組：
    federation.py       跨專案 Brain 聯邦同步
    graphiti_adapter.py Graphiti 時序圖資料庫轉接層

（6.2 規劃的 llm_client.py 統一 LLM 介面為新功能，
不在本次重構範圍。）

本 __init__ 刻意保持空白以避免任何 side-effect 載入。
"""
