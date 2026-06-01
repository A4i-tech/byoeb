import os
import pytest
import yaml

from wizard.compose_generator import generate_app_compose

ANSWERS_KAFKA_CHROMA = {
    "queue": "kafka",
    "kafka_bootstrap_servers": "kafka:9092",
    "kafka_consumer_group": "byoeb",
    "kafka_topic_bot": "byoeb-bot",
    "kafka_topic_status": "byoeb-status",
    "kafka_topic_dlq": "byoeb-dlq",
    "vector_store": "llama_index_chroma",
    "storage_backend": "local",
}

ANSWERS_QDRANT_DOCKER = {
    **ANSWERS_KAFKA_CHROMA,
    "vector_store": "qdrant",
    "qdrant_mode": "docker",
}


def test_output_file_written(tmp_path):
    path = generate_app_compose(ANSWERS_KAFKA_CHROMA, output_dir=str(tmp_path))
    assert os.path.isfile(path)
    assert path.endswith("docker-compose.app.yml")


def test_uses_registry_image_not_build(tmp_path):
    path = generate_app_compose(ANSWERS_KAFKA_CHROMA, output_dir=str(tmp_path))
    with open(path) as f:
        content = f.read()
    assert "build:" not in content
    assert "ghcr.io/" in content


def test_both_app_services_present(tmp_path):
    path = generate_app_compose(ANSWERS_KAFKA_CHROMA, output_dir=str(tmp_path))
    with open(path) as f:
        data = yaml.safe_load(f)
    assert "byoeb-chat" in data["services"]
    assert "byoeb-kb" in data["services"]


def test_kafka_service_present(tmp_path):
    path = generate_app_compose(ANSWERS_KAFKA_CHROMA, output_dir=str(tmp_path))
    with open(path) as f:
        data = yaml.safe_load(f)
    assert "kafka" in data["services"]
    listeners = data["services"]["kafka"]["environment"]["KAFKA_ADVERTISED_LISTENERS"]
    assert "kafka:9092" in listeners


def test_mongodb_service_present(tmp_path):
    path = generate_app_compose(ANSWERS_KAFKA_CHROMA, output_dir=str(tmp_path))
    with open(path) as f:
        data = yaml.safe_load(f)
    assert "mongodb" in data["services"]


def test_qdrant_service_only_when_docker_mode(tmp_path):
    path_no_qdrant = generate_app_compose(ANSWERS_KAFKA_CHROMA, output_dir=str(tmp_path))
    with open(path_no_qdrant) as f:
        data_no = yaml.safe_load(f)
    assert "qdrant" not in data_no["services"]

    path_qdrant = generate_app_compose(ANSWERS_QDRANT_DOCKER, output_dir=str(tmp_path))
    with open(path_qdrant) as f:
        data_yes = yaml.safe_load(f)
    assert "qdrant" in data_yes["services"]


def test_env_file_referenced(tmp_path):
    path = generate_app_compose(ANSWERS_KAFKA_CHROMA, output_dir=str(tmp_path))
    with open(path) as f:
        data = yaml.safe_load(f)
    chat = data["services"]["byoeb-chat"]
    assert ".env.local" in (chat.get("env_file") or [])


def test_qdrant_volume_in_volumes_block(tmp_path):
    path = generate_app_compose(ANSWERS_QDRANT_DOCKER, output_dir=str(tmp_path))
    with open(path) as f:
        data = yaml.safe_load(f)
    assert "qdrant_data" in (data.get("volumes") or {})
