import json
from pathlib import Path

# Get the directory of the current script
current_dir = Path(__file__).resolve().parent

bot_config_path = current_dir / "bot_config.json"
bot_config = json.loads(bot_config_path.read_text(encoding="utf-8"))

# Note: keys.env is loaded by chat_app.configuration.config, no need to load here