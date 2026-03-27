# SYNTHEX AI STUDIO — 貢獻指南

---

## 開始之前

SYNTHEX AI STUDIO 是一個活躍開發中的專案，歡迎各種形式的貢獻：

- 回報問題或安全漏洞
- 改善文件
- 新增或改善測試
- 新增 Agent 功能
- 修復 Bug
- 提出架構改善建議

---

## 開發環境設定

```bash
# 1. Clone 或解壓縮
cd ~/tools/synthex-ai-studio

# 2. 建立虛擬環境（強烈建議，避免套件衝突）
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# 3. 安裝依賴（含開發工具）
pip install -r requirements.txt
pip install pytest pytest-asyncio

# 4. 設定環境變數
export ANTHROPIC_API_KEY="sk-ant-..."

# 5. 執行測試確認環境正常
python -m pytest tests/ -v
# 應全部通過（139/139）
```

---

## 程式碼規範

### Python 風格

- **Python 版本：** 3.11+（使用 `from __future__ import annotations`）
- **型別提示：** 所有 public 函數必須有完整型別提示
- **Docstring：** 所有 public class 和函數必須有說明
- **行長度：** 最大 100 字元

```python
# ✅ 正確範例
from __future__ import annotations

def validate_path(path: str, workdir: Path) -> Path:
    """
    驗證路徑在 workdir 範圍內（防路徑穿越攻擊）。

    Args:
        path:    相對或絕對路徑字串
        workdir: 允許的根目錄

    Returns:
        解析後的絕對路徑

    Raises:
        SecurityError: 若路徑超出 workdir
    """
    resolved = (workdir / path).resolve()
    try:
        resolved.relative_to(workdir)
    except ValueError:
        raise SecurityError(f"路徑穿越攻擊：{path!r}")
    return resolved
```

### 安全規則（必須遵守）

1. **絕對禁止 `shell=True`**

```python
# ❌ 禁止
subprocess.run(cmd_string, shell=True)

# ✅ 必須使用 argv 陣列
subprocess.run(shlex.split(cmd_string))
# 或
subprocess.run(["npm", "run", "build"])
```

2. **所有外部輸入必須驗證**

```python
# ❌ 禁止直接使用
def process(user_input: str) -> str:
    return f"result: {user_input}"

# ✅ 先驗證
def process(user_input: str) -> str:
    cleaned = re.sub(r'[\x00-\x1f]', '', user_input)
    if len(cleaned) > MAX_INPUT_LEN:
        raise ValueError(f"輸入超過長度限制：{len(cleaned)}")
    return f"result: {cleaned}"
```

3. **新工具必須加入路徑驗證**

任何讀寫檔案的新工具，都必須呼叫 `_safe_path()` 驗證。

4. **網路請求必須驗證 URL**

任何發出 HTTP 請求的程式碼，都必須呼叫 `validate_url()` 防止 SSRF。

---

## 新增 Agent

### Step 1：在 `agents/all_agents.py` 定義

```python
class BOLT(BaseAgent):
    """韌體工程師 — 嵌入式系統專家"""
    name   = "BOLT"
    title  = "韌體工程師"
    dept   = "hardware"         # 部門：exec/engineering/product/ai/infra/qa/biz/hardware
    emoji  = "⚡"
    color  = "\033[33m"         # ANSI 色彩程式碼
    skills = [
        "MCU 程式設計",
        "RTOS（FreeRTOS/Zephyr）",
        "Bootloader 設計",
        "低功耗設計",
        "通訊協議（UART/SPI/I²C）",
    ]
    personality_traits = {
        "技術深度": 96,
        "穩定性優先": 95,
        "資源意識": 93,    # 記憶體和 CPU 都是稀缺資源
    }
    system_prompt = """
你是 BOLT，SYNTHEX AI STUDIO 的韌體工程師。
在嵌入式世界，每個位元都要斤斤計較。

【設計哲學】
- 記憶體是金子，不是水——開 malloc() 前三思
- 中斷服務例程越短越好，讓 RTOS 做調度
- 每個功能加上去，先問：這個在最差情況下的時間複雜度是什麼？
...
"""
```

### Step 2：加入到部門清單

在 `all_agents.py` 底部的 `ALL_AGENTS` 字典加入：

```python
ALL_AGENTS: dict[str, type[BaseAgent]] = {
    # ... 現有 Agent ...
    "BOLT": BOLT,
}
```

### Step 3：更新文件

- 在 `AGENTS.md` 加入新 Agent 的說明
- 在 `CLAUDE.md` 的角色表加入新 Agent

### Step 4：加入測試（建議）

```python
class TestBOLTAgent(unittest.TestCase):
    def test_bolt_init(self):
        """BOLT Agent 應正確初始化"""
        agent = BOLT(client=mock_client, workdir=tmp_path)
        self.assertEqual(agent.name, "BOLT")
        self.assertEqual(agent.dept, "hardware")
    
    def test_bolt_system_prompt(self):
        """BOLT 的 system_prompt 應包含韌體相關知識"""
        agent = BOLT(client=mock_client, workdir=tmp_path)
        self.assertIn("RTOS", agent.system_prompt)
```

---

## 新增測試

### 測試放置規則

所有測試放在 `tests/test_core.py`。按功能分組，每組用 `class TestXxx(unittest.TestCase)` 包裝。

### 測試命名規則

```python
def test_<行為>_<場景>_<預期結果>(self):
    # test_[被測函數]_[輸入條件]_[預期行為]
    
def test_safe_path_with_traversal_raises_security_error(self):
    """路徑包含 ../ 時應拋出 SecurityError"""
    
def test_rate_limiter_exceeds_limit_waits(self):
    """超過速率限制時應等待而非失敗"""
```

### 測試必須符合的標準

1. **不依賴外部服務**：測試不能呼叫 Anthropic API（使用 Mock）
2. **不依賴網路**：測試必須在離線環境下通過
3. **使用 `tempfile.mkdtemp()`**：不使用固定路徑
4. **清理暫存檔**：測試結束後清理 `tmpdir`
5. **執行速度**：單個測試不超過 5 秒

```python
class TestNewFeature(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # 初始化測試所需的物件
    
    def tearDown(self):
        # 清理（若有全域副作用）
        pass
    
    def test_feature_happy_path(self):
        """正常情況下應正確執行"""
        result = my_function(self.tmpdir)
        self.assertEqual(result, "expected")
    
    def test_feature_error_case(self):
        """錯誤輸入應拋出正確的例外"""
        with self.assertRaises(ValueError):
            my_function(invalid_input)
```

---

## 修改 Project Brain

Project Brain 的模組在 `core/brain/`。修改時注意：

### 修改 L3 知識圖譜（`graph.py`）

Schema 更改需要遷移腳本（`.brain/` 目錄中的 SQLite）：

```python
def migrate_v3_to_v4(brain_dir: Path) -> None:
    """
    遷移 L3 知識圖譜從 v3 到 v4。
    新增 is_invalidated 欄位支援知識驗證功能。
    """
    conn = sqlite3.connect(str(brain_dir / "knowledge_graph.db"))
    try:
        conn.execute("ALTER TABLE nodes ADD COLUMN is_invalidated INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # 欄位已存在，跳過
    finally:
        conn.close()
```

### 修改 Brain Router（`router.py`）

Router 修改後必須更新對應測試：

```python
# 確保三層查詢仍然正常工作
class TestBrainRouter(unittest.TestCase):
    def test_query_returns_three_layer_context(self):
        ...
    
    def test_l1_takes_priority_for_recent_tasks(self):
        ...
```

---

## Pull Request / 提交規範

### Commit 訊息格式

```
<type>: <subject>

[可選的 body]

[可選的 footer]
```

**type：**
- `feat`: 新功能
- `fix`: Bug 修復
- `security`: 安全修復
- `docs`: 文件更新
- `test`: 測試相關
- `refactor`: 重構（不影響功能）
- `perf`: 效能優化
- `chore`: 工具配置等雜項

**範例：**
```
feat: 新增 BOLT 韌體工程師 Agent

加入嵌入式系統專家 BOLT，支援 MCU 程式設計、RTOS 調度分析、
Bootloader 設計等韌體開發場景。

包含 5 個測試案例覆蓋核心功能。

fix(security): 修復 run_command 的 Shell Injection 漏洞

將 shell=True 改為 argv 陣列，防止惡意命令注入。
影響：tools.py 的所有命令執行路徑。

Fixes: #123
```

### 提交前檢查清單

```bash
# 1. 確認所有測試通過
python -m pytest tests/ -v
# 必須 139/139 通過（若有新測試則更多）

# 2. 確認沒有安全問題
grep -r "shell=True" core/ agents/
# 不應有任何輸出

# 3. 確認新功能有對應文件
# - AGENTS.md（若新增 Agent）
# - COMMANDS.md（若新增命令）
# - PROJECT_BRAIN.md（若修改 Brain）

# 4. 更新 CHANGELOG.md
```

---

## 版本號規則

SYNTHEX 使用語意化版本（Semantic Versioning）：

```
v[主版本].[次版本].[修補版本]

主版本：不相容的 API 變更（架構性重寫）
次版本：向下相容的新功能
修補版本：Bug 修復和文件更新
```

**目前版本：** v0.13.0

版本號在以下位置需要更新：
- `CHANGELOG.md`（加入新版本的記錄）
- `core/brain/__init__.py`（若 Brain 版本更新）
- `README.md`（頁尾的版本標示）

---

## 尋求協助

如果你在開發過程中遇到問題：

1. **查閱文件**：README.md → ARCHITECTURE.md → 對應的模組 docstring
2. **查看測試**：`tests/test_core.py` 中有每個模組的使用範例
3. **查看 CHANGELOG.md**：了解歷次修改的脈絡
4. **開 Issue**：描述你遇到的問題、重現步驟、預期行為
