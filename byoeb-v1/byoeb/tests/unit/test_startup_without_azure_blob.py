import os
import subprocess
import sys
from pathlib import Path

import pytest

BYOEB_DIR = Path(__file__).resolve().parents[2]

# Runs in a fresh interpreter so modules that tests imported earlier cannot hide a missing package.
_SCRIPT = """
import importlib.abc
import sys


class BlockAzureBlob(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name == "azure.storage.blob" or name.startswith("azure.storage.blob."):
            raise ImportError(f"azure blob package blocked by test: {name}")


sys.meta_path.insert(0, BlockAzureBlob())
try:
    import azure.storage.blob
except ImportError:
    pass
else:
    raise SystemExit("the block did not work")

import tests.conftest
from byoeb.chat_app.configuration import dependency_setup as chat
from byoeb.kb_app.configuration import dependency_setup as kb
import byoeb.scripts.knowledge_base.upload_to_blob

assert "azure.storage.blob" not in sys.modules
print(*(type(s).__name__ for s in (chat.media_storage, kb.amedia_storage, kb.amedia_storage_analysis)))
"""


@pytest.mark.parametrize(
    "backend, env, expected",
    [
        ("local", {}, "LocalFileStorage LocalFileStorage NoneType"),
        (
            "s3",
            {
                "S3_ENDPOINT_URL": "http://localhost:9000",
                "S3_ACCESS_KEY_ID": "test-access-key",
                "S3_SECRET_ACCESS_KEY": "test-secret-key",
                "S3_BUCKET_NAME": "byoeb-media",
                "S3_ANALYSIS_BUCKET_NAME": "test-bucket",
            },
            "S3MediaStorage S3MediaStorage S3MediaStorage",
        ),
    ],
)
def test_storage_modules_import_without_azure_blob_package(backend, env, expected):
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", _SCRIPT],
        cwd=BYOEB_DIR,
        env={**os.environ, "STORAGE_BACKEND": backend, **env},
        capture_output=True,
        text=True,
        timeout=600,
    )

    assert result.returncode == 0, result.stderr[-3000:]
    assert result.stdout.strip().splitlines()[-1] == expected
