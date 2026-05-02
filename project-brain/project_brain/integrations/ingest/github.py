"""
project_brain/integrations/ingest/github.py — E-04: GitHub Ingestion Source

Fetches issues (and optionally PRs) from a GitHub repository via the REST API
and produces RawDocument objects for the IngestPipeline.

Uses only stdlib (urllib.request) — no external dependencies.

Usage::

    source = GitHubIngestSource()
    docs = source.fetch("owner/repo", token="ghp_xxx", types=["issues"])
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from .base import RawDocument

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"
_DEFAULT_TIMEOUT = 15


class GitHubIngestSource:
    """Fetch GitHub issues/PRs and produce RawDocuments."""

    def fetch(
        self,
        repo: str,
        token: str = "",
        types: list[str] | None = None,
        state: str = "closed",
        per_page: int = 50,
        max_pages: int = 3,
    ) -> list[RawDocument]:
        """Fetch issues and/or PRs from a GitHub repository.

        Args:
            repo: Repository in "owner/repo" format.
            token: GitHub personal access token (or empty for public repos).
            types: List of types to fetch: ["issues", "prs"]. Default: ["issues"].
            state: Issue/PR state filter: "closed", "open", "all".
            per_page: Items per page (max 100).
            max_pages: Maximum pages to fetch (rate limit protection).

        Returns:
            List of RawDocuments, one per issue/PR.
        """
        types = types or ["issues"]
        per_page = min(per_page, 100)
        docs: list[RawDocument] = []

        if "issues" in types:
            docs.extend(self._fetch_issues(repo, token, state, per_page, max_pages))
        if "prs" in types:
            docs.extend(self._fetch_prs(repo, token, state, per_page, max_pages))

        logger.info("GitHubIngestSource: fetched %d documents from %s", len(docs), repo)
        return docs

    def _fetch_issues(self, repo: str, token: str, state: str,
                      per_page: int, max_pages: int) -> list[RawDocument]:
        """Fetch issues (excluding PRs) from the repository."""
        docs: list[RawDocument] = []

        for page in range(1, max_pages + 1):
            url = (f"{_API_BASE}/repos/{repo}/issues"
                   f"?state={state}&per_page={per_page}&page={page}")
            items = self._get_json(url, token)
            if not items:
                break

            for item in items:
                # Skip pull requests (they appear in /issues endpoint too)
                if "pull_request" in item:
                    continue
                docs.append(self._issue_to_doc(repo, item))

            if len(items) < per_page:
                break  # last page

        return docs

    def _fetch_prs(self, repo: str, token: str, state: str,
                   per_page: int, max_pages: int) -> list[RawDocument]:
        """Fetch pull requests from the repository."""
        docs: list[RawDocument] = []

        for page in range(1, max_pages + 1):
            url = (f"{_API_BASE}/repos/{repo}/pulls"
                   f"?state={state}&per_page={per_page}&page={page}")
            items = self._get_json(url, token)
            if not items:
                break

            for item in items:
                docs.append(self._pr_to_doc(repo, item))

            if len(items) < per_page:
                break

        return docs

    def _issue_to_doc(self, repo: str, issue: dict) -> RawDocument:
        """Convert a GitHub issue JSON to a RawDocument."""
        number = issue.get("number", 0)
        title = issue.get("title", "")
        body = issue.get("body", "") or ""
        labels = [lb.get("name", "") for lb in issue.get("labels", [])]
        state = issue.get("state", "")

        # Kind hint from labels
        kind_hint = "Note"
        label_lower = {lb.lower() for lb in labels}
        if label_lower & {"bug", "defect", "incident"}:
            kind_hint = "Pitfall"
        elif label_lower & {"decision", "rfc", "proposal", "adr"}:
            kind_hint = "Decision"
        elif label_lower & {"rule", "convention", "standard"}:
            kind_hint = "Rule"

        return RawDocument(
            source=f"github:{repo}#issue-{number}",
            title=title,
            content=body[:4000],  # truncate very long bodies
            url=issue.get("html_url", f"https://github.com/{repo}/issues/{number}"),
            metadata={
                "issue_number": number,
                "labels": labels,
                "state": state,
                "kind_hint": kind_hint,
                "comments": issue.get("comments", 0),
                "created_at": issue.get("created_at", ""),
                "closed_at": issue.get("closed_at", ""),
            },
        )

    def _pr_to_doc(self, repo: str, pr: dict) -> RawDocument:
        """Convert a GitHub PR JSON to a RawDocument."""
        number = pr.get("number", 0)
        title = pr.get("title", "")
        body = pr.get("body", "") or ""
        labels = [lb.get("name", "") for lb in pr.get("labels", [])]

        return RawDocument(
            source=f"github:{repo}#pr-{number}",
            title=title,
            content=body[:4000],
            url=pr.get("html_url", f"https://github.com/{repo}/pull/{number}"),
            metadata={
                "pr_number": number,
                "labels": labels,
                "state": pr.get("state", ""),
                "kind_hint": "Decision",  # PRs are typically architectural decisions
                "merged": pr.get("merged_at") is not None,
                "created_at": pr.get("created_at", ""),
            },
        )

    @staticmethod
    def _get_json(url: str, token: str) -> list[dict]:
        """GET a GitHub API URL and return parsed JSON."""
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "project-brain-ingest/0.51.0",
            })
            if token:
                req.add_header("Authorization", f"token {token}")

            with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            logger.warning("GitHub API %d: %s (url=%s)", e.code, e.reason, url)
            return []
        except Exception as e:
            logger.warning("GitHub API request failed: %s", e)
            return []
