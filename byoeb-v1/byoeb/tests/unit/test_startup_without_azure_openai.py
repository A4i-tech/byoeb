import os
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Blocks only the two Azure OpenAI llama-index packages, then imports every module that builds an OpenAI client.
CODE = """
import importlib.abc
import sys

BLOCKED = ("llama_index.llms.azure_openai", "llama_index.embeddings.azure_openai")

class Blocker(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.startswith(BLOCKED):
            raise ImportError("blocked " + name)

sys.meta_path.insert(0, Blocker())
try:
    import llama_index.llms.azure_openai
except ImportError:
    pass
else:
    raise SystemExit("The blocker does not block the Azure OpenAI packages.")
import tests.conftest
import byoeb.chat_app.configuration.dependency_setup
import byoeb.kb_app.configuration.dependency_setup
import byoeb.services.chat.translator
loaded = [name for name in sys.modules if name.startswith(BLOCKED)]
assert not loaded, loaded
"""


def test_modules_import_without_azure_openai_packages():
    env = {k: v for k, v in os.environ.items() if k not in ("CHAT_PROVIDER", "EMBEDDING_PROVIDER", "TRANSCRIPTION_PROVIDER")}
    result = subprocess.run([sys.executable, "-c", CODE], cwd=PROJECT_ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stderr[-3000:]
