"""
core/brain — Thin integration adapter (DO NOT add business logic here)

This package is a re-export shim over project_brain/.
All business logic lives exclusively in project_brain/.
core/ exists only for Synthex integration (config, model selection, orchestration).

Rules:
  - Never duplicate logic from project_brain/ here.
  - To change behaviour, edit project_brain/ only.
  - Add new modules here ONLY when they are Synthex-specific orchestration.
"""
# Transparent re-export — keeps backward compat for `from core.brain.X import Y`
from project_brain import *  # noqa
from project_brain import Brain, ProjectBrain, KnowledgeGraph
