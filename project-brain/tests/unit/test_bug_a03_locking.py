"""
tests/unit/test_bug_a03_locking.py — BUG-A03 雙重加鎖驗收測試
═══════════════════════════════════════════════════════════════

問題（BUG-A03）
──────────────
`engine.py` 的 `ProjectBrain` 類別有 6 個懶加載屬性：

  - db            → BrainDB
  - graph         → KnowledgeGraph
  - context_engineer → ContextEngineer
  - decay_engine  → DecayEngine
  - nudge_engine  → NudgeEngine
  - router        → Router

這 6 個屬性共用同一個 `_init_lock = threading.Lock()`（非可重入鎖）。

根本原因（雙重加鎖 / double-checked locking 競態）：

  1. Thread A 讀 `if self._db is None`（無鎖保護的外部檢查）→ True
  2. Thread B 讀 `if self._db is None`（無鎖保護的外部檢查）→ True
  3. Thread A 獲得鎖，初始化 BrainDB，釋放鎖
  4. Thread B 獲得鎖，再次初始化 BrainDB（雙重初始化！）
     → 兩個不同的 sqlite3.Connection，可能造成寫入衝突

  另外，若屬性 A 的 getter 在持鎖狀態下觸發屬性 B（e.g. db 初始化呼叫了
  需要同一鎖的另一屬性），會造成死鎖（Lock 非可重入）。

實作計劃（執行前請閱讀）
────────────────────────
1. 把 `_init_lock` 拆成 6 個各自獨立的鎖：

   ```python
   # engine.py — ProjectBrain.__init__
   self._db_lock             = threading.Lock()
   self._graph_lock          = threading.Lock()
   self._context_lock        = threading.Lock()
   self._decay_lock          = threading.Lock()
   self._nudge_lock          = threading.Lock()
   self._router_lock         = threading.Lock()
   ```

2. 每個 @property 改用自己的鎖：

   ```python
   @property
   def db(self) -> BrainDB:
       if self._db is None:
           with self._db_lock:
               if self._db is None:         # double-checked: 此時已持鎖
                   self._db = BrainDB(self.brain_dir)
       return self._db
   ```

3. 移除原本的 `_init_lock = threading.Lock()`（類別層級共用鎖）。

驗收標準
────────
- 20 個執行緒並行存取 `engine.db`，只建立一個 BrainDB 實例
- 並行存取 `engine.graph + engine.db + engine.context_engineer`，無死鎖
- 50 執行緒壓力測試，所有執行緒均能拿到非 None 的屬性值
- 修改後不再有 `_init_lock`（類別層級共用鎖）

執行方式
────────
  # 未實作前（應失敗或偶發性競態）：
  python -m pytest tests/unit/test_bug_a03_locking.py -v

  # 實作後（應全部通過）：
  python -m pytest tests/unit/test_bug_a03_locking.py -v
"""
import threading
import time
import pytest


# ════════════════════════════════════════════════════════════════
#  測試群組 1：鎖結構驗證
# ════════════════════════════════════════════════════════════════

class TestBugA03LockStructure:
    """engine.py 的鎖應已拆分為各屬性專用鎖，不再使用共用 _init_lock。"""

    def _make_engine(self, tmp_path):
        from project_brain.engine import ProjectBrain
        return ProjectBrain(tmp_path)

    def test_no_shared_init_lock(self, tmp_path):
        """
        ProjectBrain 不應有 `_init_lock` 屬性
        （舊的共用鎖已被拆分為各屬性專用鎖）。
        """
        engine = self._make_engine(tmp_path)
        assert not hasattr(engine, "_init_lock"), (
            "engine 仍有 `_init_lock`（共用鎖）。\n"
            "BUG-A03 修復要求拆分為各屬性專用鎖。\n"
            "請將 _init_lock 改為 _db_lock / _graph_lock / ... 等獨立鎖。"
        )

    def test_per_property_locks_exist(self, tmp_path):
        """每個懶加載屬性應有對應的專用鎖。"""
        engine = self._make_engine(tmp_path)
        expected_locks = [
            "_db_lock",
            "_graph_lock",
            "_context_lock",
            "_decay_lock",
            "_nudge_lock",
            "_router_lock",
        ]
        missing = [lock for lock in expected_locks if not hasattr(engine, lock)]
        assert not missing, (
            f"缺少以下專用鎖：{missing}\n"
            "請在 ProjectBrain.__init__ 中為每個懶加載屬性建立獨立的 threading.Lock()。"
        )

    def test_all_locks_are_threading_lock(self, tmp_path):
        """每個專用鎖必須是 threading.Lock 實例（而非 RLock 或其他）。"""
        engine = self._make_engine(tmp_path)
        lock_names = [
            "_db_lock", "_graph_lock", "_context_lock",
            "_decay_lock", "_nudge_lock", "_router_lock",
        ]
        for name in lock_names:
            lock = getattr(engine, name, None)
            if lock is None:
                continue  # 缺少的鎖由上一個測試報告
            # threading.Lock() 回傳的是 _thread.lock 或 _thread.RLock
            # 只確認它有 acquire/release 介面
            assert hasattr(lock, "acquire") and hasattr(lock, "release"), (
                f"{name} 沒有 acquire/release 介面，不是有效的鎖。"
            )

    def test_locks_are_distinct_objects(self, tmp_path):
        """所有專用鎖必須是不同的物件（不能重用同一個鎖）。"""
        engine = self._make_engine(tmp_path)
        lock_names = [
            "_db_lock", "_graph_lock", "_context_lock",
            "_decay_lock", "_nudge_lock", "_router_lock",
        ]
        locks = [getattr(engine, n) for n in lock_names if hasattr(engine, n)]
        lock_ids = [id(lock) for lock in locks]
        assert len(set(lock_ids)) == len(lock_ids), (
            f"有鎖物件被重用（共用）。\n"
            f"id 列表：{lock_ids}\n"
            "每個屬性必須有自己獨立的 threading.Lock() 實例。"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 2：並行存取不重複初始化
# ════════════════════════════════════════════════════════════════

class TestBugA03SingleInit:
    """多執行緒並行存取同一屬性，只應初始化一次。"""

    def test_db_initialized_exactly_once_under_concurrency(self, tmp_path):
        """
        20 個執行緒同時存取 engine.db，
        所有執行緒應得到同一個 BrainDB 實例（id 相同）。
        """
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        results = []
        errors = []

        def access_db():
            try:
                db = engine.db
                results.append(id(db))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=access_db) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"執行緒存取 engine.db 時發生錯誤：{errors}"
        assert len(results) == 20, f"只有 {len(results)}/20 個執行緒完成"
        unique_ids = set(results)
        assert len(unique_ids) == 1, (
            f"engine.db 被初始化了 {len(unique_ids)} 次（應只有 1 次）。\n"
            f"發現 {len(unique_ids)} 個不同的 BrainDB 實例。\n"
            "雙重初始化競態條件（BUG-A03）仍存在。"
        )

    def test_graph_initialized_exactly_once_under_concurrency(self, tmp_path):
        """20 個執行緒同時存取 engine.graph，只建立一個 KnowledgeGraph。"""
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        results = []
        errors = []

        def access_graph():
            try:
                g = engine.graph
                results.append(id(g))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=access_graph) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert not errors, f"存取 engine.graph 時發生錯誤：{errors}"
        unique_ids = set(results)
        assert len(unique_ids) == 1, (
            f"engine.graph 被初始化了 {len(unique_ids)} 次（應只有 1 次）。"
        )

    def test_db_instance_is_not_none(self, tmp_path):
        """engine.db 在任何執行緒中都不應為 None。"""
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        none_count = [0]
        lock = threading.Lock()

        def check_not_none():
            db = engine.db
            if db is None:
                with lock:
                    none_count[0] += 1

        threads = [threading.Thread(target=check_not_none) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert none_count[0] == 0, (
            f"{none_count[0]} 個執行緒拿到 None 的 engine.db。"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 3：無死鎖（跨屬性並行存取）
# ════════════════════════════════════════════════════════════════

class TestBugA03NoDeadlock:
    """
    並行存取多個屬性不得發生死鎖。

    BUG-A03 的共用鎖設計使得：
    - 屬性 A 的 getter 在持 _init_lock 時觸發屬性 B 的 getter
    - 屬性 B 嘗試獲取同一個 _init_lock → 死鎖（Lock 非可重入）

    修復後（每屬性獨立鎖），此問題消失。
    """

    TIMEOUT_SECONDS = 10  # 死鎖測試的超時時間

    def test_concurrent_db_and_graph_no_deadlock(self, tmp_path):
        """
        一半執行緒存取 engine.db，另一半存取 engine.graph，
        全部應在 10 秒內完成（無死鎖）。
        """
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        results = {"db": [], "graph": []}
        errors = []

        def access_db():
            try:
                _ = engine.db
                results["db"].append(1)
            except Exception as e:
                errors.append(f"db: {e}")

        def access_graph():
            try:
                _ = engine.graph
                results["graph"].append(1)
            except Exception as e:
                errors.append(f"graph: {e}")

        threads = (
            [threading.Thread(target=access_db)    for _ in range(10)] +
            [threading.Thread(target=access_graph) for _ in range(10)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=self.TIMEOUT_SECONDS)

        alive = [t for t in threads if t.is_alive()]
        assert not alive, (
            f"{len(alive)} 個執行緒在 {self.TIMEOUT_SECONDS}s 後仍未完成。\n"
            "可能發生死鎖（BUG-A03）。使用共用鎖時，"
            "db 的初始化觸發了 graph 的鎖，造成自我死鎖。"
        )
        assert not errors, f"執行緒發生錯誤：{errors}"

    def test_all_six_properties_no_deadlock(self, tmp_path):
        """
        6 類執行緒各自存取 6 個不同屬性，全部應在 10 秒內完成。
        """
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        errors = []

        def make_accessor(prop_name):
            def fn():
                try:
                    getattr(engine, prop_name)
                except Exception as e:
                    errors.append(f"{prop_name}: {e}")
            return fn

        properties = ["db", "graph", "context_engineer", "decay_engine", "nudge_engine", "router"]
        threads = []
        for prop in properties:
            for _ in range(5):  # 5 執行緒 × 6 屬性 = 30 執行緒
                threads.append(threading.Thread(target=make_accessor(prop)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=self.TIMEOUT_SECONDS)

        alive = [t for t in threads if t.is_alive()]
        assert not alive, (
            f"{len(alive)} 個執行緒在 {self.TIMEOUT_SECONDS}s 後仍未完成（可能死鎖）。"
        )
        assert not errors, f"執行緒發生錯誤：{errors[:5]}"  # 最多顯示 5 個錯誤

    def test_reentrant_property_access_no_deadlock(self, tmp_path):
        """
        若某屬性的初始化內部存取另一個屬性（鏈式初始化），
        不應因為鎖重入而死鎖。
        """
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        completed = threading.Event()
        error_holder = [None]

        def chain_access():
            try:
                # context_engineer 的初始化可能需要 db 和 graph
                # 這在共用鎖下會造成重入死鎖
                _ = engine.context_engineer
                _ = engine.db
                _ = engine.graph
                completed.set()
            except Exception as e:
                error_holder[0] = e
                completed.set()

        t = threading.Thread(target=chain_access)
        t.start()
        t.join(timeout=self.TIMEOUT_SECONDS)

        assert t.is_alive() is False, (
            f"鏈式屬性存取在 {self.TIMEOUT_SECONDS}s 後未完成（可能死鎖）。\n"
            "請確認各屬性初始化過程不會重入同一個鎖。"
        )
        assert error_holder[0] is None, (
            f"鏈式屬性存取發生錯誤：{error_holder[0]}"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 4：壓力測試
# ════════════════════════════════════════════════════════════════

class TestBugA03StressTest:
    """50 執行緒同時存取所有屬性，結果應全部正確且無競態。"""

    def test_50_threads_all_properties(self, tmp_path):
        """
        50 個執行緒，每個執行緒隨機存取 3 個屬性，
        所有執行緒在 15 秒內完成，無錯誤，且取得的實例一致。
        """
        import random
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        instance_ids = {prop: set() for prop in [
            "db", "graph", "context_engineer", "decay_engine", "nudge_engine", "router"
        ]}
        errors = []
        lock = threading.Lock()

        props = list(instance_ids.keys())

        def worker():
            try:
                chosen = random.sample(props, 3)
                for prop in chosen:
                    obj = getattr(engine, prop)
                    if obj is not None:
                        with lock:
                            instance_ids[prop].add(id(obj))
            except Exception as e:
                with lock:
                    errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        alive = [t for t in threads if t.is_alive()]
        assert not alive, f"{len(alive)} 個執行緒仍在執行（可能死鎖或超時）。"
        assert not errors, f"執行緒錯誤：{errors[:5]}"

        # 每個屬性只應有 1 個實例 ID
        for prop, ids in instance_ids.items():
            if not ids:
                continue  # 未被存取的屬性跳過
            assert len(ids) == 1, (
                f"engine.{prop} 被初始化了 {len(ids)} 次（應只有 1 次）。\n"
                "雙重初始化競態條件仍存在（BUG-A03）。"
            )

    def test_rapid_sequential_access_stable(self, tmp_path):
        """
        單一執行緒快速反覆存取 engine.db 100 次，
        每次都應得到相同的物件實例。
        """
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        first_id = id(engine.db)

        for i in range(99):
            current_id = id(engine.db)
            assert current_id == first_id, (
                f"第 {i+2} 次存取 engine.db 得到不同實例（id 改變）。\n"
                "lazy init 邏輯可能每次都重新建立物件。"
            )

    def test_property_value_consistent_across_threads(self, tmp_path):
        """
        所有執行緒看到的 engine.db 應指向同一個物件。
        """
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        # 預先觸發初始化
        expected_id = id(engine.db)

        seen_ids = []
        lock = threading.Lock()

        def check_id():
            db = engine.db
            with lock:
                seen_ids.append(id(db))

        threads = [threading.Thread(target=check_id) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        unique = set(seen_ids)
        assert len(unique) == 1, (
            f"50 個執行緒看到 {len(unique)} 個不同的 engine.db 實例，應只有 1 個。"
        )
        assert list(unique)[0] == expected_id, (
            "執行緒看到的 engine.db 實例與預期不符。"
        )


# ════════════════════════════════════════════════════════════════
#  測試群組 5：回歸測試（功能不受影響）
# ════════════════════════════════════════════════════════════════

class TestBugA03Regression:
    """確認鎖修改後基本功能仍正常運作。"""

    def test_engine_db_functional_after_fix(self, tmp_path):
        """engine.db 應可正常進行 CRUD 操作。"""
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        db = engine.db
        assert db is not None

        node_id = db.add_node("test_node", "Rule", "測試規則", content="BUG-A03 修復後功能驗證")
        assert node_id is not None

        node = db.get_node(node_id)
        assert node is not None
        assert node["title"] == "測試規則"

    def test_engine_graph_functional_after_fix(self, tmp_path):
        """engine.graph 應可正常加入和搜尋節點。"""
        from project_brain.engine import ProjectBrain

        engine = ProjectBrain(tmp_path)
        g = engine.graph
        assert g is not None

        g.add_node("test1", "Rule", "測試圖節點", content="驗證圖操作")
        results = g.search_nodes("測試")
        assert any(r["id"] == "test1" for r in results), (
            "加入節點後搜尋未找到（graph 功能異常）。"
        )

    def test_multiple_engine_instances_independent(self, tmp_path):
        """
        不同 tmp_path 的 ProjectBrain 實例應完全獨立。
        """
        from project_brain.engine import ProjectBrain
        import tempfile

        with tempfile.TemporaryDirectory() as tmp2:
            from pathlib import Path
            engine1 = ProjectBrain(tmp_path)
            engine2 = ProjectBrain(Path(tmp2))

            assert id(engine1.db) != id(engine2.db), (
                "不同 ProjectBrain 實例的 db 屬性不應共用物件。"
            )
