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

    def test_s3_backend_requires_credentials_and_bucket(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
        monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
        monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="S3_BUCKET_NAME, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY"):
            ChatAppSettings()

    def test_s3_backend_needs_no_azure_settings(self, monkeypatch):
        for name in ("AZURE_STORAGE_CONTAINER_NAME", "AZURE_STORAGE_BLOB_ACCOUNT_URL", "AZURE_STORAGE_CONNECTION_STRING"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("S3_BUCKET_NAME", "byoeb-media")
        monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
        monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        assert ChatAppSettings().s3_bucket_name == "byoeb-media"

    def test_unknown_storage_backend_is_rejected(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "gcs")
        monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
        from byoeb.chat_app.configuration.config import ChatAppSettings
        with pytest.raises(ValidationError, match="Use local, azure or s3"):
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
        assert s.storage_backend == "local"

    def test_kb_s3_backend_requires_credentials(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("S3_BUCKET_NAME", "byoeb-media")
        monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
        monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
        from byoeb.kb_app.configuration.config import KbAppSettings
        with pytest.raises(ValidationError, match="S3_ACCESS_KEY_ID"):
            KbAppSettings()

    def test_kb_s3_backend_needs_no_azure_settings(self, monkeypatch):
        for name in ("AZURE_STORAGE_CONTAINER_NAME", "AZURE_STORAGE_ANALYSIS_CONTAINER_NAME", "AZURE_STORAGE_BLOB_ACCOUNT_URL", "AZURE_STORAGE_CONNECTION_STRING"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("S3_BUCKET_NAME", "byoeb-media")
        monkeypatch.setenv("S3_ANALYSIS_BUCKET_NAME", "test-bucket")
        monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
        monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
        from byoeb.kb_app.configuration.config import KbAppSettings
        s = KbAppSettings()
        assert (s.s3_bucket_name, s.s3_analysis_bucket_name) == ("byoeb-media", "test-bucket")
