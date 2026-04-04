"""
UNQ-03 基準測試：get_context 召回率量測

設計：
  - 50 個精心設計的軟體工程知識節點（涵蓋 10 個主題領域）
  - 20 個查詢，每個查詢有 1 個「預期應出現」的節點
  - 召回率 = 預期節點出現在輸出中的查詢數 / 20
  - 同時測試 FTS5 精確度（title 精確出現）

目標（UNQ-03）：
  ≥ 60%  有 sentence-transformers
  ≥ 40%  只有 LocalTFIDF
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import NamedTuple

# ── 確保 project_brain 可 import ─────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from project_brain.graph    import KnowledgeGraph
from project_brain.context  import ContextEngineer
from project_brain.brain_db import BrainDB
from project_brain.embedder import get_embedder


# ══════════════════════════════════════════════════════════════════
#  50 節點測試庫
#  欄位：(id, type, title, content, tags, confidence)
# ══════════════════════════════════════════════════════════════════

NODES: list[tuple] = [
    # ── 資料庫（DB）──────────────────────────────────────────────
    ("db-01", "Pitfall",  "N+1 查詢問題",
     "ORM 在迴圈內逐筆 SELECT 導致 N+1 問題。應使用 eager loading（select_related / prefetch_related）或批次查詢合一。",
     ["database", "orm", "performance"], 0.92),

    ("db-02", "Rule",     "資料庫 Migration 必須向前相容",
     "每次 migration 在新舊版本程式碼同時執行期間都必須能正常運作。先加欄位、後移除舊欄位，不可直接重命名。",
     ["database", "migration", "deployment"], 0.95),

    ("db-03", "Decision", "連線池大小設定為 CPU 核心數 × 2",
     "PostgreSQL 連線池最佳大小通常為 CPU 核心數 × 2 + 可用磁碟主軸數。過大反而因 context switch 降低吞吐量。",
     ["database", "performance", "postgresql"], 0.88),

    ("db-04", "Rule",     "交易邊界不跨越網路呼叫",
     "HTTP 呼叫或外部 API 不可放在資料庫 transaction 內部。網路延遲會鎖住資料列，造成 deadlock 或超時。",
     ["database", "transaction", "architecture"], 0.93),

    ("db-05", "Pitfall",  "未建索引的外鍵導致全表掃描",
     "PostgreSQL 不自動為外鍵建立索引。JOIN 查詢若沒有對應索引，每次都是 Seq Scan，資料量大時效能崩潰。",
     ["database", "index", "postgresql"], 0.90),

    # ── API 設計 ─────────────────────────────────────────────────
    ("api-01", "Rule",    "API 版本號在路徑中，非 Header",
     "版本放 URL（/v1/users）比放 Header（Accept: application/vnd.api+v1）易於測試、日誌追蹤和 CDN 快取。",
     ["api", "versioning", "rest"], 0.87),

    ("api-02", "Pitfall", "Rate Limit 應在閘道層，非應用層",
     "在每個服務自行實作 rate limit 會造成狀態不一致（多副本）。應統一在 API Gateway 或 Nginx 層做限流。",
     ["api", "rate-limit", "security"], 0.91),

    ("api-03", "Rule",    "錯誤回應必須包含機器可讀的 error code",
     "HTTP 狀態碼不夠用。回應 body 必須有 {error: \"USER_NOT_FOUND\"}，讓 client 能程式化處理，不依賴 message 字串。",
     ["api", "error-handling", "rest"], 0.89),

    ("api-04", "Decision","JWT 使用 RS256 非對稱簽名",
     "RS256 允許服務只持有公鑰即可驗證 token，不需要共享秘密。HS256 的共享密鑰一旦洩漏所有服務都受影響。",
     ["api", "jwt", "security", "authentication"], 0.94),

    ("api-05", "Rule",    "CORS preflight 快取設定 max-age",
     "Access-Control-Max-Age 應設定為至少 86400（一天），避免瀏覽器每次跨域請求都發送 preflight OPTIONS。",
     ["api", "cors", "performance"], 0.82),

    # ── Python 實務 ──────────────────────────────────────────────
    ("py-01", "Pitfall",  "asyncio 中避免在 async def 裡呼叫同步 I/O",
     "在 async 函式中直接呼叫 requests.get() 或 open() 等同步阻塞呼叫會凍結整個 event loop。應使用 httpx.AsyncClient 或 aiofiles。",
     ["python", "async", "performance"], 0.93),

    ("py-02", "Rule",     "型別注解使用 from __future__ import annotations",
     "Python 3.9 以下的 list[str] 語法在 runtime 會失敗。統一在模組頂部加 from __future__ import annotations 延遲求值。",
     ["python", "type-hints", "compatibility"], 0.88),

    ("py-03", "Pitfall",  "Mock patch 路徑必須是使用端的路徑",
     "mock.patch('requests.get') 無法攔截已 import 的模組。應 patch 使用端：mock.patch('mymodule.requests.get')。",
     ["python", "testing", "mock"], 0.94),

    ("py-04", "Rule",     "logging 使用 getLogger(__name__) 不用 root logger",
     "直接呼叫 logging.info() 寫入 root logger 會污染所有模組的日誌輸出。每個模組應建立自己的 logger = logging.getLogger(__name__)。",
     ["python", "logging", "best-practice"], 0.90),

    ("py-05", "Decision", "依賴管理使用 pyproject.toml 取代 requirements.txt",
     "requirements.txt 無法表達開發/生產依賴分離、版本範圍語意。pyproject.toml + pip-tools 或 Poetry 提供更好的重現性。",
     ["python", "dependency", "packaging"], 0.85),

    # ── 部署與基礎設施 ───────────────────────────────────────────
    ("dep-01", "Rule",    "機密不可寫入 Dockerfile 或 image layer",
     "ENV 指令設定的值會永久保存在 image layer 中，docker history 可直接讀取。機密必須在 runtime 從環境變數或 secret manager 注入。",
     ["deployment", "docker", "security", "secrets"], 0.96),

    ("dep-02", "Pitfall", "健康檢查端點不可依賴外部服務",
     "/healthz 若去連接資料庫或外部 API，外部依賴掛了會導致整個服務被 load balancer 摘除。健康檢查只驗證自身狀態。",
     ["deployment", "health-check", "reliability"], 0.91),

    ("dep-03", "Rule",    "Rollback 計劃必須在部署前準備好",
     "每次部署前需確認回滾方式：前一個版本的 image tag、migration 的 down script、feature flag 關閉路徑。沒有回滾計劃的部署是賭博。",
     ["deployment", "rollback", "reliability"], 0.93),

    ("dep-04", "Decision","環境差異用環境變數，不用 if env == 'production'",
     "程式碼中的環境判斷是技術債的溫床。12-factor app 原則：所有環境差異（DB URL、log level、feature toggle）透過環境變數注入。",
     ["deployment", "configuration", "twelve-factor"], 0.89),

    ("dep-05", "Pitfall", "Docker COPY 指令順序影響 build cache",
     "COPY . . 放在 RUN pip install 之前會讓任何程式碼修改都使 pip install 快取失效。應先 COPY 依賴描述檔、安裝後再 COPY 程式碼。",
     ["deployment", "docker", "performance"], 0.87),

    # ── 測試策略 ─────────────────────────────────────────────────
    ("test-01", "Rule",   "整合測試使用真實資料庫，不用 mock",
     "Mock 資料庫的測試無法捕捉查詢語法錯誤、索引問題和 migration 失敗。整合測試必須連接真實的測試資料庫。",
     ["testing", "integration", "database"], 0.95),

    ("test-02", "Rule",   "每個測試必須獨立，不依賴執行順序",
     "測試間的共享狀態（全域變數、靜態快取、資料庫殘留資料）是不穩定測試的根源。每個測試前後需清理狀態。",
     ["testing", "isolation", "best-practice"], 0.92),

    ("test-03", "Pitfall","測試檔案不可 import 被測模組的私有函式",
     "測試 _private_func() 把測試與實作細節耦合。實作重構時大量測試失敗，但行為未變。只測試公開介面。",
     ["testing", "coupling", "best-practice"], 0.88),

    ("test-04", "Decision","使用 pytest fixture 管理測試資源生命週期",
     "unittest setUp/tearDown 無法組合。pytest fixture 支援 scope（session/module/function）和依賴注入，適合複雜測試環境。",
     ["testing", "pytest", "fixture"], 0.86),

    ("test-05", "Rule",   "測試名稱描述行為，非實作",
     "test_get_user() 不如 test_returns_404_when_user_not_found()。好的測試名稱是活文件，失敗時立即知道哪個行為壞了。",
     ["testing", "naming", "documentation"], 0.83),

    # ── 資安 ────────────────────────────────────────────────────
    ("sec-01", "Rule",    "SQL 查詢必須使用參數化，永不字串拼接",
     "f'SELECT * FROM users WHERE id={user_id}' 是 SQL injection 漏洞。ORM 或 cursor.execute(sql, (id,)) 的佔位符是唯一安全做法。",
     ["security", "sql", "injection"], 0.97),

    ("sec-02", "Pitfall", "前端輸出未做 HTML 跳脫導致 XSS",
     "直接將使用者輸入插入 innerHTML 或伺服器端 template 未跳脫，讓攻擊者注入 <script>。使用框架提供的跳脫機制或 DOMPurify。",
     ["security", "xss", "frontend"], 0.95),

    ("sec-03", "Rule",    "Secret 不可 commit 進 git 倉庫",
     "即使立即刪除，git history 仍保留。一旦 push 到遠端必須視為已洩漏，立即輪換。使用 .gitignore + pre-commit hook 防止意外提交。",
     ["security", "secrets", "git"], 0.96),

    ("sec-04", "Rule",    "輸入驗證在服務邊界，不信任任何外部來源",
     "前端驗證只是 UX，後端必須獨立驗證所有輸入。API、webhook payload、message queue 的資料都是外部來源，必須驗證型別、長度、格式。",
     ["security", "validation", "input"], 0.91),

    ("sec-05", "Pitfall", "CSRF token 用 SameSite=Strict 可簡化防禦",
     "傳統 CSRF token 需要後端狀態。現代瀏覽器支援 Set-Cookie: SameSite=Strict，大幅簡化 CSRF 防禦，但仍需注意舊瀏覽器相容性。",
     ["security", "csrf", "cookie"], 0.84),

    # ── 效能 ────────────────────────────────────────────────────
    ("perf-01","Rule",    "快取鍵必須包含所有影響結果的變數",
     "cache.get('user_profile') 如果有多用戶會 key collision。快取鍵應包含 user_id、版本等所有影響回傳值的因素：user_profile:{user_id}:{version}。",
     ["performance", "caching", "redis"], 0.90),

    ("perf-02","Pitfall", "分頁使用 OFFSET 在大資料集效能差",
     "SELECT * LIMIT 20 OFFSET 10000 需掃描前 10020 列再丟棄。cursor-based pagination（WHERE id > last_id LIMIT 20）效能是 O(1)。",
     ["performance", "pagination", "database"], 0.92),

    ("perf-03","Rule",    "N+1 問題的根本解法是 DataLoader 模式",
     "GraphQL 的 N+1 需要 DataLoader（批次 + 快取）。REST 的 N+1 用 eager loading。兩者核心都是把多次查詢合批成一次。",
     ["performance", "dataloader", "graphql"], 0.87),

    ("perf-04","Decision","圖片使用 CDN + WebP 格式，不從應用伺服器直接提供",
     "圖片從應用伺服器提供佔用頻寬和 CPU，且無法邊緣快取。CDN + 現代格式（WebP/AVIF）可減少 30-50% 圖片體積。",
     ["performance", "cdn", "images"], 0.83),

    ("perf-05","Rule",    "資料庫 EXPLAIN ANALYZE 每個慢查詢",
     "優化前必須先看 EXPLAIN ANALYZE 輸出。「感覺很慢」可能是索引缺失、表統計過舊或查詢計畫錯誤，對症下藥。",
     ["performance", "database", "profiling"], 0.89),

    # ── 架構設計 ────────────────────────────────────────────────
    ("arch-01","Rule",    "依賴方向：外層依賴內層，內層不知道外層",
     "Clean Architecture / Hexagonal：domain 層不依賴 framework 和資料庫。依賴反轉透過介面（interface）實現，讓核心邏輯可獨立測試。",
     ["architecture", "clean-architecture", "solid"], 0.91),

    ("arch-02","Pitfall", "分散式系統中使用本地事務邊界跨服務",
     "微服務間不可用分散式 transaction（2PC 太脆弱）。應使用 Saga 模式或最終一致性設計。每個服務只管自己的資料，跨服務用事件補償。",
     ["architecture", "microservices", "distributed"], 0.94),

    ("arch-03","Decision","事件驅動架構中事件必須是過去式命名",
     "UserCreated、OrderShipped 是事件。CreateUser 是命令。混用命名讓 consumer 無法區分「已發生的事實」和「請求執行的動作」。",
     ["architecture", "event-driven", "naming"], 0.85),

    ("arch-04","Rule",    "每個服務只有一個理由改變（SRP）",
     "Single Responsibility Principle：若一個服務因為業務規則、資料儲存和通知邏輯都需要改，它承擔了太多責任。拆分依據是「誰會要求這個服務改變」。",
     ["architecture", "solid", "srp"], 0.88),

    ("arch-05","Decision","配置注入使用環境變數，代碼注入使用 DI container",
     "環境變數管 DB URL、API keys；DI container（FastAPI Depends、injector）管物件圖的組裝。兩者混淆導致測試困難和配置複雜。",
     ["architecture", "dependency-injection", "configuration"], 0.87),

    # ── 程式碼品質 ───────────────────────────────────────────────
    ("qual-01","Rule",    "函式長度超過 20 行需考慮拆分",
     "20 行是粗略門檻，真正標準是：能否給函式一個清楚的名字？如果需要「且」或「或」來描述功能，就該拆。",
     ["code-quality", "refactoring", "naming"], 0.86),

    ("qual-02","Pitfall", "Magic number 應改為命名常數",
     "if status == 3 讓閱讀者無法理解 3 的意義。STATUS_ACTIVE = 3 或 class Status(Enum) 讓代碼自我記錄，修改時不會遺漏。",
     ["code-quality", "naming", "readability"], 0.89),

    ("qual-03","Rule",    "Code review 重點在設計，不在風格",
     "縮排、命名風格交給 linter（black、flake8）自動處理。Code review 應聚焦：設計是否合理？邊界情況是否處理？是否有更簡單的方案？",
     ["code-quality", "code-review", "process"], 0.84),

    ("qual-04","Decision","公開 API 文件用 docstring，內部邏輯用 inline comment",
     "docstring 用於函式/類別的公開介面說明（是什麼、為什麼）。# 是用於複雜邏輯的局部解釋（怎麼做）。過多 inline comment 是重構信號。",
     ["code-quality", "documentation", "comments"], 0.82),

    ("qual-05","Rule",    "重構必須有測試覆蓋才能安全進行",
     "沒有測試直接重構是在走鋼索。先補測試（characterization tests）確保現有行為，再安全重構。Boy Scout Rule：讓程式比你看到時更乾淨。",
     ["code-quality", "refactoring", "testing"], 0.90),

    # ── CI/CD 流程 ───────────────────────────────────────────────
    ("ci-01", "Rule",     "CI pipeline 失敗必須阻斷 merge",
     "CI 只是警告而非阻斷，工程師會選擇性忽略。pipeline 必須是 merge 的硬性 gate：測試失敗、lint 錯誤、安全掃描警告都不可合入。",
     ["ci-cd", "pipeline", "process"], 0.93),

    ("ci-02", "Decision", "Feature flag 用於風險部署，不用長期 branch",
     "長期 feature branch 製造合併地獄。Feature flag 讓未完成的功能跟著 main 一起部署但隱藏，消除整合衝突，支援 trunk-based development。",
     ["ci-cd", "feature-flag", "deployment"], 0.88),

    ("ci-03", "Pitfall",  "Canary 部署未設定自動回滾指標",
     "Canary 若沒有自動監控 error rate / latency 並在超標時自動回滾，就只是手動部署加風險。必須定義觀察窗口和回滾 threshold。",
     ["ci-cd", "canary", "deployment", "monitoring"], 0.91),

    ("ci-04", "Rule",     "Build artifact 一次建置，多環境部署",
     "不同環境不應重新 build。一個 docker image 從 staging 推到 production，環境差異用環境變數注入。確保測試通過的程式碼就是部署的程式碼。",
     ["ci-cd", "deployment", "immutable-infrastructure"], 0.92),

    ("ci-05", "Pitfall",  "Blue-Green 部署切換前必須確認 DB schema 相容",
     "Blue-Green 切換瞬間新舊版本同時運行。新版本若有破壞性 schema 變更（欄位刪除、型別修改），舊版本請求會失敗。必須先完成 schema 前向相容遷移。",
     ["ci-cd", "blue-green", "database", "deployment"], 0.94),
]

assert len(NODES) == 50, f"Expected 50 nodes, got {len(NODES)}"


# ══════════════════════════════════════════════════════════════════
#  20 查詢 + 預期節點
#  格式：(query, expected_node_id, expected_title_fragment)
# ══════════════════════════════════════════════════════════════════

QUERIES: list[tuple[str, str, str]] = [
    # 資料庫
    ("ORM 查詢在迴圈裡速度很慢，懷疑是 N+1 問題",       "db-01", "N+1 查詢問題"),
    ("資料庫 migration 失敗，新舊版本同時跑",            "db-02", "Migration 必須向前相容"),
    ("transaction 裡面呼叫外部 API 導致 deadlock",       "db-04", "交易邊界不跨越網路"),
    ("PostgreSQL JOIN 查詢沒有外鍵索引導致全表掃描",     "db-05", "未建索引的外鍵"),

    # API
    ("如何設計 API 版本號，放路徑還是 Header",           "api-01", "API 版本號在路徑"),
    ("JWT 簽名應該用 HS256 還是 RS256",                  "api-04", "JWT 使用 RS256"),
    ("CORS preflight OPTIONS 請求太頻繁影響效能",        "api-05", "CORS preflight 快取"),

    # Python
    ("async 函式裡用 requests 庫阻塞了 event loop",     "py-01", "asyncio 中避免在 async def"),
    ("mock.patch 無法攔截到目標函式",                    "py-03", "Mock patch 路徑必須是使用端"),
    ("如何設定 logging 讓各模組有自己的 logger",         "py-04", "logging 使用 getLogger"),

    # 部署
    ("Docker image 裡包含了 API key 和密碼",             "dep-01", "機密不可寫入 Dockerfile"),
    ("Kubernetes 健康檢查連不到資料庫就把 pod 摘除",     "dep-02", "健康檢查端點不可依賴外部"),
    ("多個環境用 if env == production 判斷設定",         "dep-04", "環境差異用環境變數"),

    # 測試
    ("整合測試 mock 資料庫通過但生產環境 migration 失敗","test-01", "整合測試使用真實資料庫"),
    ("測試執行順序不同結果不同，不穩定的測試",           "test-02", "每個測試必須獨立"),
    ("pytest 的 fixture 怎麼管理測試資源的生命週期",     "test-04", "pytest fixture"),

    # 資安
    ("使用者輸入直接拼接進 SQL 查詢字串",                "sec-01", "SQL 查詢必須使用參數化"),
    ("如何防止把 secret 和 API key 不小心 commit 進去", "sec-03", "Secret 不可 commit"),

    # 效能
    ("分頁查詢用 OFFSET 在百萬資料集越來越慢",           "perf-02", "分頁使用 OFFSET"),

    # CI/CD
    ("Blue-Green 部署後舊版本讀取新 schema 欄位失敗",   "ci-05", "Blue-Green 部署切換前"),
]

assert len(QUERIES) == 20, f"Expected 20 queries, got {len(QUERIES)}"


# ══════════════════════════════════════════════════════════════════
#  量測工具
# ══════════════════════════════════════════════════════════════════

class QueryResult(NamedTuple):
    query:          str
    expected_id:    str
    expected_frag:  str
    hit:            bool
    output_len:     int
    elapsed_ms:     int
    output_preview: str


def setup_test_brain() -> tuple[KnowledgeGraph, ContextEngineer, Path]:
    """建立含 50 個節點的測試知識庫（KnowledgeGraph + BrainDB + 向量索引）。"""
    tmp = Path(tempfile.mkdtemp())
    brain_dir = tmp / ".brain"
    brain_dir.mkdir()

    graph    = KnowledgeGraph(tmp)
    brain_db = BrainDB(brain_dir)
    embedder = get_embedder()

    for node_id, node_type, title, content, tags, conf in NODES:
        # FTS5 路徑
        graph.add_node(
            node_id, node_type, title,
            content=content,
            tags=tags,
            meta={"confidence": conf},
        )
        # BrainDB hybrid search 路徑
        brain_db.add_node(
            node_id, node_type, title,
            content=content,
            tags=tags,
            confidence=conf,
        )
        # 向量索引（有 embedder 才建）
        if embedder:
            try:
                vec = embedder.embed(title + " " + content)
                if vec:
                    brain_db.add_vector(node_id, vec)
            except Exception:
                pass

    graph._conn.commit()

    engine = ContextEngineer(graph, brain_dir=brain_dir, brain_db=brain_db)
    return graph, engine, tmp


def run_benchmark() -> list[QueryResult]:
    """執行 20 個查詢並收集結果。"""
    graph, engine, tmp = setup_test_brain()
    results = []

    for query, expected_id, expected_frag in QUERIES:
        t0 = time.monotonic()
        output = engine.build(query)
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        # 召回判斷：預期節點的 title 片段是否出現在輸出中
        hit = expected_frag in output

        results.append(QueryResult(
            query         = query,
            expected_id   = expected_id,
            expected_frag = expected_frag,
            hit           = hit,
            output_len    = len(output),
            elapsed_ms    = elapsed_ms,
            output_preview= output[:200].replace("\n", " "),
        ))

    return results


def detect_embedder() -> str:
    """偵測 ContextEngineer 實際使用的 embedder。"""
    emb = get_embedder()
    if emb is None:
        return "None（純 FTS5 模式）"
    return type(emb).__name__


def print_report(results: list[QueryResult]) -> None:
    hits     = sum(1 for r in results if r.hit)
    total    = len(results)
    recall   = hits / total
    avg_ms   = sum(r.elapsed_ms for r in results) / total
    embedder = detect_embedder()

    target_60 = "✅" if recall >= 0.60 else "❌"
    target_40 = "✅" if recall >= 0.40 else "❌"

    print("\n" + "═" * 70)
    print("  UNQ-03 基準測試報告 — get_context 召回率")
    print("═" * 70)
    print(f"  知識庫規模  : {len(NODES)} 個節點")
    print(f"  查詢數      : {total}")
    print(f"  Embedder    : {embedder}")
    print(f"  平均延遲    : {avg_ms:.0f} ms / query")
    print()
    print(f"  ┌─────────────────────────────────────────┐")
    print(f"  │  召回率 : {recall*100:5.1f}%  ({hits}/{total} 命中)        │")
    print(f"  │  目標 ≥ 60% (sentence-transformers) {target_60}   │")
    print(f"  │  目標 ≥ 40% (LocalTFIDF)           {target_40}   │")
    print(f"  └─────────────────────────────────────────┘")
    print()

    # 詳細結果
    print("  詳細查詢結果：")
    print(f"  {'#':>2}  {'狀態':<4}  {'預期節點':<12}  查詢")
    print("  " + "─" * 65)
    for i, r in enumerate(results, 1):
        icon  = "✅" if r.hit else "❌"
        query = textwrap.shorten(r.query, width=42, placeholder="…")
        print(f"  {i:>2}  {icon}   {r.expected_id:<12}  {query}")

    # 失敗分析
    misses = [r for r in results if not r.hit]
    if misses:
        print()
        print(f"  未命中查詢分析（{len(misses)} 個）：")
        for r in misses:
            print(f"    • [{r.expected_id}] {r.expected_frag}")
            print(f"      查詢: {r.query}")
            preview = r.output_preview[:120]
            print(f"      輸出: {preview}")
            print()

    # 結論
    print("═" * 70)
    if recall >= 0.60:
        verdict = "主要 context 來源 ✅  召回率達標，可信賴作為 Agent 的主要知識注入"
    elif recall >= 0.40:
        verdict = "補充參考 ⚠️   FTS5/LocalTFIDF 模式下可用，建議安裝 sentence-transformers 提升到 60%+"
    else:
        verdict = "需改善 ❌  召回率低於 40%，不建議作為主要 context 來源"
    print(f"  結論: {verdict}")
    print("═" * 70 + "\n")

    return recall


# ══════════════════════════════════════════════════════════════════
#  主程式
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n正在建立 50 節點測試知識庫並執行 20 個查詢...")
    results = run_benchmark()
    print_report(results)
