"""
core/brain/condition_watcher.py — 條件性失效觸發器（修補）

## 問題

`invalidation_condition` 只是靜態文字備注，系統無法自動偵測「條件是否已滿足」。
例如：「升級到 Node.js 20+ 後此 polyfill 不再需要」—— 
系統不知道當前 Node.js 是否已升級到 20+。

## 解法

`ConditionWatcher` 從專案的實際檔案中提取「現實信號」
（package.json 版本、Dockerfile 基底映像、.env 變數等），
和 `invalidation_condition` 進行語意比對，找出「可能已失效」的知識節點。

## 支援的信號來源

1. `package.json`  — Node.js 版本、依賴版本
2. `pyproject.toml` / `requirements.txt` — Python 版本、套件版本
3. `Dockerfile`    — 基底映像版本
4. `.python-version` / `.node-version` — 語言版本鎖定
5. `go.mod`        — Go 版本

## 使用方式

    from project_brain.condition_watcher import ConditionWatcher
    from project_brain.graph import KnowledgeGraph
    from pathlib import Path

    graph   = KnowledgeGraph(Path(".brain"))
    watcher = ConditionWatcher(graph, workdir=Path("."))
    report  = watcher.check()

    for r in report:
        print(f"⚠ [{r.node_title}] 失效條件可能已滿足: {r.condition}")
        print(f"   信號來源: {r.signal_source}  信心: {r.confidence:.0%}")
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class InvalidationAlert:
    """可能失效的知識節點警告"""
    node_id:       str
    node_title:    str
    node_kind:     str
    condition:     str          # invalidation_condition 的內容
    signal_source: str          # 觸發的信號來源（package.json, Dockerfile...）
    signal_value:  str          # 偵測到的實際值（"Node.js 20.11.0"）
    confidence:    float        # 0.0~1.0，匹配信心
    suggestion:    str          # 建議操作


class ConditionWatcher:
    """
    條件性失效觸發器（修補）。

    從專案檔案提取版本信號，與知識節點的 invalidation_condition 比對，
    找出「可能已失效」的知識。

    不修改任何知識節點，只回報。人類決定是否 reject 或更新。
    """

    def __init__(self, graph, workdir: Path):
        self.graph   = graph
        self.workdir = Path(workdir)

    def check(self, skip_acked: bool = True) -> list["InvalidationAlert"]:
        """
        掃描專案檔案，比對所有知識節點的失效條件（v7.0.x 修補）。

        Args:
            skip_acked: 是否略過已用 ack() 標記的節點（預設 True）

        Returns:
            list[InvalidationAlert]：可能已失效的知識節點清單
        """
        signals  = self._extract_project_signals()
        alerts: list[InvalidationAlert] = []
        acked    = self.get_acked() if skip_acked else set()

        rows = self.graph._conn.execute("""
            SELECT id, type, title, invalidation_condition
            FROM nodes
            WHERE invalidation_condition != '' AND invalidation_condition IS NOT NULL
        """).fetchall()

        for row in rows:
            if skip_acked and row["id"] in acked:
                continue  # 已知悉，跳過
            condition = row["invalidation_condition"] or ""
            if not condition:
                continue
            alert = self._match_condition(
                node_id    = row["id"],
                node_title = row["title"],
                node_kind  = row["type"],
                condition  = condition,
                signals    = signals,
            )
            if alert:
                alerts.append(alert)

        return alerts

    def _extract_project_signals(self) -> list[dict]:
        """
        從專案檔案提取版本相關的現實信號。

        Returns:
            list[dict]：[{source, key, value, raw}]
        """
        signals: list[dict] = []

        extractors = [
            self._extract_package_json,
            self._extract_pyproject,
            self._extract_requirements,
            self._extract_dockerfile,
            self._extract_version_files,
            self._extract_go_mod,
        ]
        for fn in extractors:
            try:
                signals.extend(fn())
            except Exception as e:
                logger.debug("signal_extractor_failed: %s: %s", fn.__name__, e)

        return signals

    def _extract_package_json(self) -> list[dict]:
        p = self.workdir / "package.json"
        if not p.exists():
            return []
        import json
        data = json.loads(p.read_text())
        signals = []
        # Node.js version
        engines = data.get("engines", {})
        if "node" in engines:
            signals.append({"source": "package.json#engines.node",
                            "key": "nodejs", "value": engines["node"],
                            "raw": f"Node.js {engines['node']}"})
        # Key dependencies
        for dep_key in ("dependencies", "devDependencies"):
            for pkg, ver in data.get(dep_key, {}).items():
                signals.append({"source": f"package.json#{dep_key}.{pkg}",
                                "key": pkg, "value": ver,
                                "raw": f"{pkg}@{ver}"})
        return signals

    def _extract_pyproject(self) -> list[dict]:
        p = self.workdir / "pyproject.toml"
        if not p.exists():
            return []
        content = p.read_text()
        signals = []
        m = re.search(r'python\s*=\s*"([^"]+)"', content)
        if m:
            signals.append({"source": "pyproject.toml#python",
                            "key": "python", "value": m.group(1),
                            "raw": f"Python {m.group(1)}"})
        return signals

    def _extract_requirements(self) -> list[dict]:
        for fname in ("requirements.txt", "requirements-dev.txt"):
            p = self.workdir / fname
            if not p.exists():
                continue
            signals = []
            for line in p.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = re.match(r'^([a-zA-Z0-9_\-]+)[>=<!\s]+(.+)$', line)
                if m:
                    signals.append({"source": fname,
                                   "key": m.group(1).lower(),
                                   "value": m.group(2).strip(),
                                   "raw": line})
            return signals
        return []

    def _extract_dockerfile(self) -> list[dict]:
        p = self.workdir / "Dockerfile"
        if not p.exists():
            return []
        signals = []
        for line in p.read_text().splitlines():
            m = re.match(r'^FROM\s+([^\s:]+):?([^\s]+)?', line)
            if m:
                image = m.group(1)
                tag   = m.group(2) or "latest"
                signals.append({"source": "Dockerfile#FROM",
                               "key": image, "value": tag,
                               "raw": f"{image}:{tag}"})
        return signals

    def _extract_version_files(self) -> list[dict]:
        signals = []
        for fname, key in [(".node-version", "nodejs"), (".python-version", "python"),
                           (".ruby-version", "ruby")]:
            p = self.workdir / fname
            if p.exists():
                ver = p.read_text().strip()
                signals.append({"source": fname, "key": key,
                               "value": ver, "raw": f"{key} {ver}"})
        return signals

    def _extract_go_mod(self) -> list[dict]:
        p = self.workdir / "go.mod"
        if not p.exists():
            return []
        m = re.search(r'^go\s+(\d+\.\d+)', p.read_text(), re.MULTILINE)
        if m:
            return [{"source": "go.mod", "key": "go",
                    "value": m.group(1), "raw": f"Go {m.group(1)}"}]
        return []

    def ack(self, node_id: str, note: str = "") -> bool:
        """
        標記指定節點的失效警告為「已知悉」（v7.0.x 修補）。

        `brain watch` 每次都會重新掃描，
        ack 後的節點不再重複顯示，直到下次 invalidation_condition 更新。

        Args:
            node_id: 要標記的節點 ID
            note:    說明原因（選填）

        Returns:
            bool：是否成功記錄
        """
        import sqlite3, json as _j
        db_path = self.graph.db_path.parent / "watch_ack.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ack_list (
                node_id    TEXT PRIMARY KEY,
                note       TEXT DEFAULT '',
                acked_at   TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO ack_list(node_id, note) VALUES(?,?)",
            (node_id, note)
        )
        conn.commit()
        conn.close()
        return True

    def get_acked(self) -> set:
        """取得所有已標記為知悉的節點 ID"""
        import sqlite3
        db_path = self.graph.db_path.parent / "watch_ack.db"
        if not db_path.exists():
            return set()
        try:
            conn = sqlite3.connect(str(db_path))
            rows = conn.execute("SELECT node_id FROM ack_list").fetchall()
            conn.close()
            return {r[0] for r in rows}
        except Exception:
            return set()

    def _try_structured_rule(
        self,
        condition: str,
        signals:   list[dict],
    ) -> Optional[bool]:
        """
        嘗試解析結構化失效條件規則（v8.0）。

        語法：
          node_version >= 20         → 比較 Node.js 主版本
          python_version >= 3.12     → 比較 Python 版本
          package:<name> >= <ver>    → 比較 npm/pip 套件版本
          env:<VAR> == <value>       → 比較環境變數值
          file_exists:<path>         → 特定檔案是否存在

        Returns:
          True  → 條件已觸發（知識失效）
          False → 條件未觸發（知識仍有效）
          None  → 無法解析（fallback 到自然語言比對）
        """
        import re, os
        c = condition.strip()

        # node_version >= N
        m = re.match(r'node_version\s*([><=!]+)\s*(\d+)', c, re.I)
        if m:
            op, req = m.group(1), int(m.group(2))
            for s in signals:
                if s['key'] in ('nodejs', 'node'):
                    curr = re.search(r'(\d+)', s['value'])
                    if curr:
                        return self._compare_versions(int(curr.group()), op, req)
            return False  # 找不到信號 = 條件未觸發

        # python_version >= N.M
        m = re.match(r'python_version\s*([><=!]+)\s*(\d+\.\d+)', c, re.I)
        if m:
            op, req = m.group(1), float(m.group(2))
            for s in signals:
                if s['key'] == 'python':
                    curr = re.search(r'(\d+\.\d+)', s['value'])
                    if curr:
                        return self._compare_versions(float(curr.group()), op, req)
            return False

        # package:<name> >= <ver>
        m = re.match(r'package:([a-zA-Z0-9_\-]+)\s*([><=!]+)\s*([\d.]+)', c, re.I)
        if m:
            pkg, op, req = m.group(1).lower(), m.group(2), m.group(3)
            for s in signals:
                if s['key'].lower() == pkg:
                    curr_s = re.search(r'(\d+)', s['value'])
                    req_s  = re.search(r'(\d+)', req)
                    if curr_s and req_s:
                        return self._compare_versions(
                            int(curr_s.group()), op, int(req_s.group())
                        )
            return False

        # env:<VAR> == <value>
        m = re.match(r'env:([A-Z0-9_]+)\s*([=!]+)\s*(\S+)', c, re.I)
        if m:
            var, op, expected = m.group(1), m.group(2), m.group(3)
            actual = os.environ.get(var, "")
            if op in ('==', '='):
                return actual == expected
            elif op in ('!=', '!=='):
                return actual != expected
            return False

        # file_exists:<path>
        m = re.match(r'file_exists:(.+)', c, re.I)
        if m:
            path = Path(self.workdir) / m.group(1).strip()
            return path.exists()

        return None  # 無法解析 → fallback 到自然語言

    @staticmethod
    def _compare_versions(current, op: str, required) -> bool:
        """比較版本數字"""
        if op in ('>=', '=>'):  return current >= required
        if op in ('<=', '=<'):  return current <= required
        if op == '>':           return current > required
        if op == '<':           return current < required
        if op in ('==', '='):   return current == required
        if op in ('!=', '!='): return current != required
        return False

    def _match_condition(
        self,
        node_id:    str,
        node_title: str,
        node_kind:  str,
        condition:  str,
        signals:    list[dict],
    ) -> Optional[InvalidationAlert]:
        """
        將失效條件與信號清單做語意比對（v8.0 升級：支援結構化規則語法）。

        支援兩種格式：
        1. 自然語言（原有）："升級到 Node.js 20 後不再需要"
        2. 結構化規則（v8.0 新增）：
           "node_version >= 20"
           "package:express >= 5.0"
           "env:NODE_ENV == production"
           "file_exists:.no-polyfill"

        結構化規則優先，無法解析時 fallback 到自然語言比對。
        """
        # 先嘗試結構化規則解析（精準，無歧義）
        structured = self._try_structured_rule(condition, signals)
        if structured is not None:
            if not structured:
                return None  # 明確「未觸發」
            return InvalidationAlert(
                node_id       = node_id,
                node_title    = node_title,
                node_kind     = node_kind,
                condition     = condition,
                signal_source = "structured-rule",
                signal_value  = condition,
                confidence    = 0.95,  # 結構化規則信心更高
                suggestion    = (
                    f"結構化條件已觸發：`{condition}`。"
                    f"請確認此節點是否應更新或刪除。"
                ),
            )

        condition_lower = condition.lower()

        # 版本關鍵字模式：<技術> <版本號>
        VERSION_PATTERNS = [
            (r'node\.?js\s*(?:>=?\s*)?(\d+)', "nodejs", "Node.js"),
            (r'python\s*(?:>=?\s*)?(\d+\.\d+)', "python", "Python"),
            (r'go\s*(?:>=?\s*)?(\d+\.\d+)', "go", "Go"),
            (r'django\s*(?:>=?\s*)?(\d+)', "django", "Django"),
            (r'react\s*(?:>=?\s*)?(\d+)', "react", "React"),
            (r'next\.?js\s*(?:>=?\s*)?(\d+)', "next", "Next.js"),
        ]

        for pattern, key, display in VERSION_PATTERNS:
            m = re.search(pattern, condition_lower)
            if not m:
                continue
            required_version = m.group(1)

            # 找對應信號
            for signal in signals:
                if signal["key"].lower() in (key, key.replace("js", "")):
                    current_version = re.search(r'[\d]+', signal["value"])
                    if not current_version:
                        continue
                    curr_major = int(current_version.group())
                    try:
                        req_major = int(required_version)
                    except ValueError:
                        continue

                    # 條件：如果 condition 說「升級到 X 後失效」
                    # 且當前版本 >= X，則可能已失效
                    if curr_major >= req_major:
                        return InvalidationAlert(
                            node_id       = node_id,
                            node_title    = node_title,
                            node_kind     = node_kind,
                            condition     = condition,
                            signal_source = signal["source"],
                            signal_value  = signal["raw"],
                            confidence    = 0.8,
                            suggestion    = (
                                f"當前 {display} 版本（{signal['raw']}）已達 v{required_version}+，"
                                f"此知識節點的失效條件可能已滿足。"
                                f"請確認後執行 brain review 更新或刪除此節點。"
                            ),
                        )
        return None
