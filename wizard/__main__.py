"""Entry point for `python -m wizard` — starts the web setup wizard."""
from wizard.web_app import run_web_wizard

if __name__ == "__main__":
    run_web_wizard(port=5001, open_browser=False)
