"""
project_brain.engines — 處理引擎（ARCHITECTURE_REVIEW.md §6.2）

包含所有主要的知識處理引擎：
    context.py            ContextEngineer — context 組裝
    nudge_engine.py       NudgeEngine — 主動警告
    decay_engine.py       DecayEngine — 信心衰減
    review_board.py       KnowledgeReviewBoard — KRB 審查
    memory_synthesizer.py MemorySynthesizer — cross-layer 合成
    conflict_resolver.py  ConflictResolver — 知識衝突解析
    knowledge_validator.py KnowledgeValidator — 節點驗證

本 __init__ 刻意保持空白以避免任何 side-effect 載入。
"""
