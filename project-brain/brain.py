#!/usr/bin/env python3
"""brain — Project Brain CLI 入口（包裝器）。

安裝為全域命令：pip install -e .  →  brain <cmd>
本地使用：      python brain.py <cmd>
"""
from project_brain.cli import main

if __name__ == "__main__":
    main()
