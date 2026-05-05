import yaml
from pathlib import Path

current_dir = Path(__file__).resolve().parent

bot_config_path = current_dir / "bot_config.yaml"
bot_config = yaml.safe_load(bot_config_path.read_text(encoding="utf-8"))

# Import app_config from centralized location
from byoeb.chat_app.configuration.config import app_config

# Note: keys.env is loaded by chat_app.configuration.config, no need to load here
