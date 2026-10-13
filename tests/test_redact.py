import importlib
import os
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reload_with_env(enabled: bool):
    """Reload app.redact with PII_REDACTION set to the given value."""
    os.environ["PII_REDACTION"] = "true" if enabled else "false"
    import app.redact as mod
    importlib.reload(mod)
    return mod


# ---------------------------------------------------------------------------
# When PII_REDACTION is disabled
# ---------------------------------------------------------------------------

class TestRedactDisabled:
    def setup_method(self):
        self.mod = _reload_with_env(False)

    def test_passthrough_text(self):
        text = "Call me at 555-123-4567 or email foo@bar.com"
        redacted, mapping = self.mod.redact(text)
        assert redacted == text
        assert mapping == {}

    def test_restore_noop(self):
        assert self.mod.restore("hello", {}) == "hello"


# ---------------------------------------------------------------------------
# When PII_REDACTION is enabled (mocked presidio)
# ---------------------------------------------------------------------------

class TestRedactEnabled:
    def setup_method(self):
        self.mod = _reload_with_env(True)

    def _mock_analyzer_result(self, start: int, end: int, entity_type: str):
        r = MagicMock()
        r.start = start
        r.end = end
        r.entity_type = entity_type
        return r

    def test_email_redacted(self):
        text = "Email me at foo@bar.com please"
        result = self._mock_analyzer_result(12, 23, "EMAIL_ADDRESS")
        with patch.object(self.mod, "_get_analyzer") as mock_get:
            analyzer = MagicMock()
            analyzer.analyze.return_value = [result]
            mock_get.return_value = analyzer

            redacted, mapping = self.mod.redact(text)

        assert "<EMAIL_1>" in redacted
        assert "foo@bar.com" not in redacted
        assert mapping["<EMAIL_1>"] == "foo@bar.com"

    def test_restore_reverses_redaction(self):
        mapping = {"<EMAIL_1>": "foo@bar.com", "<PERSON_1>": "Alice"}
        text = "Send to <EMAIL_1> from <PERSON_1>"
        restored = self.mod.restore(text, mapping)
        assert restored == "Send to foo@bar.com from Alice"

    def test_restore_empty_mapping(self):
        assert self.mod.restore("hello world", {}) == "hello world"

    def test_empty_text_returns_unchanged(self):
        redacted, mapping = self.mod.redact("")
        assert redacted == ""
        assert mapping == {}

    def test_no_pii_returns_unchanged(self):
        text = "What is the capital of France?"
        with patch.object(self.mod, "_get_analyzer") as mock_get:
            analyzer = MagicMock()
            analyzer.analyze.return_value = []
            mock_get.return_value = analyzer
            redacted, mapping = self.mod.redact(text)

        assert redacted == text
        assert mapping == {}
