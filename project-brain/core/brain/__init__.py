"""
core/brain — 向後相容 shim（v9.3）

此目錄已廢棄，實際程式碼在 project_brain/。
保留以避免破壞使用 'from core.brain.X import Y' 的舊程式碼。
"""
# 透明轉發所有 import 到 project_brain
from project_brain import *  # noqa
from project_brain import Brain, ProjectBrain, KnowledgeGraph
