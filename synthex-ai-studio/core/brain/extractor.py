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

輸出 JSON（只輸出 JSON，不要其他說明）：
{
  "knowledge_chunks": [
    {
      "type": "Decision|Pitfall|Rule|Architecture",
      "title": "簡短標題（< 50 字）",
      "content": "詳細說明（包含背景、原因、影響）",
      "tags": ["相關標籤"],
      "confidence": 0.0-1.0
    }
  ],
  "components_mentioned": ["組件名稱列表"],
  "dependencies_detected": [
    {"from": "組件A", "to": "組件B", "reason": "為什麼依賴"}
  ]
}

如果沒有有價值的知識，返回：{"knowledge_chunks": [], "components_mentioned": [], "dependencies_detected": []}
"""


class KnowledgeExtractor:
    """AI 驅動的知識提取器"""

    def __init__(self, workdir: str):
        self.workdir = Path(workdir)
        self.client  = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )
        # 用便宜的 Sonnet 做提取（量大但邏輯不複雜）
        self.model = _DEFAULT_MODEL

    def _call(self, content: str, max_tokens: int = 1000) -> dict:
        """呼叫 Claude API 提取知識"""
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{
                    "role": "user",
                    "content": EXTRACTION_PROMPT + "\n\n---\n\n" + content[:4000]
                }]
            )
            text = resp.content[0].text
            # 清理可能的 markdown 包裹
            text = re.sub(r"```json\n?", "", text)
            text = re.sub(r"```\n?",     "", text)
            return json.loads(text.strip())
        except Exception as e:
            return {"knowledge_chunks": [], "components_mentioned": [],
                    "dependencies_detected": [], "_error": str(e)}

    def from_git_commit(self, commit_hash: str, commit_msg: str, diff: str) -> dict:
        """從 git commit 提取知識"""
        content = f"""
Git Commit: {commit_hash[:8]}
Message: {commit_msg}

Code Diff:
{diff[:3000]}
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

    @staticmethod
    def make_id(prefix: str, content: str) -> str:
        """產生穩定的節點 ID"""
        h = hashlib.md5(content.encode()).hexdigest()[:8]
        slug = re.sub(r'[^a-z0-9]+', '-', prefix.lower())[:30]
        return f"{slug}-{h}"
