"""
project_brain/synonyms.py — REF-02: single source of truth for synonym map.

Both brain_db.py and context.py import from here.
To add synonyms, edit this file only.
"""

SYNONYM_MAP: dict = {
    # 認證 / 授權
    "token":         ["jwt","bearer","access_token","令牌","token"],
    "jwt":           ["token","bearer","令牌","rs256","hs256","驗證","auth"],
    "令牌":           ["jwt","token","bearer","驗證","auth","認證"],
    "認證":           ["jwt","token","auth","authentication","驗證","authorize"],
    "授權":           ["auth","authorization","rbac","permission","權限"],
    "auth":          ["jwt","token","認證","授權","authentication"],
    # 支付
    "支付":           ["stripe","payment","charge","扣款","收費"],
    "stripe":        ["webhook","payment","charge","idempotency","支付"],
    "webhook":       ["stripe","idempotency","冪等","callback","回調"],
    "冪等":           ["webhook","idempotency","idempotent","重複","duplicate"],
    "扣款":           ["stripe","charge","payment","支付","重複"],
    # 資料庫
    "db":            ["database","postgres","postgresql","mysql","sqlite","資料庫"],
    "database":      ["db","postgres","postgresql","sql","資料庫"],
    "資料庫":         ["postgres","postgresql","mysql","mongodb","sqlite","db","database"],
    "postgresql":    ["postgres","db","database","sql","acid","連線池","connection"],
    "postgres":      ["postgresql","db","database","sql","acid","連線池"],
    "連線":           ["connection","pool","連線池","database","db"],
    "資料庫連線":      ["connection","pool","postgresql","mysql","db"],
    "關係型":         ["postgresql","mysql","sql","acid","relational","table"],
    "migration":     ["遷移","migrate","schema","rollback","資料庫","升級"],
    "遷移":           ["migration","migrate","schema","rollback","資料庫"],
    # API 版本化（BUG-E01 fix）
    "版本":          ["versioning", "v1", "url", "path", "routing", "api version"],
    "版本號":        ["versioning", "api version", "url", "path", "v1"],
    "路徑":          ["url", "path", "endpoint", "route", "routing"],
    "header":        ["http header", "accept", "content-type", "versioning"],
    "versioning":    ["版本", "版本號", "url", "path", "v1"],
    # 通用技術
    "api":           ["endpoint","rest","http","request","response","接口"],
    "cache":         ["redis","memcached","快取","緩存"],
    "快取":           ["cache","redis","ttl","expire","緩存"],
    "部署":           ["docker","deploy","kubernetes","k8s","container","ci"],
    "容器":           ["docker","container","k8s","kubernetes","部署","image"],
    "kubernetes":    ["k8s","container","docker","部署","pod","deploy"],
    "效能":           ["performance","latency","throughput","slow","timeout","優化"],
    "安全":           ["security","auth","xss","sql injection","ssl","tls","https"],
    "測試":           ["test","unit","integration","e2e","mock","assert"],
    "test":          ["unittest","pytest","mock","測試"],
    "錯誤":           ["error","exception","bug","failure","crash","問題"],
    "error":         ["exception","bug","failure","crash"],
    "問題":           ["error","bug","issue","problem","failure","crash"],
    # 非同步 / 並發
    "非同步":         ["async","await","concurrency","thread","並發","event loop"],
    "async":         ["非同步","await","concurrency","thread","asyncio"],
    "並發":           ["concurrency","race condition","lock","thread","async"],
    # 訊息佇列
    "訊息佇列":        ["kafka","rabbitmq","queue","message","非同步","pub/sub"],
    "kafka":         ["rabbitmq","queue","message","訊息佇列","consumer"],
    # 重試 / 容錯
    "重試":           ["retry","backoff","冪等","timeout","超時"],
    "retry":         ["重試","backoff","冪等","idempotent","timeout"],
    # 日誌 / 監控
    "日誌":           ["log","logging","logger","monitor","trace"],
    "log":           ["logging","logger","日誌","monitor","trace"],
    "監控":           ["monitor","prometheus","grafana","alert","metric"],
    # 配置
    "配置":           ["config","env","環境變數","設定",".env"],
    "config":        ["配置","env","環境變數",".env","settings"],
}
