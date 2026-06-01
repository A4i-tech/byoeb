"""Print next steps and optionally launch docker compose after .env.local is generated."""
import os
import pathlib
import subprocess
import sys
import time
import webbrowser
import urllib.request
import urllib.error

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

console = Console()


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------

def _docker_available() -> bool:
    """Return True if docker CLI is reachable and daemon is running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _is_in_docker() -> bool:
    """Return True when this process is running inside a Docker container."""
    return (
        pathlib.Path("/.dockerenv").exists()
        or os.environ.get("RUNNING_IN_DOCKER", "") == "1"
    )


def _compose_command(answers: dict, in_docker: bool | None = None) -> list[str]:
    """
    Build the docker compose command list.

    When running inside Docker (in_docker=True), the wizard container has the
    host Docker socket mounted. Docker interprets paths from the HOST perspective,
    so we must pass HOST_PWD (set in docker-compose.wizard.yml via ${PWD}) and
    reference the generated docker-compose.app.yml by its HOST path.

    Outside Docker (normal dev / git-clone flow), we run against the
    docker-compose.yml already present in the working directory and use
    --build to compile from source.
    """
    if in_docker is None:
        in_docker = _is_in_docker()

    profiles = []
    if answers.get("vector_store") == "qdrant" and answers.get("qdrant_mode") == "docker":
        profiles.append("qdrant")

    cmd = ["docker", "compose"]

    if in_docker:
        host_pwd = os.environ.get("HOST_PWD", "/workspace")
        cmd += ["-f", f"{host_pwd}/docker-compose.app.yml"]
        cmd += ["--project-directory", host_pwd]

    for p in profiles:
        cmd += ["--profile", p]

    if in_docker:
        cmd += ["up", "--pull", "always", "-d"]
    else:
        cmd += ["up", "--build", "-d"]

    return cmd


def _run_compose(cmd: list[str]) -> bool:
    """Stream docker compose output. Return True on success."""
    console.print()
    console.print("[bold cyan]Starting services...[/bold cyan]")
    console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
    console.print()

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    for line in process.stdout:
        line = line.rstrip()
        if line:
            # colour docker compose status lines
            if "Pulling" in line or "Downloading" in line or "Extracting" in line:
                console.print(f"[dim]{line}[/dim]")
            elif "Started" in line or "Running" in line or "healthy" in line:
                console.print(f"[green]{line}[/green]")
            elif "Error" in line or "error" in line or "failed" in line:
                console.print(f"[red]{line}[/red]")
            else:
                console.print(line)

    process.wait()
    return process.returncode == 0


def _wait_for_url(url: str, label: str, timeout: int = 120) -> bool:
    """Poll url until HTTP 200 or timeout. Return True if healthy."""
    with Progress(
        SpinnerColumn(),
        TextColumn(f"[cyan]Waiting for {label}..."),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task("", total=None)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if resp.status < 500:
                        return True
            except Exception:
                pass
            time.sleep(3)
    return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def print_next_steps(answers: dict, env_path: str):
    profiles = []
    if answers.get("vector_store") == "qdrant" and answers.get("qdrant_mode") == "docker":
        profiles.append("qdrant")

    profile_flag = "".join(f" --profile {p}" for p in profiles)
    compose_cmd_str = f"docker compose{profile_flag} up --build -d"

    # --- summary table ---
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
        "[bold]To start AshaBot manually:[/bold]\n"
        f"  [cyan]{compose_cmd_str}[/cyan]\n\n"
        "[bold]Admin panel:[/bold]\n"
        "  [cyan]http://localhost:8000/admin[/cyan]\n\n"
        "[dim]Tip: expose port 8000 via ngrok for WhatsApp webhook testing[/dim]",
        title="[bold]Next steps[/bold]",
        border_style="cyan",
    ))

    # --- offer to start docker ---
    if not _docker_available():
        console.print(Panel(
            "[bold red]Docker is not running.[/bold red]\n\n"
            "Please install Docker Desktop and start it, then run:\n\n"
            f"  [cyan]{compose_cmd_str}[/cyan]\n\n"
            "[link=https://docs.docker.com/get-docker/]https://docs.docker.com/get-docker/[/link]",
            title="[bold red]⚠ Docker not found[/bold red]",
            border_style="red",
        ))
        return

    start_now = questionary.confirm(
        "Start AshaBot now with Docker?",
        default=True,
    ).ask()

    if not start_now:
        console.print(
            f"\n[dim]When ready, run:[/dim] [cyan]{compose_cmd_str}[/cyan]\n"
        )
        return

    cmd = _compose_command(answers)
    success = _run_compose(cmd)

    if not success:
        console.print(Panel(
            "Docker Compose exited with an error.\n"
            "Check the output above for details.\n\n"
            "Common fixes:\n"
            "  • Make sure port 8000 and 27017 are free\n"
            "  • Run [cyan]docker compose logs[/cyan] for more detail",
            title="[bold red]⚠ Startup failed[/bold red]",
            border_style="red",
        ))
        return

    # --- health checks ---
    console.print()
    chat_ok = _wait_for_url("http://localhost:8000/health", "chat app")
    kb_ok = _wait_for_url("http://localhost:8001/health", "KB app")

    if chat_ok and kb_ok:
        console.print(Panel(
            "[bold green]✓ AshaBot is up![/bold green]\n\n"
            "[bold]Admin panel:[/bold]  [cyan]http://localhost:8000/admin[/cyan]\n"
            "[bold]KB API docs:[/bold]  [cyan]http://localhost:8001/docs[/cyan]\n\n"
            "[bold]WhatsApp webhook:[/bold]\n"
            "  1. Run [cyan]ngrok http 8000[/cyan]\n"
            f"  2. Set webhook URL to [cyan]https://<ngrok-url>/webhook[/cyan]\n"
            f"  3. Verify token: [cyan]{answers.get('whatsapp_verify_token', 'byoeb-verify')}[/cyan]",
            title="[bold green]🚀 Ready[/bold green]",
            border_style="green",
        ))
        # open admin panel in browser automatically
        webbrowser.open("http://localhost:8000/admin")
    else:
        console.print(Panel(
            "Services started but health check timed out.\n"
            "Run [cyan]docker compose logs[/cyan] to check for errors.",
            title="[bold yellow]⚠ Services slow to start[/bold yellow]",
            border_style="yellow",
        ))
