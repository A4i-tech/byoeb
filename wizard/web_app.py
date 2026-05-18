"""Flask-based web setup wizard for AshaBot / BYOEB."""
import json
import os
import queue
import subprocess
import threading
import webbrowser

from flask import Flask, Response, render_template, request, jsonify

from wizard.env_generator import generate_env
from wizard.compose_helper import _compose_command, _docker_available

app = Flask(__name__, template_folder="templates")
app.secret_key = os.urandom(24)

# shared state for SSE streaming
_log_queue: queue.Queue = queue.Queue()
_launch_status = {"done": False, "success": False}


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.post("/api/generate")
def api_generate():
    """Write .env.local from submitted answers. Return path + docker status."""
    answers = request.get_json(force=True)
    try:
        path = generate_env(answers, output_dir=".")
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    docker_ok = _docker_available()
    return jsonify({"ok": True, "env_path": path, "docker_available": docker_ok})


@app.post("/api/launch")
def api_launch():
    """Start docker compose in background thread; stream via /api/stream."""
    answers = request.get_json(force=True)
    cmd = _compose_command(answers)

    global _launch_status
    _launch_status = {"done": False, "success": False}

    def _run():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in process.stdout:
            _log_queue.put(line.rstrip())
        process.wait()
        _launch_status["done"] = True
        _launch_status["success"] = process.returncode == 0
        _log_queue.put(
            "__DONE_OK__" if process.returncode == 0 else "__DONE_ERR__"
        )

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True})


@app.get("/api/stream")
def api_stream():
    """SSE endpoint — streams docker compose log lines."""
    def _generate():
        while True:
            try:
                line = _log_queue.get(timeout=30)
                yield f"data: {json.dumps(line)}\n\n"
                if line.startswith("__DONE_"):
                    break
            except queue.Empty:
                yield "data: {\"ping\": true}\n\n"

    return Response(_generate(), mimetype="text/event-stream")


@app.get("/api/docker-check")
def api_docker_check():
    return jsonify({"available": _docker_available()})


# ---------------------------------------------------------------------------
# Entry point (called from setup_wizard.py --web)
# ---------------------------------------------------------------------------

def run_web_wizard(port: int = 7860, open_browser: bool = True):
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
