import subprocess
import sys

SCRIPT = """
import sys
class Block:
    def find_spec(self, name, path=None, target=None):
        if name == "azure.cognitiveservices" or name.startswith("azure.cognitiveservices."):
            raise ImportError("azure speech package blocked")
sys.meta_path.insert(0, Block())
import byoeb.services.chat.translator
assert "azure.cognitiveservices.speech" not in sys.modules
print("ok")
"""


def test_adapter_module_imports_without_azure_speech_package():
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT],
        env={**__import__("os").environ, "TTS_PROVIDER": "openai", "TTS_MODEL": "tts-1", "TTS_VOICE": "alloy"},
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
