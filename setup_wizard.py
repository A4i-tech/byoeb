#!/usr/bin/env python3
"""
AshaBot / BYOEB Interactive Setup Wizard

Usage:
    pip install -r wizard/requirements.txt

    # Terminal (CLI) wizard:
    python setup_wizard.py

    # Web UI wizard (opens browser automatically):
    python setup_wizard.py --web
    python setup_wizard.py --web --port 7860
"""
import argparse


def main():
    parser = argparse.ArgumentParser(description="AshaBot setup wizard")
    parser.add_argument("--web", action="store_true", help="Launch web UI instead of CLI")
    parser.add_argument("--port", type=int, default=7860, help="Port for web UI (default: 7860)")
    args = parser.parse_args()

    if args.web:
        from wizard.web_app import run_web_wizard
        print(f"Opening AshaBot Setup Wizard at http://localhost:{args.port}")
        run_web_wizard(port=args.port, open_browser=True)
    else:
        from wizard.questions import ask_all
        from wizard.env_generator import generate_env
        from wizard.compose_helper import print_next_steps
        answers = ask_all()
        env_path = generate_env(answers)
        print_next_steps(answers, env_path)


if __name__ == "__main__":
    main()
