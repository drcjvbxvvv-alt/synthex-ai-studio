"""project_brain/interfaces/cli_ingest.py — E-04: brain ingest CLI command

Usage:
  brain ingest files --path ./docs [--glob "**/*.md"] [--dry-run]
  brain ingest github --repo org/repo --token $GH_TOKEN [--dry-run]
"""
from __future__ import annotations

import os
from pathlib import Path

from project_brain.interfaces.cli_utils import (
    R, B, D, G, Y, C, GR,
    _workdir, _ok, _err, _info,
)


def cmd_ingest(args):
    """知識匯入 Pipeline。"""
    wd = _workdir(args)
    brain_dir = Path(wd) / ".brain"
    if not brain_dir.exists():
        _err(f"Brain 尚未初始化，請先執行：brain init --workdir {wd}")
        return

    ingest_sub = getattr(args, "ingest_sub", "")
    if not ingest_sub:
        _err("缺少子命令。用法：brain ingest files --path <dir> 或 brain ingest github --repo <repo>")
        return

    dry_run = getattr(args, "dry_run", False)

    # Initialize brain
    from project_brain.engine import ProjectBrain
    brain = ProjectBrain(wd)

    # Try to get LLM client for extraction
    llm_client = None
    try:
        from project_brain.brain_config import load_config
        from project_brain.integrations.llm_client import from_brain_config
        llm_client = from_brain_config("pipeline", brain_dir)
        # Test if it's a NoopLLMClient
        if type(llm_client).__name__ == "NoopLLMClient":
            llm_client = None
    except Exception:
        pass

    from project_brain.integrations.ingest.pipeline import IngestPipeline
    pipeline = IngestPipeline(brain, llm_client=llm_client)

    if ingest_sub == "files":
        _ingest_files(args, pipeline, dry_run)
    elif ingest_sub == "github":
        _ingest_github(args, pipeline, dry_run)
    else:
        _err(f"未知子命令：{ingest_sub}")


def _ingest_files(args, pipeline, dry_run: bool):
    """Handle brain ingest files."""
    path = getattr(args, "path", None)
    if not path:
        _err("缺少 --path 參數。用法：brain ingest files --path <dir>")
        return

    glob_pattern = getattr(args, "glob", "**/*.md")
    path = Path(path)
    if not path.exists():
        _err(f"路徑不存在：{path}")
        return

    print(f"\n  {B}{C}📄 Brain Ingest: Local Files{R}")
    print(f"  {D}Path:    {path}{R}")
    print(f"  {D}Pattern: {glob_pattern}{R}")
    print(f"  {D}Dry-run: {dry_run}{R}")
    if pipeline._llm:
        print(f"  {D}LLM:     {type(pipeline._llm).__name__}{R}")
    else:
        print(f"  {D}LLM:     none (heuristic mode){R}")
    print()

    from project_brain.integrations.ingest.files import LocalFilesIngestSource
    source = LocalFilesIngestSource()
    docs = source.fetch(path, glob_pattern=glob_pattern)

    if not docs:
        _info("未找到任何文件")
        return

    print(f"  {D}掃描到 {len(docs)} 個文件段落{R}")
    result = pipeline.run(docs, dry_run=dry_run, source_label="ingest:files")
    _print_result(result, dry_run)


def _ingest_github(args, pipeline, dry_run: bool):
    """Handle brain ingest github."""
    repo = getattr(args, "repo", None)
    if not repo:
        _err("缺少 --repo 參數。用法：brain ingest github --repo owner/repo --token $TOKEN")
        return

    token = getattr(args, "token", "") or os.environ.get("GITHUB_TOKEN", "")
    types = (getattr(args, "types", "issues") or "issues").split(",")

    print(f"\n  {B}{C}🐙 Brain Ingest: GitHub{R}")
    print(f"  {D}Repo:    {repo}{R}")
    print(f"  {D}Types:   {', '.join(types)}{R}")
    print(f"  {D}Token:   {'***' + token[-4:] if len(token) > 4 else '(none)'}{R}")
    print(f"  {D}Dry-run: {dry_run}{R}")
    print()

    from project_brain.integrations.ingest.github import GitHubIngestSource
    source = GitHubIngestSource()
    docs = source.fetch(repo, token=token, types=types)

    if not docs:
        _info("未取得任何 issues/PRs")
        return

    print(f"  {D}取得 {len(docs)} 個 issues/PRs{R}")
    result = pipeline.run(docs, dry_run=dry_run, source_label=f"ingest:github:{repo}")
    _print_result(result, dry_run)


def _print_result(result, dry_run: bool):
    """Print ingestion result summary."""
    from project_brain.interfaces.cli_utils import R, G, Y, D

    if dry_run:
        print(f"\n  {Y}[DRY-RUN] 以下為預覽，未實際寫入：{R}")
    print(f"\n  {G}Ingestion 完成{R}")
    print(f"  {D}文件掃描：{result.documents_scanned}{R}")
    print(f"  {D}候選提取：{result.candidates_extracted}{R}")
    print(f"  {D}重複跳過：{result.duplicates_skipped}{R}")
    if not dry_run:
        print(f"  {D}寫入 L3： {result.written_to_l3}{R}")
        print(f"  {D}進入 Staging：{result.written_to_staging}{R}")
    if result.errors:
        print(f"  {Y}錯誤：{len(result.errors)}{R}")
        for e in result.errors[:5]:
            print(f"    {D}{e}{R}")
