import os
import pytest
from unittest.mock import patch

from wizard.compose_helper import _compose_command, _is_in_docker


def test_compose_command_default_no_docker():
    """Outside Docker: no -f flag, no --project-directory."""
    answers = {"queue": "kafka", "vector_store": "llama_index_chroma"}
    cmd = _compose_command(answers, in_docker=False)
    assert cmd == ["docker", "compose", "up", "--build", "-d"]


def test_compose_command_in_docker_uses_workspace_path():
    """Inside Docker: uses /workspace path, not HOST_PWD (avoids Windows path issues on Linux Docker CLI)."""
    answers = {"queue": "kafka", "vector_store": "llama_index_chroma"}
    cmd = _compose_command(answers, in_docker=True)
    assert "-f" in cmd
    assert "/workspace/docker-compose.app.yml" in cmd
    assert "--project-directory" in cmd
    assert "/workspace" in cmd


def test_compose_command_in_docker_no_build_flag():
    """Inside Docker: uses --pull always, NOT --build (images are pre-built)."""
    answers = {"queue": "kafka", "vector_store": "llama_index_chroma"}
    cmd = _compose_command(answers, in_docker=True)
    assert "--build" not in cmd
    assert "--pull" in cmd


def test_compose_command_qdrant_profile():
    """Qdrant docker mode adds --profile qdrant."""
    answers = {"queue": "kafka", "vector_store": "qdrant", "qdrant_mode": "docker"}
    cmd = _compose_command(answers, in_docker=False)
    assert "--profile" in cmd
    assert "qdrant" in cmd


def test_is_in_docker_env_var():
    with patch.dict(os.environ, {"RUNNING_IN_DOCKER": "1"}):
        assert _is_in_docker() is True

def test_is_not_in_docker_by_default():
    env = {k: v for k, v in os.environ.items() if k != "RUNNING_IN_DOCKER"}
    with patch.dict(os.environ, env, clear=True):
        result = _is_in_docker()
        assert isinstance(result, bool)
