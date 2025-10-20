import os
import json
from dotenv import load_dotenv
from pathlib import Path

# Get the directory of the current script
current_dir = Path(__file__).resolve().parent

bot_config_path = current_dir / "bot_config.json"
bot_config = json.loads(bot_config_path.read_text())

environment_path = current_dir / ".." / ".." / ".." / "keys.env"
load_dotenv(environment_path)