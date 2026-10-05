import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

BLOCKED_IMPORT_SCRIPT = """
import importlib.abc, sys

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "azure.ai.translation" or name.startswith("azure.ai.translation."):
            raise ImportError("blocked: " + name)

sys.meta_path.insert(0, Block())
from byoeb.chat_app.configuration.dependency_setup import text_translator
assert type(text_translator).__name__ == "AsyncOpenAITextTranslator", type(text_translator)
assert not any(m.startswith("azure.ai.translation") for m in sys.modules)
"""


def test_app_starts_with_openai_provider_and_azure_translation_package_blocked():
    env = {**os.environ, "TRANSLATION_PROVIDER": "openai", "TRANSLATION_MODEL": "any"}
    result = subprocess.run(
        [sys.executable, "-c", BLOCKED_IMPORT_SCRIPT], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setenv("MONGO_DB_CONNECTION_STRING", "mongodb://localhost:27017/test")
    for name in ("TRANSLATION_PROVIDER", "TRANSLATION_MODEL", "TRANSLATION_BASE_URL", "TRANSLATION_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def make_settings():
    from byoeb.chat_app.configuration.config import ChatAppSettings
    return ChatAppSettings()


def test_provider_defaults_to_openai_and_requires_model(settings_env):
    with pytest.raises(ValidationError, match="TRANSLATION_MODEL"):
        make_settings()
    settings_env.setenv("TRANSLATION_MODEL", "m1")
    assert make_settings().translation_provider == "openai"


def test_unknown_provider_names_allowed_values(settings_env):
    settings_env.setenv("TRANSLATION_PROVIDER", "deepl")
    with pytest.raises(ValidationError, match="'azure' or 'openai'"):
        make_settings()


def test_azure_provider_needs_azure_settings(settings_env):
    settings_env.setenv("TRANSLATION_PROVIDER", "azure")
    assert make_settings().translation_provider == "azure"
    settings_env.delenv("AZURE_COGNITIVE_REGION")
    with pytest.raises(ValidationError, match="AZURE_COGNITIVE_REGION"):
        make_settings()
