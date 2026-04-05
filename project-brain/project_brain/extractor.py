"""
KnowledgeExtractor — AI 驅動的知識提取引擎

從以下來源自動提取結構化知識：
- Git commits（決策、踩坑）
- 程式碼本身（業務規則、架構模式）
- TODO/FIXME 注釋（技術債）
- 函數名稱和模組結構（依賴關係）
"""
import os
import re
import json
import hashlib
import subprocess
from pathlib import Path
from typing import Optional
import anthropic

try:
    from core.config import cfg, ModelID
    _DEFAULT_MODEL = cfg.model_sonnet
except ImportError:
    _DEFAULT_MODEL = "claude-sonnet-4-6"  # fallback


EXTRACTION_PROMPT = """
你是一個專業的程式碼考古學家。從以下的程式碼變更或程式碼片段中提取有價值的知識。

提取規則：
1. 只提取真正有價值的知識，不要提取顯而易見的東西
2. 特別關注：「為什麼這樣做」而不是「做了什麼」
3. 標記踩過的坑（包含解決方案）
4. 識別業務規則（必須遵守的約束）
5. 找出架構決策（選擇 A 而不是 B 的理由）

如果沒有有價值的知識，knowledge_chunks 回傳空陣列即可。
"""

# AUTO-03: Structured output tool for Anthropic provider.
# Using tool_use eliminates json.loads() fragility from LLM preamble text.
_EXTRACT_TOOL: dict = {
    "name": "store_knowledge",
    "description": "Store extracted knowledge chunks from code analysis",
    "input_schema": {
        "type": "object",
        "properties": {
            "knowledge_chunks": {
                "type": "array",
                "description": "Extracted knowledge items. Empty array if nothing valuable found.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type":       {"type": "string", "enum": ["Decision", "Pitfall", "Rule", "Architecture"]},
                        "title":      {"type": "string", "description": "Short title < 60 chars"},
                        "content":    {"type": "string", "description": "Detailed explanation with background, reason, impact"},
                        "tags":       {"type": "array", "items": {"type": "string"}},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    },
                    "required": ["type", "title", "content", "confidence"],
                },
                "maxItems": 8,
            },
            "components_mentioned": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Component or service names mentioned",
            },
            "dependencies_detected": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "from":   {"type": "string"},
                        "to":     {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["from", "to", "reason"],
                },
            },
        },
        "required": ["knowledge_chunks", "components_mentioned", "dependencies_detected"],
    },
}


class KnowledgeExtractor:
    """
    AI 驅動的知識提取器

    支援多種 LLM 後端（透過環境變數設定）：
      BRAIN_LLM_PROVIDER=anthropic  → Claude（預設，需要 ANTHROPIC_API_KEY）
      BRAIN_LLM_PROVIDER=openai     → 任何 OpenAI 相容 API（包括 Ollama、LM Studio）
        BRAIN_LLM_BASE_URL=http://localhost:11434/v1  → Ollama
        BRAIN_LLM_BASE_URL=http://localhost:1234/v1   → LM Studio
        BRAIN_LLM_MODEL=llama3.1:8b                  → 本地模型名稱
    """

    def __init__(self, workdir: str):
        self.workdir  = Path(workdir)
        self.provider = os.environ.get("BRAIN_LLM_PROVIDER", "anthropic").lower()
        self.model    = os.environ.get("BRAIN_LLM_MODEL", _DEFAULT_MODEL)

        if self.provider == "openai":
            # OpenAI 相容（Ollama、LM Studio、本地 API）
            from openai import OpenAI
            base_url = os.environ.get("BRAIN_LLM_BASE_URL", "http://localhost:11434/v1")
            api_key  = os.environ.get("OPENAI_API_KEY", "ollama")  # Ollama 不需要真實 key
            self.client = OpenAI(base_url=base_url, api_key=api_key)
        else:
            # Anthropic（預設）
            self.client = anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY")
            )

    def _call(self, content: str, max_tokens: int = 1000) -> dict:
        """呼叫 LLM API 提取知識（支援 Anthropic / OpenAI 相容格式）

        AUTO-03: Anthropic provider uses tool_use for structured output,
        eliminating json.loads() fragility from LLM preamble text.
        OpenAI-compatible provider (Ollama/LM Studio) keeps json.loads()
        as tool_use support is inconsistent across local models.
        """
        prompt = EXTRACTION_PROMPT + "\n\n---\n\n" + content[:4000]
        _empty = {"knowledge_chunks": [], "components_mentioned": [],
                  "dependencies_detected": []}
        try:
            if self.provider == "openai":
                # OpenAI 相容格式（Ollama、LM Studio）— keep json.loads() path
                resp = self.client.chat.completions.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}]
                )
                text = resp.choices[0].message.content or ""
                text = re.sub(r"```json\n?", "", text)
                text = re.sub(r"```\n?",     "", text)
                return json.loads(text.strip())
            else:
                # AUTO-03: Anthropic — tool_use guarantees structured output
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    tools=[_EXTRACT_TOOL],
                    tool_choice={"type": "tool", "name": "store_knowledge"},
                    messages=[{"role": "user", "content": prompt}]
                )
                tool_block = next(
                    (b for b in resp.content if b.type == "tool_use"), None
                )
                if tool_block is None:
                    return _empty
                return tool_block.input  # already a dict, no json.loads needed
        except Exception as e:
            return {**_empty, "_error": str(e)}

    def from_git_commit(self, commit_hash: str, commit_msg: str, diff: str) -> dict:
        """從 git commit 提取知識"""
        content = f"""
Git Commit: {commit_hash[:8]}
Message: {commit_msg}

Code Diff:
{diff[:8000]}
"""
        result = self._call(content)
        # 加入來源資訊
        for chunk in result.get("knowledge_chunks", []):
            chunk["source"]     = f"git:{commit_hash[:8]}"
            chunk["source_url"] = f"commit/{commit_hash}"
        return result

    def from_file(self, file_path: str, content: str) -> dict:
        """從程式碼檔案提取知識"""
        ext  = Path(file_path).suffix
        text = f"""
File: {file_path}

```{ext[1:] if ext else 'code'}
{content[:3000]}
```
"""
        result = self._call(text)
        for chunk in result.get("knowledge_chunks", []):
            chunk["source"]     = f"file:{file_path}"
            chunk["source_url"] = file_path
        return result

    def from_comments(self, file_path: str, content: str) -> dict:
        """專門提取 TODO/FIXME/HACK/NOTE 注釋"""
        lines    = content.split("\n")
        comments = []
        patterns = [
            (r"TODO[:：\s](.+)",  "TODO"),
            (r"FIXME[:：\s](.+)", "FIXME"),
            (r"HACK[:：\s](.+)",  "HACK"),
            (r"NOTE[:：\s](.+)",  "NOTE"),
            (r"XXX[:：\s](.+)",   "XXX"),
            (r"WARN[:：\s](.+)",  "WARN"),
        ]
        for i, line in enumerate(lines, 1):
            for pattern, tag in patterns:
                m = re.search(pattern, line, re.IGNORECASE)
                if m:
                    comments.append(f"[{tag}] 第{i}行: {m.group(1).strip()}")

        if not comments:
            return {"knowledge_chunks": [], "components_mentioned": [],
                    "dependencies_detected": []}

        text = f"""
File: {file_path}
Comments found:
{chr(10).join(comments)}
"""
        return self._call(text, max_tokens=500)

    def from_git_history(self, limit: int = 100) -> list:
        """
        從完整的 git 歷史提取知識
        用於舊專案的考古掃描
        """
        results = []
        try:
            # 取得 git log
            log_output = subprocess.check_output(
                ["git", "log", f"--max-count={limit}",
                 "--pretty=format:%H|%ae|%ai|%s", "--diff-filter=M"],
                cwd=str(self.workdir),
                stderr=subprocess.DEVNULL,
                text=True,
            )

            for line in log_output.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 3)
                if len(parts) < 4:
                    continue
                commit_hash, author, date, message = parts

                # 跳過不含決策資訊的 commit
                skip_patterns = [
                    r"^(Merge|bump|version|release|format|lint|style|typo)",
                    r"^\d+\.\d+",  # 版本號
                ]
                if any(re.match(p, message, re.IGNORECASE) for p in skip_patterns):
                    continue

                # 取得 diff
                try:
                    diff = subprocess.check_output(
                        ["git", "show", "--stat", "--diff-filter=M",
                         "--unified=3", commit_hash],
                        cwd=str(self.workdir),
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )[:2000]
                except Exception:
                    diff = ""

                extracted = self.from_git_commit(commit_hash, message, diff)
                extracted["_meta"] = {
                    "commit": commit_hash,
                    "author": author,
                    "date":   date,
                }
                if extracted.get("knowledge_chunks"):
                    results.append(extracted)

        except (subprocess.CalledProcessError, FileNotFoundError):
            pass  # 不是 git repo，跳過

        return results

    def from_adr_files(self, adr_dir: Path) -> list:
        """讀取現有的 ADR 文件"""
        results = []
        if not adr_dir.exists():
            return results

        for path in sorted(adr_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8", errors="ignore")
            chunk = {
                "type":       "ADR",
                "title":      path.stem,
                "content":    content,
                "tags":       ["adr", "architecture-decision"],
                "confidence": 1.0,
                "source":     f"adr:{path.name}",
                "source_url": str(path),
            }
            results.append({
                "knowledge_chunks":     [chunk],
                "components_mentioned": self._extract_components_from_text(content),
                "dependencies_detected":[],
            })
        return results

    def _extract_components_from_text(self, text: str) -> list:
        """簡單的組件名稱提取（PascalCase 和常見術語）"""
        components = set()
        # PascalCase 名稱（可能是類別或服務名稱）
        for m in re.finditer(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b', text):
            components.add(m.group())
        # 常見架構組件關鍵字
        for m in re.finditer(r'\b(?:Service|Repository|Controller|Handler|'
                             r'Manager|Gateway|Adapter|Factory|Store)\b', text):
            # 取前後文
            start = max(0, m.start() - 20)
            ctx   = text[start:m.end()]
            word  = re.search(r'(\w+)' + m.group(), ctx)
            if word:
                components.add(word.group())
        return list(components)[:10]

    def extract_from_text(self, text: str, prompt_hint: str = '', source: str = 'text') -> list:
        """從任意文字提煉結構化知識節點（v8.0，供 MemoryConsolidator 呼叫）."""
        if not text or len(text.strip()) < 50:
            return []
        hint = prompt_hint or '提煉工程決策、踩坑、規則。排除臨時筆記和一次性資訊。'
        prompt = (
            '你是工程知識提煉專家，分析以下文字，提取值得長期保留的知識。\n\n'
            + hint + '\n\n文字：\n' + text[:3000] + '\n\n'
            '以 JSON 回覆：{"knowledge":[{"title":"標題","content":"內容","type":"Pitfall|Decision|Rule","confidence":0.8}]}\n'
            '最多 8 條，confidence<0.5 不輸出。'
        )
        try:
            result = self._call(prompt, max_tokens=2000)
            import json, re as _re
            raw = _re.sub(r'```(?:json)?\n?|```', '', result.get('content', '')).strip()
            items = json.loads(raw).get('knowledge', [])
            return [
                {'title': i.get('title','')[:60], 'content': i.get('content',''),
                 'type': i.get('type','Rule'), 'confidence': float(i.get('confidence',0.7)),
                 'source': source}
                for i in items if i.get('title') and i.get('content')
                and float(i.get('confidence', 0)) >= 0.5
            ][:10]
        except Exception as e:
            import logging; logging.getLogger(__name__).warning('extract_from_text: %s', e)
            return []

    def from_session_log(
        self,
        task_description: str,
        decisions: list,
        lessons: list,
        pitfalls: list,
        source: str = "session",
    ) -> dict:
        """PH1-04: Session-aware extraction — convert structured complete_task data
        directly to knowledge chunks WITHOUT an LLM call.

        This captures "process knowledge" (what happened during a work session)
        rather than relying solely on commit messages. Called by complete_task MCP tool.

        Args:
            task_description: One-sentence summary of what was done.
            decisions:        List of architectural/design choices made.
            lessons:          List of things learned that help future work.
            pitfalls:         List of mistakes encountered or near-misses.
            source:           Source tag for the chunks (default: 'session').

        Returns:
            Same dict format as other from_* methods:
            {"knowledge_chunks": [...], "components_mentioned": [], "dependencies_detected": []}
        """
        chunks = []
        ts = source  # e.g. "session" or "session:2026-04-03"

        def _title(text: str, max_len: int = 60) -> str:
            """Extract first sentence instead of truncating mid-word."""
            sentence = re.split(r'[。.！!？?\n]', text.strip())[0]
            return sentence[:max_len].strip()

        for decision in decisions:
            if not decision or not decision.strip():
                continue
            chunks.append({
                "type":       "Decision",
                "title":      _title(decision),
                "content":    f"Task: {task_description}\nDecision: {decision.strip()}",
                "tags":       ["session", "decision"],
                "confidence": 0.85,
                "source":     ts,
            })

        for lesson in lessons:
            if not lesson or not lesson.strip():
                continue
            chunks.append({
                "type":       "Rule",
                "title":      _title(lesson),
                "content":    f"Task: {task_description}\nLesson: {lesson.strip()}",
                "tags":       ["session", "lesson"],
                "confidence": 0.80,
                "source":     ts,
            })

        for pitfall in pitfalls:
            if not pitfall or not pitfall.strip():
                continue
            chunks.append({
                "type":       "Pitfall",
                "title":      _title(pitfall),
                "content":    f"Task: {task_description}\nPitfall: {pitfall.strip()}",
                "tags":       ["session", "pitfall"],
                "confidence": 0.90,  # pitfalls are high-confidence: they actually happened
                "source":     ts,
            })

        return {
            "knowledge_chunks":       chunks,
            "components_mentioned":   [],
            "dependencies_detected":  [],
        }

    def from_git_diff_staged(self) -> dict:
        """PH1-04: Extract knowledge from staged (uncommitted) git diff.

        Captures in-progress decisions before they are committed, closing the
        gap between 'work in progress' and 'commit message only' extraction.
        Requires ANTHROPIC_API_KEY or OpenAI-compatible LLM.
        """
        try:
            diff = subprocess.check_output(
                ["git", "diff", "--cached", "--stat", "--unified=3"],
                cwd=str(self.workdir),
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            return {"knowledge_chunks": [], "components_mentioned": [],
                    "dependencies_detected": [], "_error": "git diff --cached failed"}

        if not diff.strip():
            return {"knowledge_chunks": [], "components_mentioned": [],
                    "dependencies_detected": []}

        content = f"Staged (uncommitted) git diff:\n{diff[:6000]}"
        result = self._call(content)
        for chunk in result.get("knowledge_chunks", []):
            chunk["source"] = "git:staged"
        return result

    @staticmethod
    def make_id(prefix: str, content: str) -> str:
        """產生穩定的節點 ID"""
        h = hashlib.md5(content.encode()).hexdigest()[:8]
        slug = re.sub(r'[^a-z0-9]+', '-', prefix.lower())[:30]
        return f"{slug}-{h}"
