import tempfile
import pytest
from wizard.env_generator import generate_env


BASE = {
    "queue": "kafka",
    "kafka_bootstrap_servers": "kafka:9092",
    "kafka_consumer_group": "byoeb",
    "kafka_topic_bot": "byoeb-bot",
    "kafka_topic_status": "byoeb-status",
    "kafka_topic_dlq": "byoeb-dlq",
    "vector_store": "llama_index_chroma",
    "storage_backend": "local",
    "local_storage_path": "/app/local_media_storage",
    "mongo_uri": "mongodb://mongodb:27017/byoeb",
    "openai_api_key": "sk-test",
    "openai_org_id": "",
    "whatsapp_token": "wa-tok",
    "whatsapp_phone_id": "12345",
    "whatsapp_verify_token": "byoeb-verify",
    "admin_username": "admin",
    "admin_password": "Secret123!",
}


def _gen(overrides=None):
    answers = {**BASE, **(overrides or {})}
    with tempfile.TemporaryDirectory() as d:
        path = generate_env(answers, output_dir=d)
        return open(path, encoding="utf-8").read()


def test_kafka_chroma_local():
    c = _gen()
    assert "QUEUE_PROVIDER=kafka" in c
    assert "KAFKA_BOOTSTRAP_SERVERS=kafka:9092" in c
    assert "VECTOR_STORE_TYPE=llama_index_chroma" in c
    assert "STORAGE_BACKEND=local" in c
    assert "MONGO_DB_CONNECTION_STRING=mongodb://mongodb:27017/byoeb" in c
    assert "OPENAI_API_KEY=sk-test" in c
    assert "ADMIN_USERNAME=admin" in c
    # password must be hashed, not plaintext
    assert "Secret123!" not in c
    assert "ADMIN_PASSWORD_HASH=" in c
    # auth + admin secrets auto-generated
    assert "AUTH_TOKEN_SECRET=" in c
    assert "ADMIN_SECRET_KEY=" in c


def test_qdrant_memory():
    c = _gen({"vector_store": "qdrant", "qdrant_mode": "memory", "qdrant_collection_name": "mydb"})
    assert "VECTOR_STORE_TYPE=qdrant" in c
    assert "QDRANT_LOCATION=:memory:" in c
    assert "QDRANT_COLLECTION_NAME=mydb" in c


def test_qdrant_docker():
    c = _gen({"vector_store": "qdrant", "qdrant_mode": "docker", "qdrant_collection_name": "mydb"})
    assert "QDRANT_HOST=qdrant" in c
    assert "QDRANT_PORT=6333" in c


def test_qdrant_cloud():
    c = _gen({
        "vector_store": "qdrant", "qdrant_mode": "cloud",
        "qdrant_url": "https://xyz.qdrant.tech",
        "qdrant_api_key": "secret-key",
        "qdrant_collection_name": "mydb",
    })
    assert "QDRANT_URL=https://xyz.qdrant.tech" in c
    assert "QDRANT_API_KEY=secret-key" in c


def test_azure_queue():
    c = _gen({
        "queue": "azure_storage_queue",
        "azure_storage_queue_account_url": "https://foo.queue.core.windows.net",
        "azure_queue_bot": "botq",
        "azure_queue_status": "statusq",
        "azure_queue_dead_letter": "dlq",
    })
    assert "QUEUE_PROVIDER=azure_storage_queue" in c
    assert "AZURE_QUEUE_BOT=botq" in c


def test_azure_blob_storage():
    c = _gen({
        "storage_backend": "azure",
        "azure_storage_blob_account_url": "https://foo.blob.core.windows.net",
        "azure_storage_container_name": "mycontainer",
    })
    assert "STORAGE_BACKEND=azure" in c
    assert "AZURE_STORAGE_CONTAINER_NAME=mycontainer" in c


def test_no_redis_references():
    c = _gen()
    assert "redis" not in c.lower()
