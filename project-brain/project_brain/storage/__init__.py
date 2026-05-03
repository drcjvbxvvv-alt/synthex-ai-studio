"""
project_brain/storage/ — 資料存取層

H-01 架構拆分：從 brain_db.py 2850 行提取出 WriteContext + Repository 層。

  WriteContext: 共享的寫入基礎設施（conn, lock, execute_write, write_guard）
  repositories/: 各領域的 SQL 操作（NodeRepo, SearchRepo, AnalyticsRepo 等）

BrainDB 保留為 facade，委派到 repositories，外部 API 不變。
"""
from .write_context import WriteContext

__all__ = ["WriteContext"]
