"""
project_brain/constants.py — REF-04: 全域共用常數

所有魔法數字的唯一來源。修改此檔案即可同步影響所有引用點。
"""

# ── 衰減（Decay） ─────────────────────────────────────────────
# 日衰減率：約 1 年後信心降至 0.33（Ebbinghaus 遺忘曲線）
# 同步至：brain_db._effective_confidence(), decay_engine._factor_time()
BASE_DECAY_RATE = 0.003

# ── Context 組裝（ContextEngineer） ──────────────────────────
# _fmt_node() 中 content 顯示的最大字元數
ADR_CONTENT_CAP  = 800   # ADR 類型節點（架構決策記錄，內容較長）
NODE_CONTENT_CAP = 400   # 一般節點（Pitfall / Rule / Decision 等）

# ── 搜尋（Search） ────────────────────────────────────────────
# search_nodes / search_nodes_multi / graph.search_nodes 的預設回傳數量
DEFAULT_SEARCH_LIMIT = 8
