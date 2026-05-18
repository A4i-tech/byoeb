"""Print next steps after .env.local is generated."""
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_next_steps(answers: dict, env_path: str):
    profiles = []
    if answers.get("vector_store") == "qdrant" and answers.get("qdrant_mode") == "docker":
        profiles.append("qdrant")

    profile_flag = "".join(f" --profile {p}" for p in profiles)
    compose_cmd = f"docker compose{profile_flag} up --build -d"

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="bold green")
    table.add_column()
    table.add_row("Queue:", answers["queue"])
    table.add_row("Vector store:", answers["vector_store"])
    table.add_row("Storage:", answers["storage_backend"])
    table.add_row("Admin user:", answers.get("admin_username", "admin"))

    console.print()
    console.print(Panel(
        table,
        title="[bold green]✓ Configuration summary[/bold green]",
        border_style="green",
    ))

    console.print(Panel(
        f"[bold].env.local written to:[/bold] {env_path}\n\n"
        "[bold]Start AshaBot:[/bold]\n"
        f"  [cyan]{compose_cmd}[/cyan]\n\n"
        "[bold]Admin panel:[/bold]\n"
        "  [cyan]http://localhost:8000/admin[/cyan]\n\n"
        "[dim]Tip: expose port 8000 via ngrok for WhatsApp webhook testing[/dim]",
        title="[bold]Next steps[/bold]",
        border_style="cyan",
    ))
