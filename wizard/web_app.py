"""Flask-based web setup wizard for AshaBot / BYOEB."""
import json
import os
import pathlib
import queue
import subprocess
import threading
import time
import webbrowser

import requests
from flask import Flask, Response, render_template, request, jsonify

from wizard.env_generator import generate_env
from wizard.compose_helper import _compose_command, _docker_available, _is_in_docker
from wizard.compose_generator import generate_app_compose

# Folder with bundled sample documents (relative to repo root, i.e. cwd when wizard runs)
_SAMPLE_KB_DIR = pathlib.Path("sample_kb")

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
    """Write .env.local + docker-compose.app.yml from submitted answers."""
    answers = request.get_json(force=True)

    # When running inside the wizard Docker container, write to the mounted
    # host directory so Docker (via socket) can read the files by HOST path.
    output_dir = "/workspace" if _is_in_docker() else "."

    try:
        env_path = generate_env(answers, output_dir=output_dir)
        generate_app_compose(answers, output_dir=output_dir)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    docker_ok = _docker_available()
    return jsonify({"ok": True, "env_path": env_path, "docker_available": docker_ok})


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
        # If already finished (e.g. browser reconnected after done), replay result immediately
        if _launch_status["done"]:
            sentinel = "__DONE_OK__" if _launch_status["success"] else "__DONE_ERR__"
            yield f"data: {json.dumps(sentinel)}\n\n"
            return
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


@app.get("/api/kb-health")
def api_kb_health():
    """Proxy KB health check — avoids browser CORS issues across ports."""
    kb_base = "http://host.docker.internal:8001" if _is_in_docker() else "http://localhost:8001"
    try:
        resp = requests.get(f"{kb_base}/docs", timeout=3)
        return jsonify({"available": resp.status_code < 500})
    except Exception:
        return jsonify({"available": False})


@app.post("/api/setup-mcp-user")
def api_setup_mcp_user():
    """
    After containers are healthy, auto-create a test ASHA user + MCP auth user.
    Returns MCP connection URL and credentials.
    """
    body = request.get_json(force=True) or {}
    admin_username = body.get("admin_username", os.environ.get("ADMIN_USERNAME", "admin"))
    admin_password = body.get("admin_password", os.environ.get("ADMIN_PASSWORD", ""))
    chat_base = "http://host.docker.internal:8000" if _is_in_docker() else "http://localhost:8000"

    try:
        # 1. Get admin token + CSRF via cookie session
        sess = requests.Session()
        r = sess.post(f"{chat_base}/auth/token/issue", data={
            "username": admin_username,
            "password": admin_password,
        }, timeout=10)
        if r.status_code != 200:
            return jsonify({"ok": False, "error": f"Admin login failed: {r.status_code}"}), 400

        csrf_token = sess.cookies.get("csrf_token", "")

        # 2. Get tenant ID from /auth/me
        me = sess.get(f"{chat_base}/auth/me", timeout=5).json()
        tenant_id = (me.get("tenants") or [{}])[0].get("tenant_id")
        if not tenant_id:
            return jsonify({"ok": False, "error": "Could not determine tenant ID"}), 400

        # 3. Create ASHA user record
        mcp_phone = "91000000001"
        mcp_username = "mcpuser"
        mcp_password = admin_password  # reuse admin password for simplicity

        sess.post(f"{chat_base}/register_users",
            json=[{
                "phone_number_id": mcp_phone,
                "user_location": {"district": "Local"},
                "user_type": "asha",
                "user_language": "en",
            }],
            headers={"X-CSRF-Token": csrf_token},
            timeout=10,
        )

        # 4. Create auth user (ignore error if already exists)
        sess.post(f"{chat_base}/auth/users",
            json={
                "username": mcp_username,
                "password": mcp_password,
                "tenant_id": tenant_id,
                "roles": ["admin"],
                "phone_number_id": mcp_phone,
            },
            headers={"X-CSRF-Token": csrf_token},
            timeout=10,
        )

        return jsonify({
            "ok": True,
            "mcp_url": "http://127.0.0.1:8000/mcp",
            "mcp_username": mcp_username,
            "mcp_password": mcp_password,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/sample-docs")
def api_sample_docs():
    """List sample KB documents shipped with the repo."""
    docs = []
    if _SAMPLE_KB_DIR.is_dir():
        descriptions = {
            "app_faq.txt":              "AshaBot app FAQ — PIN reset, features, how to use",
            "immunization_schedule.txt":"India national immunization schedule (all vaccines & ages)",
            "dengue_chikungunya.txt":   "Dengue & chikungunya — symptoms, prevention, treatment",
            "tuberculosis_faq.txt":     "Tuberculosis FAQ — causes, symptoms, treatment",
            "iron_folic_acid_faq.txt":  "Weekly Iron & Folic Acid (WIFS) FAQ — anaemia, supplements",
            "safe_motherhood.txt":      "Safe motherhood guide — ANC, delivery, postnatal care",
        }
        for f in sorted(_SAMPLE_KB_DIR.iterdir()):
            if f.suffix == ".txt":
                docs.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "description": descriptions.get(f.name, ""),
                })
    return jsonify(docs)


@app.post("/api/seed-kb")
def api_seed_kb():
    """Upload selected sample docs to KB service and trigger indexing."""
    body = request.get_json(force=True)
    selected = body.get("files", [])          # list of filenames from sample_kb/
    kb_url = body.get("kb_url", "http://localhost:8001")
    # Inside the wizard container, localhost refers to the container itself.
    # Use host.docker.internal to reach the KB service mapped on the host.
    if _is_in_docker():
        kb_url = "http://host.docker.internal:8001"

    results = []
    uploaded = []

    # 1. Upload each file
    for name in selected:
        path = _SAMPLE_KB_DIR / name
        if not path.exists():
            results.append({"file": name, "ok": False, "error": "not found"})
            continue
        try:
            with open(path, "rb") as fh:
                resp = requests.post(
                    f"{kb_url}/storage/file",
                    files={"file": (name, fh, "text/plain")},
                    timeout=30,
                )
            if resp.status_code in (200, 201, 204):
                uploaded.append(name)
                results.append({"file": name, "ok": True, "stage": "uploaded"})
            else:
                results.append({"file": name, "ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"})
        except Exception as exc:
            results.append({"file": name, "ok": False, "error": str(exc)})

    # 2. Index all successfully uploaded files
    indexed = 0
    if uploaded:
        try:
            params = [("files", f) for f in uploaded]
            resp = requests.get(f"{kb_url}/vector/index", params=params, timeout=120)
            if resp.status_code == 200:
                indexed = len(uploaded)
                for r in results:
                    if r.get("ok"):
                        r["stage"] = "indexed"
        except Exception as exc:
            for r in results:
                if r.get("ok"):
                    r["index_error"] = str(exc)

    return jsonify({"ok": True, "results": results, "indexed": indexed})


# ---------------------------------------------------------------------------
# Entry point (called from setup_wizard.py --web)
# ---------------------------------------------------------------------------

def run_web_wizard(port: int = 7860, open_browser: bool = True):
    if open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
