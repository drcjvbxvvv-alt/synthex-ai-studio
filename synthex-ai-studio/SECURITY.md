# SYNTHEX AI STUDIO — 安全設計與最佳實踐

---

## 目錄

- [設計理念](#設計理念)
- [命令注入防護](#命令注入防護)
- [路徑穿越防護](#路徑穿越防護)
- [SSRF 防護](#ssrf-防護)
- [API 安全](#api-安全)
- [記憶體與資料安全](#記憶體與資料安全)
- [Project Brain 安全](#project-brain-安全)
- [使用建議](#使用建議)
- [已知限制](#已知限制)
- [漏洞回報](#漏洞回報)

---

## 設計理念

SYNTHEX AI STUDIO 在設計時遵循以下安全原則：

**安全是設計，不是事後補丁。** 路徑驗證、命令過濾、SSRF 防護都在第一個版本就整合進去，不是功能完成後再想起來的。

**最小權限原則。** Agent 只能操作 `workdir` 指定的目錄，無法存取系統其他位置。工具集分級，高層管理 Agent 只有讀取工具，不能執行命令。

**Defense in Depth（縱深防禦）。** 每個危險操作有多層防護：型別驗證 → 白名單過濾 → 路徑解析 → 邊界確認。一層失效，下一層還在。

**失敗安全（Fail Safe）。** 驗證失敗時拒絕操作，不是嘗試繼續。錯誤訊息不洩漏系統內部資訊（路徑、stack trace）。

---

## 命令注入防護

### 核心設計：禁用 `shell=True`

所有外部命令執行使用 argv 陣列（不通過 shell 解析），從根本上消除 Shell Injection：

```python
# ✓ 正確：argv 陣列，不通過 shell
subprocess.run(["git", "log", "--oneline", "-20"], capture_output=True)

# ✗ 錯誤：shell=True，攻擊者可注入
# subprocess.run(f"git log {user_input}", shell=True)  # 危險！
```

攻擊者即使能控制參數，也無法注入 `;rm -rf /` 這類 shell 指令。

### 危險命令黑名單

即使是 argv 陣列模式，以下模式仍會被過濾：

```python
DANGEROUS_PATTERNS = [
    r'rm\s+-rf\s+[/~]',        # 刪除根目錄或 home 目錄
    r'curl\s+.*\|\s*(ba)?sh',  # 管道執行遠端腳本
    r'wget\s+.*-O\s*-\s*\|',   # wget 管道
    r'>\s*/dev/sd',             # 覆寫磁碟裝置
    r'mkfs\.',                  # 格式化磁碟
    r'dd\s+if=',                # 磁碟底層操作
    r'chmod\s+777\s+/',         # 開放根目錄權限
    r':(){ :|:& };:',           # Fork Bomb
    r'python.*-c.*exec',        # Python 任意執行
    r'eval\s+.*\$\(',           # eval 命令替換
]
```

遇到任一模式，立即拒絕並記錄到日誌，不執行。

### Git 命令白名單

`git_run` 工具只允許常用的安全命令：

```python
GIT_ALLOWED_COMMANDS = {
    "status", "add", "commit", "push", "pull", "log",
    "diff", "branch", "checkout", "merge", "stash",
    "fetch", "clone", "init", "remote", "tag", "show",
}
```

`git gc --aggressive --prune=all` 這類管理命令需要用 `run_command` 明確呼叫。

---

## 路徑穿越防護

### 三道關卡

所有涉及檔案路徑的操作都經過三道驗證：

```python
def _validate_path(workdir: Path, user_path: str) -> Path:
    # 關卡 1：型別和長度驗證
    if not isinstance(user_path, str) or len(user_path) > 4096:
        raise ValueError("無效路徑")

    # 關卡 2：os.path.normpath 解析（消除 ../ 和符號連結）
    resolved = Path(user_path).resolve()

    # 關卡 3：確認在 workdir 內
    if not str(resolved).startswith(str(workdir)):
        raise SecurityError(f"路徑穿越攻擊：{user_path}")

    return resolved
```

**範例攻擊被阻擋：**

```
用戶輸入：../../etc/passwd
解析後：  /etc/passwd
workdir：/home/user/projects/my-app
→ /etc/passwd 不在 workdir 內 → 拒絕
```

### Project Brain 路徑驗證

L1 工作記憶的路徑還有額外限制：

```python
PATH_PREFIX = "/memories"   # 所有路徑必須以此開頭

def _validate_memory_path(path: str) -> str:
    if not path.startswith(PATH_PREFIX):
        raise ValueError(f"路徑必須以 {PATH_PREFIX} 開頭")

    # 防止穿越到 /memories 以外
    normalized = os.path.normpath(path)
    if not normalized.startswith(PATH_PREFIX):
        raise ValueError("路徑穿越被阻擋")

    return normalized
```

---

## SSRF 防護

Computer Use 功能（`core/computer_use.py`）允許 Agent 操作瀏覽器，需要 URL 安全驗證：

### 私有 IP 封鎖

```python
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),       # 私有網路
    ipaddress.ip_network("172.16.0.0/12"),     # 私有網路
    ipaddress.ip_network("192.168.0.0/16"),    # 私有網路
    ipaddress.ip_network("127.0.0.0/8"),       # loopback
    ipaddress.ip_network("169.254.0.0/16"),    # link-local（AWS metadata）
    ipaddress.ip_network("0.0.0.0/8"),         # 保留
    ipaddress.ip_network("::1/128"),           # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),          # IPv6 私有
]

def validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)

    # 只允許 https（禁止 http、file://、ftp:// 等）
    if parsed.scheme != "https":
        raise SecurityError("只允許 HTTPS URL")

    # 解析 hostname 到 IP，確認不是私有位址
    ip = socket.gethostbyname(parsed.hostname)
    for network in BLOCKED_IP_RANGES:
        if ipaddress.ip_address(ip) in network:
            raise SecurityError(f"禁止存取私有 IP: {ip}")
```

這樣可以防止 Agent 被引導去存取 `http://169.254.169.254/latest/meta-data/`（AWS Instance Metadata）或內網服務。

---

## API 安全

### Rate Limiting（Token Bucket）

```python
class TokenBucketRateLimiter:
    def __init__(self, rate: float, capacity: float):
        # rate：每秒補充的 token 數
        # capacity：桶的最大容量

    def acquire(self, tokens: int = 1) -> float:
        """
        嘗試消耗 tokens 個 token。
        如果桶不夠，返回需要等待的秒數。
        調用方負責 time.sleep()。
        """
```

MCP Server（`core/brain/mcp_server.py`、`core/brain/graphiti_mcp_server.py`）：

```python
RATE_LIMIT_RPM = 60   # 每分鐘最多 60 次呼叫

def _rate_check() -> None:
    """滑動視窗 Rate Limiting"""
    now    = time.monotonic()
    cutoff = now - 60.0
    _call_times[:] = [t for t in _call_times if t > cutoff]
    if len(_call_times) >= RATE_LIMIT_RPM:
        raise RuntimeError(f"Rate limit exceeded")
    _call_times.append(now)
```

### CircuitBreaker（故障隔離）

防止 API 暫時不可用時，系統不斷重試浪費資源：

```python
class CircuitBreaker:
    """
    States:
    CLOSED  → 正常，請求通過
    OPEN    → 故障，請求立即失敗（不等待）
    HALF    → 嘗試恢復，少量請求通過測試
    """
    failure_threshold: int   = 5     # 連續失敗 5 次 → OPEN
    recovery_timeout:  float = 30.0  # OPEN 30 秒後嘗試 HALF
```

### API Key 保護

```python
# read_env 工具只顯示 key 名稱，不顯示值
def read_env(workdir: Path) -> dict:
    return {
        "keys": list(env_vars.keys()),   # ← 只返回 key 名稱
        # 不包含 values                  # ← 防止意外洩漏
    }
```

---

## 記憶體與資料安全

### SQLite WAL 模式

所有 SQLite 資料庫使用 WAL（Write-Ahead Logging）模式：

```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;  -- 並發寫入等待 5 秒而不是直接失敗
```

WAL 模式提供：
- 並發讀取（多個 Reader 不阻擋）
- 安全的並發寫入（Writer 不阻擋 Reader）
- 崩潰恢復（WAL 日誌可用來重建）

### 原子寫入（PhaseCheckpoint）

Checkpoint 使用 write-then-rename 模式防止中途崩潰損毀：

```python
# 先寫 .tmp，成功後才 rename 覆蓋
tmp_path = checkpoint_path.with_suffix('.tmp')
tmp_path.write_text(json.dumps(data), encoding='utf-8')
tmp_path.rename(checkpoint_path)  # 原子操作（POSIX 保證）
```

### 記憶體大小限制

防止意外的超大資料導致 OOM：

```python
# L1 工作記憶
MAX_MEMORY_SIZE_CHARS = 32_000    # 單文件最大 32K 字元
MAX_TOTAL_MEMORIES    = 500       # 最多 500 個文件

# Project Brain 查詢結果
MAX_CONTEXT_TOKENS    = 3_000     # Context 注入最多 3K tokens

# run_command 輸出
MAX_OUTPUT_BYTES      = 50 * 1024 # 輸出最多 50KB
```

---

## Project Brain 安全

### L1 — Prompt Injection 防護（KnowledgeValidator）

知識驗證時，送入 Claude 的內容先過濾 Prompt Injection 嘗試：

```python
_INJECTION_PATTERNS = re.compile(
    r"\b(ignore|forget|override|disregard|pretend|jailbreak|"
    r"act as|new instruction|system:|<\|im_start\|>)\b",
    re.IGNORECASE,
)

def _validate_with_claude(self, node: dict):
    safe_content = _INJECTION_PATTERNS.sub("[filtered]", content)
    safe_title   = _INJECTION_PATTERNS.sub("[filtered]", title)
    # 用過濾後的內容組成 prompt
```

### L2 / L3 — PII 過濾（Federation）

跨組織知識分享前，自動偵測和拒絕包含個人資訊的知識：

```python
_PII_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z]{2,}\b'),  # email
    re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),                        # IP
    re.compile(r'(?i)\b(password|secret|token|api.?key)\s*[:=]\s*\S+'), # 密鑰
    re.compile(r'https?://\S+'),                                         # URL
    re.compile(r'sk-[a-zA-Z0-9]{20,}'),                                 # Anthropic key
]

def anonymize(self, node: dict) -> FederatedKnowledge | None:
    for pii in _PII_PATTERNS:
        if pii.search(title) or pii.search(content):
            return None  # 拒絕，不匿名化含 PII 的知識
```

### 差分隱私（KnowledgeFederation）

跨組織分享時使用 Laplace 機制，讓單一知識的存在無法被統計確認：

```python
def _laplace_noise(self, value: float, epsilon: float = 1.0) -> float:
    """
    Laplace 機制：加入隱私保護雜訊
    scale = sensitivity / epsilon = 1.0 / 1.0 = 1.0
    epsilon=1.0 表示合理的隱私保護，值越小越隱私（但資訊失真也越大）
    """
    scale = 1.0 / epsilon
    noise = random.expovariate(1.0 / scale)
    noise *= (1 if random.random() > 0.5 else -1)
    return max(0.01, min(1.0, value + noise))
```

### Web UI 安全

Knowledge Graph Web UI 只綁定 localhost，不對外暴露：

```python
HOST = "127.0.0.1"  # 只接受本機連線，不是 0.0.0.0

app.run(host=HOST, port=7890, debug=False)
```

所有 API 端點使用參數化查詢（防止 SQL Injection）：

```python
# ✓ 正確：參數化查詢
rows = conn.execute(
    "SELECT * FROM nodes WHERE kind=? AND confidence>=?",
    (safe_kind, min_conf)
).fetchall()

# ✗ 錯誤：字串拼接（SQL Injection 風險）
# conn.execute(f"SELECT * FROM nodes WHERE kind='{kind}'")
```

---

## 使用建議

### API Key 管理

```bash
# ✓ 推薦：環境變數（不寫進程式碼）
export ANTHROPIC_API_KEY="sk-ant-..."

# ✓ 推薦：.env 檔案（在 .gitignore 裡）
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
echo ".env" >> .gitignore

# ✗ 避免：寫進程式碼或 commit
# api_key = "sk-ant-..."  # 這樣 API Key 會進 git history
```

### workdir 設定

SYNTHEX 只能操作 workdir 內的檔案，請確認設定正確：

```bash
# 設定到你的專案目錄，不是整個 home 或 /
python synthex.py workdir ~/projects/my-specific-project
```

不要把 workdir 設成 `/`、`~`、`/etc`，這會讓 Agent 有權讀取所有檔案。

### 刪除操作

所有刪除操作預設要求確認，使用 `--yes` 跳過：

```bash
python synthex.py do FORGE "清理 node_modules"
# → 系統顯示即將刪除的內容，要求確認

python synthex.py do FORGE "清理 node_modules" --yes
# → 自動確認，直接執行
```

在 CI/CD 環境中可以用 `--yes`，但互動環境建議不要跳過確認。

### Project Brain 資料保護

`.brain/` 目錄包含敏感的專案知識，已自動加到 `.gitignore`：

```
.brain/knowledge_graph.db    ← 知識圖譜，不提交
.brain/working_memory.db     ← 工作記憶，不提交
.brain/vectors/              ← 向量記憶，不提交
.brain/adrs/                 ← ADR 快照，提交 git（文件）
```

**不要手動把 `.brain/*.db` 加回 git tracking。** 這些 DB 可能包含 API Key、個人資訊等敏感內容。

---

## 已知限制

**`run_command` 的黑名單無法涵蓋所有危險命令。** 黑名單是加強防護，不是完整保護。如果需要更嚴格的隔離，建議在 Docker container 內使用 SYNTHEX，限制 container 的網路和檔案系統存取。

**Agent 的 Agentic 行為依賴 Claude 模型的判斷。** 如果模型被 Prompt 引導做出不正常的決策，工具層的保護是最後防線，不是第一防線。對於生產環境的操作，建議先在沙盒環境測試。

**記憶系統不對內容加密。** `.brain/knowledge_graph.db` 中的知識以明文儲存。如果需要加密，可以用加密的檔案系統（如 LUKS、VeraCrypt）掛載 `.brain/` 目錄。

**聯邦知識分享（KnowledgeFederation）目前使用本地 mock Hub。** v4.0 的差分隱私保護已實作，但真實的跨組織網路通訊還在規劃中。目前分享的知識只存在本地。

---

## 漏洞回報

如果你發現安全漏洞，請不要在 GitHub Issues 公開描述。

請透過以下方式私下回報：

1. 在 GitHub 使用 Security Advisories 功能（推薦）
2. 或直接聯絡維護者

回報時請包含：
- 漏洞描述和重現步驟
- 影響範圍（什麼條件下可以觸發）
- 如果有，概念驗證（PoC）程式碼
- 你認為嚴重程度如何，理由是什麼

我們承諾在 48 小時內確認收到，並在 7 天內提供初步評估。
