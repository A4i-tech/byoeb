import os
import pytest
from pydantic import ValidationError


class TestChatAppSettingsValidation:

    def test_fails_without_mongo_connection_string(self, monkeypatch):
        monkeypatch.delenv("MONGO_DB_CONNECTION_STRING", raising=False)
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="mongo_db_connection_string"):
            ChatAppSettings()

    def test_ashabot_message_cache_capacity_is_int(self, monkeypatch):
        monkeypatch.setenv("ASHABOT_MESSAGE_CACHE_CAPACITY", "128")
        monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        s = ChatAppSettings()
        assert s.ashabot_message_cache_capacity == 128
        assert isinstance(s.ashabot_message_cache_capacity, int)

    def test_openai_api_key_is_secretstr(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret")
        monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        from pydantic import SecretStr
        s = ChatAppSettings()
        assert isinstance(s.openai_api_key, SecretStr)
        assert "sk-test-secret" not in repr(s)
        assert s.openai_api_key.get_secret_value() == "sk-test-secret"

    def test_azure_queue_names_required_when_azure_provider(self, monkeypatch):
        monkeypatch.setenv("QUEUE_PROVIDER", "azure_storage_queue")
        monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
        monkeypatch.delenv("AZURE_QUEUE_STATUS", raising=False)
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="AZURE_QUEUE_STATUS"):
            ChatAppSettings()

    def test_invalid_feature_flag_raises_error(self):
        from byoeb.chat_app.configuration.config import _parse_feature_flags
        with pytest.raises(RuntimeError, match="Unexpected feature flag"):
            _parse_feature_flags("NOT_A_VALID_FLAG")


class TestTtsProviderValidation:

    @pytest.fixture(autouse=True)
    def base_env(self, monkeypatch):
        monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
        monkeypatch.setenv("TTS_MODEL", "tts-1")
        monkeypatch.setenv("TTS_VOICE", "alloy")

    def test_default_provider_is_openai(self, monkeypatch):
        monkeypatch.delenv("TTS_PROVIDER", raising=False)
        from byoeb.chat_app.configuration.config import ChatAppSettings
        assert ChatAppSettings().tts_provider == "openai"

    def test_unknown_provider_names_allowed_values(self, monkeypatch):
        monkeypatch.setenv("TTS_PROVIDER", "polly")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="'azure' or 'openai'"):
            ChatAppSettings()

    @pytest.mark.parametrize("name", ["TTS_MODEL", "TTS_VOICE"])
    def test_openai_requires_model_and_voice(self, monkeypatch, name):
        monkeypatch.setenv("TTS_PROVIDER", "openai")
        monkeypatch.delenv(name)
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match=name):
            ChatAppSettings()

    def test_azure_requires_azure_settings(self, monkeypatch):
        monkeypatch.setenv("TTS_PROVIDER", "azure")
        monkeypatch.delenv("AZURE_COGNITIVE_REGION")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="AZURE_COGNITIVE_REGION"):
            ChatAppSettings()

    def test_azure_does_not_require_tts_model(self, monkeypatch):
        monkeypatch.setenv("TTS_PROVIDER", "azure")
        monkeypatch.delenv("TTS_MODEL")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        assert ChatAppSettings().tts_provider == "azure"

class TestKbAppSettingsValidation:

    def test_qdrant_port_is_int(self, monkeypatch):
        monkeypatch.setenv("QDRANT_PORT", "6334")
        from byoeb.kb_app.configuration.config import KbAppSettings
        s = KbAppSettings()
        assert s.qdrant_port == 6334
        assert isinstance(s.qdrant_port, int)

    def test_kb_defaults_are_correct(self):
        from byoeb.kb_app.configuration.config import KbAppSettings
        s = KbAppSettings()
        assert s.qdrant_location == ":memory:"
        assert s.qdrant_port == 6333
        assert s.qdrant_collection_name == "byoeb-kb"
        assert s.storage_backend == "azure"
