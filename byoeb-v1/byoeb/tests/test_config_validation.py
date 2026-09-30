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


class TestProviderSettings:

    @pytest.fixture(autouse=True)
    def clean_provider_env(self, monkeypatch):
        for name in (
            "CHAT_PROVIDER", "EMBEDDING_PROVIDER", "TRANSCRIPTION_PROVIDER", "OPENAI_API_KEY", "OPENAI_BASE_URL",
            "CHAT_BASE_URL", "EMBEDDING_BASE_URL", "TRANSCRIPTION_BASE_URL",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    @pytest.mark.parametrize("name", ["CHAT_PROVIDER", "EMBEDDING_PROVIDER", "TRANSCRIPTION_PROVIDER"])
    def test_unknown_provider_is_rejected(self, monkeypatch, name):
        monkeypatch.setenv(name, "gemini")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match=f"{name}='gemini' is not a known provider"):
            ChatAppSettings()

    def test_providers_default_to_openai(self):
        from byoeb.chat_app.configuration.config import ChatAppSettings
        s = ChatAppSettings()
        assert (s.chat_provider, s.embedding_provider, s.transcription_provider) == ("openai", "openai", "openai")

    @pytest.mark.parametrize("name,missing", [
        ("CHAT_PROVIDER", "AZURE_OPENAI_ENDPOINT"),
        ("EMBEDDING_PROVIDER", "AZURE_OPENAI_ENDPOINT"),
        ("TRANSCRIPTION_PROVIDER", "AZURE_OPENAI_SPEECH_ENDPOINT"),
    ])
    def test_azure_without_endpoint_is_rejected(self, monkeypatch, name, missing):
        monkeypatch.setenv(name, "azure")
        monkeypatch.delenv(missing)
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match=f"{name}=azure needs these settings: {missing}"):
            ChatAppSettings()

    def test_azure_embedding_without_deployment_name_is_rejected(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "azure")
        monkeypatch.delenv("AZURE_OPENAI_DEPLOYMENT_NAME")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="AZURE_OPENAI_DEPLOYMENT_NAME"):
            ChatAppSettings()

    def test_azure_with_its_settings_needs_no_openai_key(self, monkeypatch):
        for name in ("CHAT_PROVIDER", "EMBEDDING_PROVIDER", "TRANSCRIPTION_PROVIDER"):
            monkeypatch.setenv(name, "azure")
        monkeypatch.delenv("OPENAI_API_KEY")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        assert ChatAppSettings().chat_provider == "azure"

    def test_openai_without_key_and_base_url_is_rejected(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="CHAT_PROVIDER=openai needs OPENAI_API_KEY.*CHAT_BASE_URL"):
            ChatAppSettings()

    def test_openai_with_base_url_needs_no_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:8000/v1")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        s = ChatAppSettings()
        assert s.chat_base_url == s.embedding_base_url == s.transcription_base_url == "http://localhost:8000/v1"

    def test_base_url_of_one_kind_overrides_shared_url(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "http://shared/v1")
        monkeypatch.setenv("EMBEDDING_BASE_URL", "http://embedding/v1")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        s = ChatAppSettings()
        assert (s.chat_base_url, s.embedding_base_url) == ("http://shared/v1", "http://embedding/v1")

    def test_empty_base_url_means_public_openai(self, monkeypatch):
        monkeypatch.setenv("OPENAI_BASE_URL", "")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        assert ChatAppSettings().chat_base_url is None

    def test_kb_unknown_provider_is_rejected(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_PROVIDER", "gemini")
        from byoeb.kb_app.configuration.config import KbAppSettings
        with pytest.raises(ValidationError, match="EMBEDDING_PROVIDER='gemini' is not a known provider"):
            KbAppSettings()

    def test_kb_azure_without_endpoint_is_rejected(self, monkeypatch):
        monkeypatch.setenv("CHAT_PROVIDER", "azure")
        monkeypatch.delenv("AZURE_OPENAI_ENDPOINT")
        from byoeb.kb_app.configuration.config import KbAppSettings
        with pytest.raises(ValidationError, match="CHAT_PROVIDER=azure needs these settings: AZURE_OPENAI_ENDPOINT"):
            KbAppSettings()

    def test_kb_openai_without_key_and_base_url_is_rejected(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY")
        from byoeb.kb_app.configuration.config import KbAppSettings
        with pytest.raises(ValidationError, match="CHAT_PROVIDER=openai needs OPENAI_API_KEY"):
            KbAppSettings()
