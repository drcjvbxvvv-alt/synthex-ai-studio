"""
project_brain.core — 核心不變數據層（ARCHITECTURE_REVIEW.md §6.2）

包含專案的唯一真相源：
    brain_db.py      BrainDB + SCHEMA_VERSION
    session_store.py L1a SessionStore
    constants.py     全域共用常數（monkey-patch friendly）

本 __init__ 刻意保持空白以避免任何 side-effect 載入，
使用者請透過 ``project_brain.core.brain_db`` 等子模組路徑存取。
"""
