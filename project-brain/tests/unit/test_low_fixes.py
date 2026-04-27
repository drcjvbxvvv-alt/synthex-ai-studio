"""
B-07: LOW-01~04 錯誤處理批次修復測試

LOW-01: context.py config.json 讀取失敗改為 logger.warning
LOW-02: brain_db.py 備份清理 OSError 改為 logger.debug
LOW-03: brain_db.py close() 冪等（重複呼叫不拋例外）
LOW-04: federation.py _strip_pii 新增 UUID 與 API token 清理
"""
from __future__ import annotations

import logging

import pytest


# ════════════════════════════════════════════════════════════════
# LOW-01: context.py config.json 讀取失敗 → logger.warning
# ════════════════════════════════════════════════════════════════


class TestLow01ContextConfigLog:
    """config.json 讀取失敗時應記 warning 而非靜默 pass。"""

    def test_invalid_config_json_logs_warning(self, tmp_path, caplog):
        """config.json 含無效 JSON 時，應有 LOW-01 warning。"""
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        cfg = brain_dir / "config.json"
        cfg.write_text("{invalid json", encoding="utf-8")

        from project_brain.engines.context import _get_type_limit

        with caplog.at_level(logging.WARNING, logger="project_brain.engines.context"):
            result = _get_type_limit("Pitfall", brain_dir)

        # Should fall back to default
        assert result >= 1
        # Should have logged a warning
        assert any("LOW-01" in r.message or "config.json" in r.message
                    for r in caplog.records), (
            f"Expected warning about config.json failure, got: {[r.message for r in caplog.records]}"
        )

    def test_valid_config_json_no_warning(self, tmp_path, caplog):
        """config.json 正常時不應有 warning。"""
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        cfg = brain_dir / "config.json"
        cfg.write_text('{"context": {"limits": {"Pitfall": 5}}}', encoding="utf-8")

        from project_brain.engines.context import _get_type_limit

        with caplog.at_level(logging.WARNING, logger="project_brain.engines.context"):
            result = _get_type_limit("Pitfall", brain_dir)

        assert result == 5
        assert not any("LOW-01" in r.message for r in caplog.records)

    def test_missing_config_json_no_warning(self, tmp_path, caplog):
        """config.json 不存在時（正常情況），不應有 warning。"""
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()

        from project_brain.engines.context import _get_type_limit

        with caplog.at_level(logging.WARNING, logger="project_brain.engines.context"):
            result = _get_type_limit("Rule", brain_dir)

        assert result >= 1
        assert not any("LOW-01" in r.message for r in caplog.records)


# ════════════════════════════════════════════════════════════════
# LOW-02: brain_db.py 備份清理 OSError → logger.debug
# ════════════════════════════════════════════════════════════════


class TestLow02BackupCleanupLog:
    """備份清理 OSError 應記 debug 而非靜默 pass。"""

    def test_source_has_debug_log_for_backup_cleanup(self):
        """brain_db.py 原始碼中備份清理 except 應有 logger.debug。"""
        import inspect
        from project_brain.core import brain_db as mod
        source = inspect.getsource(mod)
        assert "LOW-02" in source, (
            "brain_db.py 應有 LOW-02 標記的 debug log（backup cleanup）"
        )

    def test_backup_cleanup_does_not_crash(self, tmp_path):
        """即使備份清理失敗，BrainDB 初始化仍應成功。"""
        from project_brain.brain_db import BrainDB
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        # BrainDB 初始化會觸發備份邏輯，不應 crash
        db = BrainDB(brain_dir)
        assert db.conn is not None
        db.close()


# ════════════════════════════════════════════════════════════════
# LOW-03: brain_db.py close() 冪等
# ════════════════════════════════════════════════════════════════


class TestLow03CloseIdempotent:
    """close() 重複呼叫不應拋出例外。"""

    def test_double_close_no_exception(self, tmp_path):
        """close() 呼叫兩次不拋例外。"""
        from project_brain.brain_db import BrainDB
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        db = BrainDB(brain_dir)
        db.close()
        db.close()  # should not raise

    def test_triple_close_no_exception(self, tmp_path):
        """close() 呼叫三次不拋例外。"""
        from project_brain.brain_db import BrainDB
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        db = BrainDB(brain_dir)
        db.close()
        db.close()
        db.close()

    def test_close_sets_conn_none(self, tmp_path):
        """close() 後 conn property 回傳 None。"""
        from project_brain.brain_db import BrainDB
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        db = BrainDB(brain_dir)
        assert db.conn is not None
        db.close()
        assert db.conn is None

    def test_close_without_open_is_safe(self, tmp_path):
        """若 _conn_obj 已為 None，close() 無操作。"""
        from project_brain.brain_db import BrainDB
        brain_dir = tmp_path / ".brain"
        brain_dir.mkdir()
        db = BrainDB(brain_dir)
        db._conn_obj = None  # simulate already-closed state
        db.close()  # should not raise


# ════════════════════════════════════════════════════════════════
# LOW-04: federation.py _strip_pii — UUID 與 API token
# ════════════════════════════════════════════════════════════════


class TestLow04PiiUUID:
    """UUID (8-4-4-4-12) 格式應被 _strip_pii 清理。"""

    def _strip(self, text):
        from project_brain.federation import _strip_pii
        return _strip_pii(text)

    def test_uuid_stripped(self):
        """標準 UUID 應被替換。"""
        text = "node id: 550e8400-e29b-41d4-a716-446655440000"
        result = self._strip(text)
        assert "550e8400" not in result
        assert "[redacted-uuid]" in result

    def test_uppercase_uuid_stripped(self):
        """大寫 UUID 也應被替換（regex 不分大小寫）。"""
        text = "ID: A0EEBC99-9C0B-4EF8-BB6D-6BB9BD380A11"
        result = self._strip(text)
        assert "A0EEBC99" not in result
        assert "[redacted-uuid]" in result

    def test_normal_hyphenated_word_not_stripped(self):
        """普通帶連字號的詞不應被誤判為 UUID。"""
        text = "knowledge-management-system is running"
        result = self._strip(text)
        assert result == text  # unchanged


class TestLow04PiiToken:
    """API token 格式應被 _strip_pii 清理。"""

    def _strip(self, text):
        from project_brain.federation import _strip_pii
        return _strip_pii(text)

    def test_github_token_stripped(self):
        """GitHub Personal Access Token (ghp_) 應被替換。"""
        text = "token: ghp_1234567890abcdefghij1234567890abcdef"
        result = self._strip(text)
        assert "ghp_" not in result
        assert "[redacted-token]" in result

    def test_openai_key_stripped(self):
        """OpenAI API key (sk-) 應被替換。"""
        text = "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234567890"
        result = self._strip(text)
        assert "sk-" not in result
        assert "[redacted-token]" in result

    def test_slack_bot_token_stripped(self):
        """Slack Bot Token (xoxb-) 應被替換。"""
        text = "SLACK_TOKEN=xoxb-1234567890-1234567890123-abcdefghijklmnopqrstuv"
        result = self._strip(text)
        assert "xoxb-" not in result
        assert "[redacted-token]" in result

    def test_slack_user_token_stripped(self):
        """Slack User Token (xoxp-) 應被替換。"""
        text = "xoxp-12345678901234567890-abcdefghijklmnop"
        result = self._strip(text)
        assert "xoxp-" not in result
        assert "[redacted-token]" in result

    def test_short_sk_not_stripped(self):
        """'sk-' 後面不足 16 字元時不應替換（避免誤判）。"""
        text = "skip this sk-short"
        result = self._strip(text)
        assert "sk-short" in result  # too short to match

    def test_normal_text_unchanged(self):
        """普通文字不應被修改。"""
        text = "This is a normal knowledge node about Python decorators."
        result = self._strip(text)
        assert result == text


# ════════════════════════════════════════════════════════════════
# 整合：既有 federation PII 測試仍通過
# ════════════════════════════════════════════════════════════════


class TestLow04RegressionExistingPii:
    """確認既有的 PII 清理（email、IP、Slack）不受新增影響。"""

    def _strip(self, text):
        from project_brain.federation import _strip_pii
        return _strip_pii(text)

    def test_email_still_stripped(self):
        result = self._strip("contact user@example.com for help")
        assert "user@example.com" not in result

    def test_private_ip_still_stripped(self):
        result = self._strip("connect to 192.168.1.100:8080")
        assert "192.168.1.100" not in result

    def test_slack_url_still_stripped(self):
        result = self._strip("see https://myteam.slack.com/archives/C123")
        assert "myteam.slack.com" not in result
