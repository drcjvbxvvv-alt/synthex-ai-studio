"""
project_brain/federation.py — PH3-01 Cross-Project Knowledge Sharing

聯邦知識共享模組：讓不同專案的 Project Brain 實例安全交換知識。

元件：
  FederationBundle     — 可攜帶的知識匯出格式（JSON 可序列化）
  FederationExporter   — 把本地 L3 知識匯出為 Bundle
  FederationImporter   — 把 Bundle 匯入 KRB Staging（等待人工審查）
  SubscriptionManager  — 管理領域訂閱設定

設計原則：
  - 匯出前自動清除 PII（email、內部主機名稱）
  - 匯入時先過濾訂閱領域，再去重複，再進 KRB Staging
  - 永不直接寫入 L3（所有聯邦知識都需人工審查）
  - 零額外依賴（只用 stdlib + 現有 project_brain 模組）
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── PII 過濾 Regex ─────────────────────────────────────────────
_PII_EMAIL    = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
_PII_INTERNAL = re.compile(r'(?i)\b(?:internal|corp|intranet)\.[a-zA-Z0-9.-]+')
_PII_LOCAL    = re.compile(r'(?i)[a-zA-Z0-9_-]+\.local\b')

# ── 聯邦設定路徑 ──────────────────────────────────────────────
_FED_CONFIG_NAME   = "federation.json"
_FED_EXPORT_NAME   = "federation_export.json"
_BUNDLE_VERSION    = "1.0"

# sanitise 時截取的最大內容長度
_MAX_CONTENT_LEN   = 600


def _strip_pii(text: str) -> str:
    """移除電子郵件與常見內部主機名稱"""
    text = _PII_EMAIL.sub("[redacted-email]", text)
    text = _PII_INTERNAL.sub("[redacted-internal]", text)
    text = _PII_LOCAL.sub("[redacted-local]", text)
    return text


# ══════════════════════════════════════════════════════════════
#  FederationBundle
# ══════════════════════════════════════════════════════════════

@dataclass
class FederationBundle:
    """可攜帶的聯邦知識匯出格式（JSON-serialisable dataclass）"""

    version:        str         # "1.0"
    source_project: str         # 來源專案名稱 / 路徑
    exported_at:    str         # ISO 8601 時間戳
    nodes:          list[dict]  # 清潔後的知識節點
    domain_tags:    list[str]   # 此 Bundle 涵蓋的技術領域
    node_count:     int

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, text: str) -> "FederationBundle":
        data = json.loads(text)
        return cls(
            version        = data.get("version",        _BUNDLE_VERSION),
            source_project = data.get("source_project", ""),
            exported_at    = data.get("exported_at",    ""),
            nodes          = data.get("nodes",          []),
            domain_tags    = data.get("domain_tags",    []),
            node_count     = data.get("node_count",     0),
        )


# ══════════════════════════════════════════════════════════════
#  FederationExporter
# ══════════════════════════════════════════════════════════════

class FederationExporter:
    """
    把 KnowledgeGraph 中的 global scope 知識匯出成 FederationBundle。

    使用方式：
        exporter = FederationExporter(graph, brain_dir, project_name="my-app")
        bundle   = exporter.export(min_confidence=0.6)
    """

    def __init__(
        self,
        graph,
        brain_dir:    Path,
        project_name: str = "",
    ) -> None:
        self.graph        = graph
        self.brain_dir    = Path(brain_dir)
        self.project_name = project_name or str(self.brain_dir.parent)

    def export(
        self,
        output_path:    Optional[Path] = None,
        scope:          str   = "global",
        min_confidence: float = 0.6,
        max_nodes:      int   = 500,
    ) -> FederationBundle:
        """
        匯出滿足條件的知識節點為 FederationBundle。

        Args:
            output_path:    輸出 JSON 路徑（預設 .brain/federation_export.json）
            scope:          只匯出 scope IN ("global", scope) 的節點
            min_confidence: 最低信心門檻
            max_nodes:      最多匯出節點數

        Returns:
            FederationBundle
        """
        output_path = output_path or (self.brain_dir / _FED_EXPORT_NAME)

        # 查詢節點（嘗試有 scope 欄位的資料庫，fallback 到無 scope）
        try:
            rows = self.graph._conn.execute(
                """
                SELECT id, type, title, content, tags, confidence, meta
                FROM   nodes
                WHERE  (scope IN ('global', ?) OR scope IS NULL)
                  AND  confidence >= ?
                ORDER  BY confidence DESC
                LIMIT  ?
                """,
                (scope, min_confidence, max_nodes),
            ).fetchall()
        except Exception:
            # BUG-A04: scope column may not exist on older DBs — fallback still
            # enforces scope filtering to avoid leaking private nodes
            try:
                rows = self.graph._conn.execute(
                    """
                    SELECT id, type, title, content, tags, confidence, meta
                    FROM   nodes
                    WHERE  confidence >= ?
                      AND  (scope IS NULL OR scope = 'global' OR scope = ?)
                    ORDER  BY confidence DESC
                    LIMIT  ?
                    """,
                    (min_confidence, scope, max_nodes),
                ).fetchall()
            except Exception as exc:
                logger.error("federation export: 無法查詢節點: %s", exc)
                rows = []

        sanitised = []
        domain_tag_set: set[str] = set()

        for _row in rows:
            row = dict(_row)
            node = self._sanitise_node(row)
            if node:
                sanitised.append(node)
                # 收集 domain tags（解析 tags JSON array 或逗號分隔字串）
                for tag in self._parse_tags(row.get("tags", "")):
                    domain_tag_set.add(tag.lower())

        bundle = FederationBundle(
            version        = _BUNDLE_VERSION,
            source_project = self.project_name,
            exported_at    = datetime.now(timezone.utc).isoformat(),
            nodes          = sanitised,
            domain_tags    = sorted(domain_tag_set),
            node_count     = len(sanitised),
        )

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(bundle.to_json(), encoding="utf-8")
            logger.info(
                "federation_exported | nodes=%d → %s", len(sanitised), output_path
            )
        except Exception as exc:
            logger.error("federation export: 無法寫入 %s: %s", output_path, exc)

        return bundle

    def _sanitise_node(self, row: dict) -> Optional[dict]:
        """
        清潔節點資料，移除 PII 和內部路徑。

        保留：id, title, content[:600], kind/type, confidence, tags
        移除：source_url（可能含內部路徑）、author 資訊
        """
        title   = _strip_pii(row.get("title", "") or "")
        content = _strip_pii((row.get("content", "") or "")[:_MAX_CONTENT_LEN])

        if not title.strip():
            return None

        return {
            "id":         row.get("id", str(uuid.uuid4())),
            "kind":       row.get("type", "Rule"),
            "title":      title,
            "content":    content,
            "confidence": float(row.get("confidence", 0.7) or 0.7),
            "tags":       row.get("tags", ""),
        }

    @staticmethod
    def _parse_tags(tags_raw: str) -> list[str]:
        """解析 tags 欄位（JSON array 或逗號分隔字串）"""
        if not tags_raw:
            return []
        try:
            parsed = json.loads(tags_raw)
            if isinstance(parsed, list):
                return [str(t) for t in parsed]
        except (json.JSONDecodeError, TypeError):
            pass
        return [t.strip() for t in tags_raw.split(",") if t.strip()]


# ══════════════════════════════════════════════════════════════
#  FederationImporter
# ══════════════════════════════════════════════════════════════

class FederationImporter:
    """
    把 FederationBundle 匯入 KRB Staging（等待人工審查）。

    使用方式：
        importer = FederationImporter(krb, brain_dir)
        stats    = importer.import_bundle(Path("bundle.json"), dry_run=False)
    """

    def __init__(self, krb, brain_dir: Path, brain_db=None) -> None:
        self.krb       = krb
        self.brain_dir = Path(brain_dir)
        self._sub_mgr  = SubscriptionManager(brain_dir)
        self._brain_db = brain_db

    def import_bundle(
        self,
        bundle_path:    Path,
        dry_run:        bool  = False,
        min_confidence: float = 0.5,
    ) -> dict:
        """
        匯入 FederationBundle 到 KRB Staging。

        Args:
            bundle_path:    Bundle JSON 檔案路徑
            dry_run:        True 時只計算，不寫入
            min_confidence: 最低信心門檻（低於此值的節點略過）

        Returns:
            {"imported": N, "skipped_dup": N, "skipped_low_conf": N, "skipped_domain": N}
        """
        stats = {
            "imported":          0,
            "skipped_dup":       0,
            "skipped_low_conf":  0,
            "skipped_domain":    0,
        }

        try:
            bundle = FederationBundle.from_json(bundle_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("import_bundle: 無法讀取 %s: %s", bundle_path, exc)
            return stats

        subscriptions = self._sub_mgr.list_subscriptions()

        for node in bundle.nodes:
            title      = node.get("title", "")
            content    = node.get("content", "")
            kind       = node.get("kind", "Rule")
            confidence = float(node.get("confidence", 0.5) or 0.5)
            tags_raw   = node.get("tags", "")

            # 信心過濾
            if confidence < min_confidence:
                stats["skipped_low_conf"] += 1
                continue

            # 訂閱領域過濾（空訂閱 = 接受所有）
            if subscriptions:
                node_tags = FederationExporter._parse_tags(tags_raw)
                tag_set   = {t.lower() for t in node_tags}
                if not any(sub.lower() in tag_set for sub in subscriptions):
                    stats["skipped_domain"] += 1
                    continue

            # 去重複
            if self._is_duplicate(title, content):
                stats["skipped_dup"] += 1
                continue

            # 寫入 KRB Staging
            if not dry_run:
                try:
                    self.krb.submit(
                        title    = title,
                        content  = content,
                        kind     = kind,
                        tags     = tags_raw,
                        source   = f"federation:{bundle.source_project}",
                        submitter = "federation",
                    )
                    # FED-01: record federation import audit
                    if self._brain_db:
                        self._brain_db.record_federation_import(
                            source=f"federation:{bundle.source_project}",
                            node_id=node.get("id", ""),
                            node_title=title[:100],
                            status='staged'
                        )
                except Exception as exc:
                    logger.error("import_bundle: submit 失敗 (%s): %s", title[:40], exc)
                    continue

            stats["imported"] += 1

        logger.info(
            "federation_imported | imported=%d dup=%d low_conf=%d domain=%d dry_run=%s",
            stats["imported"], stats["skipped_dup"],
            stats["skipped_low_conf"], stats["skipped_domain"], dry_run,
        )
        return stats

    def _is_duplicate(self, title: str, content: str = "") -> bool:
        """
        重複檢查：
          1. 精確比對 nodes.title
          2. Jaccard 相似度 > 0.8（title token 集合）
          3. FED-02: TF-IDF cosine similarity >= 0.82（title+content 向量）
        """
        if not title:
            return False

        # 精確比對
        try:
            row = self.krb.graph._conn.execute(
                "SELECT 1 FROM nodes WHERE title=? LIMIT 1", (title,)
            ).fetchone()
            if row:
                return True
        except Exception as _e:
            logger.warning("exact title dedup check failed: %s", _e)

        # Jaccard token 比對（只查前 200 筆避免全表掃描）
        title_tokens = set(re.findall(r'\w+', title.lower()))
        if not title_tokens:
            return False

        try:
            rows = self.krb.graph._conn.execute(
                "SELECT title FROM nodes LIMIT 200"
            ).fetchall()
            for row in rows:
                existing_title = (row[0] or "")
                existing_tokens = set(re.findall(r'\w+', existing_title.lower()))
                union = title_tokens | existing_tokens
                if not union:
                    continue
                jaccard = len(title_tokens & existing_tokens) / len(union)
                if jaccard > 0.8:
                    return True
        except Exception as _e:
            logger.warning("Jaccard dedup check failed: %s", _e)

        # FED-02: semantic similarity check via TF-IDF cosine
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.metrics.pairwise import cosine_similarity as _cos_sim
            query_text = (title + " " + content).strip()
            rows = self.krb.graph._conn.execute(
                "SELECT title, content FROM nodes LIMIT 300"
            ).fetchall()
            if rows:
                corpus = [(row[0] or "") + " " + (row[1] or "") for row in rows]
                all_texts = [query_text] + corpus
                vec = TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(2, 4),
                    max_features=3000, sublinear_tf=True,
                )
                matrix = vec.fit_transform(all_texts)
                sims = _cos_sim(matrix[0:1], matrix[1:]).flatten()
                if sims.max() >= 0.82:
                    return True
        except Exception as _e:
            logger.warning("TF-IDF semantic dedup check failed: %s", _e)

        return False


# ══════════════════════════════════════════════════════════════
#  SubscriptionManager
# ══════════════════════════════════════════════════════════════

class SubscriptionManager:
    """
    管理聯邦知識的領域訂閱設定。

    設定儲存於 .brain/federation.json：
    {
        "subscriptions": [{"domain": "react", "added_at": "..."}],
        "blocked_sources": []
    }

    空訂閱清單 = 接受所有領域。
    """

    def __init__(self, brain_dir: Path) -> None:
        self.brain_dir   = Path(brain_dir)
        self._cfg_path   = self.brain_dir / _FED_CONFIG_NAME

    def _load(self) -> dict:
        """讀取設定，失敗時回傳預設空設定"""
        try:
            if self._cfg_path.exists():
                return json.loads(self._cfg_path.read_text(encoding="utf-8"))
        except Exception as _e:
            logger.warning("federation config load failed: %s", _e)
        return {"subscriptions": [], "blocked_sources": []}

    def _save(self, cfg: dict) -> None:
        """寫入設定"""
        try:
            self.brain_dir.mkdir(parents=True, exist_ok=True)
            self._cfg_path.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.error("SubscriptionManager._save 失敗: %s", exc)

    def subscribe(self, domain: str) -> bool:
        """訂閱一個領域，若已訂閱則回傳 False"""
        domain = domain.lower().strip()
        cfg    = self._load()
        subs   = cfg.get("subscriptions", [])
        if any(s.get("domain") == domain for s in subs):
            return False
        subs.append({
            "domain":   domain,
            "added_at": datetime.now(timezone.utc).isoformat(),
        })
        cfg["subscriptions"] = subs
        self._save(cfg)
        logger.info("federation: subscribed domain=%s", domain)
        return True

    def unsubscribe(self, domain: str) -> bool:
        """取消訂閱一個領域，若不存在則回傳 False"""
        domain = domain.lower().strip()
        cfg    = self._load()
        subs   = cfg.get("subscriptions", [])
        new_subs = [s for s in subs if s.get("domain") != domain]
        if len(new_subs) == len(subs):
            return False
        cfg["subscriptions"] = new_subs
        self._save(cfg)
        logger.info("federation: unsubscribed domain=%s", domain)
        return True

    def list_subscriptions(self) -> list[str]:
        """回傳訂閱的領域清單（空清單 = 接受所有）"""
        cfg  = self._load()
        return [s.get("domain", "") for s in cfg.get("subscriptions", [])]

    def is_subscribed(self, domain: str) -> bool:
        """
        判斷指定領域是否在訂閱清單中。
        空訂閱清單 = 接受所有（回傳 True）。
        """
        subs = self.list_subscriptions()
        if not subs:
            return True
        return domain.lower().strip() in subs


# ══════════════════════════════════════════════════════════════
#  FederationAutoSync  (VISION-03)
# ══════════════════════════════════════════════════════════════

class FederationAutoSync:
    """
    跨專案知識自動同步（VISION-03）。

    從 .brain/federation.json 的 sync_sources 清單讀取本地 bundle 路徑，
    依序匯入到 KRB Staging，供人工審查後升級至 L3。

    設定格式（.brain/federation.json）：
    {
        "subscriptions": [...],
        "blocked_sources": [...],
        "sync_sources": [
            {
                "name":       "project-a",
                "bundle_path": "/absolute/or/relative/path/federation_export.json",
                "enabled":    true
            }
        ]
    }

    設計原則：
      - 同步後永不直接寫入 L3（所有知識走 KRB Staging）
      - bundle_path 可為絕對路徑或相對於 brain_dir 的路徑
      - enabled=false 的來源被跳過
      - 每次 sync 都回傳詳細統計
    """

    def __init__(self, krb, brain_dir: Path) -> None:
        self.krb        = krb
        self.brain_dir  = Path(brain_dir)
        self._cfg_path  = self.brain_dir / _FED_CONFIG_NAME

    def _load_sources(self) -> list[dict]:
        try:
            if self._cfg_path.exists():
                cfg = json.loads(self._cfg_path.read_text(encoding="utf-8"))
                return cfg.get("sync_sources", [])
        except Exception as exc:
            logger.warning("FederationAutoSync: 無法讀取設定 %s: %s", self._cfg_path, exc)
        return []

    def add_source(self, name: str, bundle_path: str, enabled: bool = True) -> bool:
        """新增一個同步來源，若已存在同名來源則更新"""
        try:
            cfg = json.loads(self._cfg_path.read_text(encoding="utf-8")) \
                  if self._cfg_path.exists() else {}
            sources = cfg.get("sync_sources", [])
            # 更新或新增
            updated = False
            for src in sources:
                if src.get("name") == name:
                    src["bundle_path"] = bundle_path
                    src["enabled"]     = enabled
                    updated = True
                    break
            if not updated:
                sources.append({
                    "name":        name,
                    "bundle_path": bundle_path,
                    "enabled":     enabled,
                    "added_at":    datetime.now(timezone.utc).isoformat(),
                })
            cfg["sync_sources"] = sources
            self.brain_dir.mkdir(parents=True, exist_ok=True)
            self._cfg_path.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except Exception as exc:
            logger.error("FederationAutoSync.add_source 失敗: %s", exc)
            return False

    def remove_source(self, name: str) -> bool:
        """移除一個同步來源"""
        try:
            if not self._cfg_path.exists():
                return False
            cfg     = json.loads(self._cfg_path.read_text(encoding="utf-8"))
            sources = cfg.get("sync_sources", [])
            new_src = [s for s in sources if s.get("name") != name]
            if len(new_src) == len(sources):
                return False
            cfg["sync_sources"] = new_src
            self._cfg_path.write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return True
        except Exception as exc:
            logger.error("FederationAutoSync.remove_source 失敗: %s", exc)
            return False

    def sync_all(
        self,
        dry_run:        bool  = False,
        min_confidence: float = 0.5,
    ) -> dict:
        """
        同步所有已啟用的來源。

        Returns:
            {
                "synced":   int,   — 成功同步的來源數
                "skipped":  int,   — 停用或找不到 bundle 的來源數
                "errors":   int,   — 發生錯誤的來源數
                "details":  list,  — 每個來源的統計（含 imported/dup/low_conf/domain）
            }
        """
        sources = self._load_sources()
        result  = {"synced": 0, "skipped": 0, "errors": 0, "details": []}

        if not sources:
            logger.info("FederationAutoSync: 無已設定的同步來源")
            return result

        importer = FederationImporter(self.krb, self.brain_dir)

        for src in sources:
            name    = src.get("name", "unknown")
            enabled = src.get("enabled", True)

            if not enabled:
                result["skipped"] += 1
                result["details"].append({"name": name, "status": "disabled"})
                continue

            bundle_path_raw = src.get("bundle_path", "")
            if not bundle_path_raw:
                result["skipped"] += 1
                result["details"].append({"name": name, "status": "no bundle_path"})
                continue

            # 支援相對路徑（相對於 brain_dir）
            bundle_path = Path(bundle_path_raw)
            if not bundle_path.is_absolute():
                bundle_path = self.brain_dir / bundle_path

            if not bundle_path.exists():
                logger.warning("FederationAutoSync: bundle 不存在 %s (來源: %s)", bundle_path, name)
                result["skipped"] += 1
                result["details"].append({"name": name, "status": "bundle_not_found", "path": str(bundle_path)})
                continue

            try:
                stats = importer.import_bundle(
                    bundle_path    = bundle_path,
                    dry_run        = dry_run,
                    min_confidence = min_confidence,
                )
                result["synced"] += 1
                result["details"].append({"name": name, "status": "ok", **stats})
                logger.info(
                    "FederationAutoSync: 來源 %s → imported=%d dup=%d low_conf=%d domain=%d",
                    name, stats["imported"], stats["skipped_dup"],
                    stats["skipped_low_conf"], stats["skipped_domain"],
                )
            except Exception as exc:
                logger.error("FederationAutoSync: 來源 %s 同步失敗: %s", name, exc)
                result["errors"] += 1
                result["details"].append({"name": name, "status": "error", "error": str(exc)})

        return result


# ══════════════════════════════════════════════════════════════
#  CLI 輔助函式（供 cli.py 呼叫）
# ══════════════════════════════════════════════════════════════

def cmd_fed_export(brain_dir: Path, graph, args) -> None:
    """
    CLI: brain fed export

    args 預期屬性：
        output     (str | None)  — 輸出路徑（可選）
        scope      (str)         — 預設 "global"
        confidence (float)       — 預設 0.6
        max_nodes  (int)         — 預設 500
        project    (str)         — 專案名稱（可選）
    """
    exporter = FederationExporter(
        graph,
        brain_dir,
        project_name = getattr(args, "project", ""),
    )
    out_path = Path(args.output) if getattr(args, "output", None) else None
    bundle   = exporter.export(
        output_path    = out_path,
        scope          = getattr(args, "scope",      "global"),
        min_confidence = getattr(args, "confidence", 0.6),
        max_nodes      = getattr(args, "max_nodes",  500),
    )
    print(f"  Exported {bundle.node_count} nodes → {out_path or (brain_dir / _FED_EXPORT_NAME)}")


def cmd_fed_import(brain_dir: Path, krb, args) -> None:
    """
    CLI: brain fed import <bundle_path>

    args 預期屬性：
        bundle_path (str)   — Bundle JSON 路徑
        dry_run     (bool)  — 預設 False
        confidence  (float) — 預設 0.5
    """
    bundle_path = Path(getattr(args, "bundle_path", ""))
    if not bundle_path.exists():
        print(f"  ERROR: 找不到 bundle 檔案 {bundle_path}")
        return

    importer = FederationImporter(krb, brain_dir)
    stats    = importer.import_bundle(
        bundle_path    = bundle_path,
        dry_run        = getattr(args, "dry_run",    False),
        min_confidence = getattr(args, "confidence", 0.5),
    )
    dry = " (dry run)" if getattr(args, "dry_run", False) else ""
    print(
        f"  Federation import{dry}: "
        f"imported={stats['imported']} "
        f"dup={stats['skipped_dup']} "
        f"low_conf={stats['skipped_low_conf']} "
        f"domain={stats['skipped_domain']}"
    )


def cmd_fed_subscribe(brain_dir: Path, args) -> None:
    """
    CLI: brain fed subscribe / unsubscribe / list

    args 預期屬性：
        action (str)  — "subscribe" | "unsubscribe" | "list"
        domain (str)  — 領域名稱（subscribe / unsubscribe 需要）
    """
    mgr    = SubscriptionManager(brain_dir)
    action = getattr(args, "action", "list")

    if action == "list":
        subs = mgr.list_subscriptions()
        if subs:
            print("  Subscriptions: " + ", ".join(subs))
        else:
            print("  No subscriptions (accepting all domains)")

    elif action == "subscribe":
        domain = getattr(args, "domain", "")
        if not domain:
            print("  ERROR: 請提供 --domain")
            return
        ok = mgr.subscribe(domain)
        print(f"  {'Subscribed to' if ok else 'Already subscribed to'}: {domain}")

    elif action == "unsubscribe":
        domain = getattr(args, "domain", "")
        if not domain:
            print("  ERROR: 請提供 --domain")
            return
        ok = mgr.unsubscribe(domain)
        print(f"  {'Unsubscribed from' if ok else 'Not subscribed to'}: {domain}")

    else:
        print(f"  Unknown action: {action}")


def cmd_fed_sync(brain_dir: Path, krb, args) -> None:
    """
    CLI: brain fed sync  (VISION-03)

    自動從所有已設定的 sync_sources 拉取 bundle 並匯入 KRB Staging。

    args 預期屬性：
        dry_run    (bool)  — 預設 False
        confidence (float) — 預設 0.5
        add_source (str)   — "name:bundle_path" 格式，新增同步來源
        remove_source (str)— 移除同步來源（依名稱）
    """
    syncer = FederationAutoSync(krb, brain_dir)

    # 新增來源
    add_src = getattr(args, "add_source", None)
    if add_src:
        parts = add_src.split(":", 1)
        if len(parts) != 2:
            print("  ERROR: --add-source 格式應為 name:bundle_path")
            return
        ok = syncer.add_source(parts[0].strip(), parts[1].strip())
        print(f"  {'Added' if ok else 'Updated'} sync source: {parts[0].strip()}")
        return

    # 移除來源
    rm_src = getattr(args, "remove_source", None)
    if rm_src:
        ok = syncer.remove_source(rm_src)
        print(f"  {'Removed' if ok else 'Source not found'}: {rm_src}")
        return

    # 執行同步
    dry   = getattr(args, "dry_run",    False)
    conf  = getattr(args, "confidence", 0.5)
    stats = syncer.sync_all(dry_run=dry, min_confidence=conf)

    dry_label = " (dry run)" if dry else ""
    print(
        f"  Federation sync{dry_label}: "
        f"synced={stats['synced']} "
        f"skipped={stats['skipped']} "
        f"errors={stats['errors']}"
    )
    for d in stats.get("details", []):
        name   = d.get("name", "?")
        status = d.get("status", "?")
        if status == "ok":
            print(
                f"    [{name}] imported={d.get('imported',0)} "
                f"dup={d.get('skipped_dup',0)} "
                f"low_conf={d.get('skipped_low_conf',0)} "
                f"domain={d.get('skipped_domain',0)}"
            )
        else:
            print(f"    [{name}] {status}")


def cmd_fed_import_list(bd: Path, args) -> None:
    """FED-01: brain fed imports — 列出聯邦匯入記錄"""
    from project_brain.brain_db import BrainDB
    db    = BrainDB(bd)
    limit = int(getattr(args, 'limit', 20) or 20)
    rows  = db.get_federation_imports(limit=limit)
    if not rows:
        print("  (無聯邦匯入記錄)")
        return
    print(f"\n  \033[1m聯邦匯入記錄（最近 {len(rows)} 筆）\033[0m")
    print(f"  \033[90m{'─'*60}\033[0m")
    for r in rows:
        ts     = (r.get('imported_at') or '')[:16]
        src    = (r.get('source') or '')[:25]
        title  = (r.get('node_title') or '')[:35]
        status = r.get('status', '?')
        print(f"  \033[90m{ts}\033[0m  \033[96m{src}\033[0m  {title}  [{status}]")
    print()
