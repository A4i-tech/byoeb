"""Interactive prompts for AshaBot setup wizard."""
import questionary
from rich.console import Console
from rich.panel import Panel

console = Console()


def ask_all() -> dict:
    console.print(Panel.fit(
        "[bold cyan]AshaBot Setup Wizard[/bold cyan]\n"
        "[dim]Sets up your local .env.local — takes ~2 minutes[/dim]",
        border_style="cyan",
    ))
    console.print()

    answers = {}

    # ── Queue backend ────────────────────────────────────────────────────────
    console.rule("[bold]1. Queue Backend[/bold]")
    answers["queue"] = questionary.select(
        "Which message queue should AshaBot use?",
        choices=[
            questionary.Choice("Kafka  (recommended — persistent, production-grade)", value="kafka"),
            questionary.Choice("Azure Storage Queue  (if you already have Azure)", value="azure_storage_queue"),
        ],
    ).ask()

    if answers["queue"] == "kafka":
        answers["kafka_bootstrap_servers"] = questionary.text(
            "Kafka bootstrap servers:",
            default="kafka:9092",
            instruction="(use 'kafka:9092' for docker compose, 'localhost:9092' for local Kafka)",
        ).ask()
        answers["kafka_consumer_group"] = questionary.text(
            "Kafka consumer group:", default="byoeb"
        ).ask()
        answers["kafka_topic_bot"] = questionary.text("Bot topic name:", default="byoeb-bot").ask()
        answers["kafka_topic_status"] = questionary.text("Status topic name:", default="byoeb-status").ask()
        answers["kafka_topic_dlq"] = questionary.text("Dead-letter topic:", default="byoeb-dlq").ask()
    else:
        answers["azure_storage_queue_account_url"] = questionary.text(
            "Azure Storage Queue account URL:"
        ).ask()
        answers["azure_queue_bot"] = questionary.text("Bot queue name:").ask()
        answers["azure_queue_status"] = questionary.text("Status queue name:").ask()
        answers["azure_queue_dead_letter"] = questionary.text("Dead-letter queue name:").ask()

    # ── Vector store ─────────────────────────────────────────────────────────
    console.rule("[bold]2. Vector Store[/bold]")
    answers["vector_store"] = questionary.select(
        "Which vector store for knowledge base?",
        choices=[
            questionary.Choice("ChromaDB  (recommended — local, no extra setup)", value="llama_index_chroma"),
            questionary.Choice("Qdrant    (local in-memory / Docker / Cloud)", value="qdrant"),
            questionary.Choice("Azure AI Search  (if you already have Azure)", value="azure_vector_search"),
        ],
    ).ask()

    if answers["vector_store"] == "qdrant":
        mode = questionary.select(
            "Qdrant deployment mode:",
            choices=[
                questionary.Choice("In-memory  (no Docker needed, data lost on restart)", value="memory"),
                questionary.Choice("Local Docker  (persistent, run: docker compose --profile qdrant up)", value="docker"),
                questionary.Choice("Qdrant Cloud  (fully managed)", value="cloud"),
            ],
        ).ask()
        answers["qdrant_mode"] = mode
        if mode == "cloud":
            answers["qdrant_url"] = questionary.text("Qdrant Cloud URL:").ask()
            answers["qdrant_api_key"] = questionary.password("Qdrant API key:").ask()
        answers["qdrant_collection_name"] = questionary.text(
            "Qdrant collection name:", default="byoeb-kb"
        ).ask()

    elif answers["vector_store"] == "azure_vector_search":
        answers["azure_search_service_name"] = questionary.text("Azure Search service name:").ask()
        answers["azure_search_index_name"] = questionary.text("Azure Search index name:").ask()
        answers["azure_search_api_key"] = questionary.password("Azure Search API key:").ask()

    # ── Storage backend ──────────────────────────────────────────────────────
    console.rule("[bold]3. File Storage[/bold]")
    answers["storage_backend"] = questionary.select(
        "Where should media files (audio, images) be stored?",
        choices=[
            questionary.Choice("Local filesystem  (recommended for local setup)", value="local"),
            questionary.Choice("Azure Blob Storage", value="azure"),
        ],
    ).ask()

    if answers["storage_backend"] == "local":
        answers["local_storage_path"] = questionary.text(
            "Local storage path:", default="/app/local_media_storage"
        ).ask()
    else:
        answers["azure_storage_blob_account_url"] = questionary.text(
            "Azure Blob Storage account URL:"
        ).ask()
        answers["azure_storage_container_name"] = questionary.text(
            "Azure Blob container name:"
        ).ask()

    # ── MongoDB ──────────────────────────────────────────────────────────────
    console.rule("[bold]4. Database[/bold]")
    answers["mongo_uri"] = questionary.text(
        "MongoDB connection string:",
        default="mongodb://mongodb:27017/byoeb",
        instruction="(use default for docker compose)",
    ).ask()

    # ── LLM ─────────────────────────────────────────────────────────────────
    console.rule("[bold]5. LLM (OpenAI)[/bold]")  # noqa: keep numbering
    answers["openai_api_key"] = questionary.password(
        "OpenAI API key:",
        validate=lambda v: len(v) > 10 or "API key seems too short",
    ).ask()
    answers["openai_org_id"] = questionary.text(
        "OpenAI org ID:", default="", instruction="(leave blank if none)"
    ).ask()

    # ── Azure Cognitive Services ─────────────────────────────────────────────
    console.rule("[bold]6. Azure Cognitive Services[/bold]")
    console.print("[dim]Required for speech-to-text, text-to-speech and translation.[/dim]")
    answers["azure_cognitive_region"] = questionary.text(
        "Azure region:", default="eastus",
        instruction="(e.g. eastus, westeurope)",
    ).ask()
    answers["azure_cognitive_text_to_text_resource"] = questionary.text(
        "Text translation resource name:",
        instruction="(Azure Translator resource name, e.g. my-translator)",
    ).ask()
    answers["azure_cognitive_text_to_speech_resource"] = questionary.text(
        "Speech resource name:",
        instruction="(Azure Speech resource name, e.g. my-speech)",
    ).ask()
    answers["azure_cognitive_key"] = questionary.password(
        "Azure Cognitive Services key:", instruction="(leave blank to use managed identity)"
    ).ask()
    answers["azure_cognitive_endpoint"] = questionary.text(
        "Cognitive endpoint:", default="",
        instruction="(optional base URL override, e.g. https://eastus.api.cognitive.microsoft.com/)"
    ).ask()

    # ── WhatsApp ─────────────────────────────────────────────────────────────
    console.rule("[bold]7. WhatsApp[/bold]")
    answers["whatsapp_token"] = questionary.password("WhatsApp Cloud API access token:").ask()
    answers["whatsapp_phone_id"] = questionary.text("WhatsApp phone number ID:").ask()
    answers["whatsapp_verify_token"] = questionary.text(
        "WhatsApp webhook verify token:", default="byoeb-verify"
    ).ask()

    # ── Admin panel ──────────────────────────────────────────────────────────
    console.rule("[bold]8. Admin Panel[/bold]")
    answers["admin_username"] = questionary.text("Admin username:", default="admin").ask()
    answers["admin_password"] = questionary.password(
        "Admin password (min 8 chars):",
        validate=lambda v: len(v) >= 8 or "Must be at least 8 characters",
    ).ask()

    return answers
