"""
v0.3.0 架構決策驗收測試

驗證四個 v0.3.0 的核心決策在所有版本中始終成立：

  決策 E：OllamaClient duck-typed，不強制 anthropic SDK
          → OllamaClient 可在無 anthropic 套件的環境下實例化
          → KRBAIAssistant 不對 client 做型別檢查

  決策 F：MultilingualEmbedder 優先級高於 Ollama embedder
          → get_embedder() 先嘗試 Multilingual，再嘗試 Ollama
          → 兩者皆可用時，回傳 MultilingualEmbedder

  決策 G：federation export 時清理 PII，而非 import 時
          → _strip_pii 在 export（_sanitise_node）呼叫
          → import_bundle 不呼叫 _strip_pii（bundle 本身已安全）

  決策 H（LoRA）：已於 v10.x 標記為無效，不測試。

  決策 I：ANN index fallback 為 LinearScan（純 Python）
          → LinearScanIndex 無需任何外部套件
          → get_ann_index() 在 sqlite-vec 不可用時回傳 LinearScanIndex
          → LinearScanIndex 與 HNSWIndex 實作相同介面
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ══════════════════════════════════════════════════════════════════════
# 決策 E：OllamaClient duck-typed
# ══════════════════════════════════════════════════════════════════════

class TestOllamaClientDuckTyped(unittest.TestCase):
    """v0.3.0：OllamaClient duck-typed，不強制 anthropic SDK。"""

    def test_ollama_client_importable_without_anthropic(self):
        """OllamaClient 可在不 import anthropic 的情況下實例化。"""
        # 模擬 anthropic 套件不存在
        import sys
        had_anthropic = "anthropic" in sys.modules
        original = sys.modules.get("anthropic")
        sys.modules["anthropic"] = None  # type: ignore

        try:
            from project_brain.krb_ai_assist import OllamaClient
            client = OllamaClient()
            self.assertIsNotNone(client,
                                 "OllamaClient 應不依賴 anthropic 套件（v0.3.0 決策）")
        finally:
            if had_anthropic and original is not None:
                sys.modules["anthropic"] = original
            elif not had_anthropic:
                sys.modules.pop("anthropic", None)

    def test_ollama_client_has_messages_attribute(self):
        """OllamaClient 應具備 .messages 屬性（與 anthropic.Anthropic duck-type 相容）。"""
        from project_brain.krb_ai_assist import OllamaClient
        client = OllamaClient()
        self.assertTrue(hasattr(client, "messages"),
                        "OllamaClient 應有 .messages 屬性（anthropic 相容介面）")

    def test_ollama_client_messages_has_create(self):
        """OllamaClient.messages 應具備 .create 方法（duck-type 介面完整性）。"""
        from project_brain.krb_ai_assist import OllamaClient
        client = OllamaClient()
        self.assertTrue(hasattr(client.messages, "create"),
                        "OllamaClient.messages 應有 .create 方法（anthropic duck-type）")

    def test_krb_assistant_does_not_type_check_client(self):
        """KRBAIAssistant 應接受任何帶有 .messages 的 client 物件（不型別檢查）。"""
        import tempfile
        from pathlib import Path as P
        tmp = P(tempfile.mkdtemp())
        (tmp / ".brain").mkdir()

        from project_brain.graph import KnowledgeGraph
        from project_brain.review_board import KnowledgeReviewBoard

        graph = KnowledgeGraph(tmp)
        krb   = KnowledgeReviewBoard(tmp, graph)

        # 用 MagicMock 模擬 client（非 anthropic、非 OllamaClient）
        mock_client = MagicMock()
        mock_client.messages = MagicMock()

        try:
            from project_brain.krb_ai_assist import KRBAIAssistant
            assistant = KRBAIAssistant(krb, mock_client, model="test-model")
            self.assertIs(assistant.client, mock_client,
                          "KRBAIAssistant 應接受任何 duck-type client（v0.3.0 決策）")
        except TypeError as e:
            self.fail(f"KRBAIAssistant 不應對 client 做型別限制：{e}")


# ══════════════════════════════════════════════════════════════════════
# 決策 F：MultilingualEmbedder 優先級高於 Ollama embedder
# ══════════════════════════════════════════════════════════════════════

class TestMultilingualEmbedderPriority(unittest.TestCase):
    """v0.3.0：MultilingualEmbedder 優先級高於 OllamaEmbedder。"""

    def test_multilingual_checked_before_ollama_in_source(self):
        """get_embedder() 原始碼結構中，Multilingual 的判斷必須在 Ollama 之前。"""
        import inspect
        from project_brain import embedder as emb_mod
        source = inspect.getsource(emb_mod.get_embedder)
        ml_pos   = source.find("MultilingualEmbedder")
        ollama_pos = source.find("OllamaEmbedder")
        self.assertGreater(ml_pos, -1,
                           "get_embedder 原始碼應包含 MultilingualEmbedder")
        self.assertGreater(ollama_pos, -1,
                           "get_embedder 原始碼應包含 OllamaEmbedder")
        self.assertLess(ml_pos, ollama_pos,
                        "MultilingualEmbedder 應比 OllamaEmbedder 更早出現（v0.3.0 優先級決策）")

    def test_multilingual_selected_over_ollama_when_both_available(self):
        """兩者皆可用時，get_embedder() 應回傳 MultilingualEmbedder。"""
        from project_brain.embedder import get_embedder, MultilingualEmbedder

        mock_vec = [0.1] * 768

        with patch.object(MultilingualEmbedder, "is_available", return_value=True), \
             patch.object(MultilingualEmbedder, "embed", return_value=mock_vec):
            result = get_embedder()

        self.assertIsInstance(result, MultilingualEmbedder,
                              "兩者皆可用時，應選擇 MultilingualEmbedder（v0.3.0 決策）")

    def test_ollama_fallback_when_multilingual_unavailable(self):
        """MultilingualEmbedder 不可用時，應回落到 OllamaEmbedder。"""
        from project_brain.embedder import get_embedder, MultilingualEmbedder, OllamaEmbedder

        mock_vec = [0.1] * 768

        with patch.object(MultilingualEmbedder, "is_available", return_value=False), \
             patch.object(OllamaEmbedder, "is_available", return_value=True), \
             patch.object(OllamaEmbedder, "embed", return_value=mock_vec):
            result = get_embedder()

        self.assertIsInstance(result, OllamaEmbedder,
                              "Multilingual 不可用時應回落到 OllamaEmbedder（v0.3.0 決策）")


# ══════════════════════════════════════════════════════════════════════
# 決策 G：federation export 時清理 PII，而非 import 時
# ══════════════════════════════════════════════════════════════════════

class TestFederationPIIOnExport(unittest.TestCase):
    """v0.3.0：PII 在 export 時清理，import 信任 bundle 已安全。"""

    def test_strip_pii_removes_email(self):
        """_strip_pii 應移除 email 地址。"""
        from project_brain.federation import _strip_pii
        result = _strip_pii("聯絡 admin@internal.corp.com 取得存取權")
        self.assertNotIn("@", result,
                         "_strip_pii 應移除 email 地址（v0.3.0 PII 決策）")
        self.assertIn("[redacted-email]", result,
                      "_strip_pii 應以 [redacted-email] 取代 email")

    def test_strip_pii_removes_internal_hostname(self):
        """_strip_pii 應移除 internal.* 內部主機名稱。"""
        from project_brain.federation import _strip_pii
        result = _strip_pii("請連接至 internal.corp.example.com 取得資源")
        self.assertNotIn("internal.corp.example.com", result,
                         "_strip_pii 應移除 internal.* 主機名（v0.3.0 PII 決策）")

    def test_strip_pii_removes_local_domain(self):
        """_strip_pii 應移除 .local domain。"""
        from project_brain.federation import _strip_pii
        result = _strip_pii("服務位於 devbox.local 上")
        self.assertNotIn("devbox.local", result,
                         "_strip_pii 應移除 .local domain（v0.3.0 PII 決策）")
        self.assertIn("[redacted-local]", result)

    def test_sanitise_node_applies_strip_pii_to_title_and_content(self):
        """FederationExporter._sanitise_node 應對 title 和 content 套用 _strip_pii。"""
        import tempfile
        from project_brain.graph import KnowledgeGraph
        from project_brain.federation import FederationExporter

        tmp = Path(tempfile.mkdtemp())
        brain_dir = tmp / ".brain"
        brain_dir.mkdir()
        graph = KnowledgeGraph(tmp)

        exporter = FederationExporter(graph, brain_dir, project_name="test")
        node = {
            "id":         "n1",
            "title":      "部署說明 owner@secret.com",
            "content":    "連接 devbox.local 執行測試",
            "kind":       "Rule",
            "confidence": 0.8,
            "tags":       "",
        }
        result = exporter._sanitise_node(node)

        self.assertIsNotNone(result, "_sanitise_node 應回傳清潔後的節點")
        self.assertNotIn("owner@secret.com", result["title"],
                         "_sanitise_node 應清理 title 中的 PII（v0.3.0 決策：export 時清理）")
        self.assertNotIn("devbox.local", result["content"],
                         "_sanitise_node 應清理 content 中的 PII（v0.3.0 決策：export 時清理）")

    def test_import_bundle_does_not_call_strip_pii(self):
        """import_bundle 不應呼叫 _strip_pii（bundle 本身已是潔淨資料）。"""
        from project_brain import federation as fed_mod

        with patch.object(fed_mod, "_strip_pii", wraps=fed_mod._strip_pii) as mock_strip:
            # import_bundle 需要真實的 KRB — 直接驗證 source code 不含呼叫更可靠
            import inspect
            importer_source = inspect.getsource(fed_mod.FederationImporter.import_bundle)
            self.assertNotIn("_strip_pii", importer_source,
                             "import_bundle 不應呼叫 _strip_pii（bundle 本身已安全，v0.3.0 決策）")
        # mock_strip 從未被呼叫（靜態驗證，不需實際執行 import）
        mock_strip.assert_not_called()


# ══════════════════════════════════════════════════════════════════════
# 決策 I：ANN index fallback 為 LinearScan（純 Python）
# ══════════════════════════════════════════════════════════════════════

class TestANNIndexFallback(unittest.TestCase):
    """v0.3.0：ANN index fallback 為 LinearScan，sqlite-vec 是 C 擴充，不強制依賴。"""

    def test_linear_scan_importable_without_sqlite_vec(self):
        """LinearScanIndex 應可在沒有 sqlite_vec 的環境下 import 和實例化。"""
        import sys
        had = "sqlite_vec" in sys.modules
        original = sys.modules.get("sqlite_vec")
        sys.modules["sqlite_vec"] = None  # type: ignore

        try:
            # 強制重新載入 ann_index（清除快取）
            import importlib
            import project_brain.ann_index as ann_mod
            importlib.reload(ann_mod)

            index = ann_mod.LinearScanIndex(dim=4)
            self.assertIsNotNone(index,
                                 "LinearScanIndex 應在無 sqlite-vec 的環境下可用（v0.3.0 決策）")
        finally:
            if had and original is not None:
                sys.modules["sqlite_vec"] = original
            elif not had:
                sys.modules.pop("sqlite_vec", None)
            import importlib, project_brain.ann_index as ann_mod
            importlib.reload(ann_mod)

    def test_get_ann_index_returns_linear_scan_when_hnsw_unavailable(self):
        """sqlite-vec 不可用時，get_ann_index() 應回傳 LinearScanIndex。"""
        from project_brain.ann_index import get_ann_index, LinearScanIndex, HNSWIndex

        with patch.object(HNSWIndex, "is_available", return_value=False):
            result = get_ann_index(dim=8, brain_dir=Path("/tmp"))

        self.assertIsInstance(result, LinearScanIndex,
                              "sqlite-vec 不可用時應回傳 LinearScanIndex（v0.3.0 決策）")

    def test_linear_scan_and_hnsw_share_same_interface(self):
        """LinearScanIndex 應與 HNSWIndex 實作相同的公開介面（add / search / __len__）。"""
        from project_brain.ann_index import LinearScanIndex, HNSWIndex

        required_methods = ["add", "search", "__len__"]
        for method in required_methods:
            self.assertTrue(hasattr(LinearScanIndex, method),
                            f"LinearScanIndex 應有 {method} 方法")
            self.assertTrue(hasattr(HNSWIndex, method),
                            f"HNSWIndex 應有 {method} 方法")

    def test_linear_scan_add_and_search_work(self):
        """LinearScanIndex 的 add / search 功能應正確運作。"""
        from project_brain.ann_index import LinearScanIndex

        index = LinearScanIndex(dim=3)
        index.add("node_a", [1.0, 0.0, 0.0])
        index.add("node_b", [0.0, 1.0, 0.0])
        index.add("node_c", [0.0, 0.0, 1.0])

        self.assertEqual(len(index), 3)

        # 查詢向量接近 node_a
        results = index.search([1.0, 0.0, 0.0], k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "node_a",
                         "LinearScanIndex.search 應回傳最相近的節點")


if __name__ == "__main__":
    unittest.main()
