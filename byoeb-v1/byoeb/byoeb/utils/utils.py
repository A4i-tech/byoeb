import os
from byoeb.services.chat import constants
from urllib.parse import unquote
from pathlib import Path

def get_git_root_path():
    current_dir = os.path.abspath(__file__)
    try:
        while current_dir != os.path.dirname(current_dir):  # Stop at the filesystem root
            if os.path.isdir(os.path.join(current_dir, ".github")):
                return current_dir
            current_dir = os.path.dirname(current_dir)
        return current_dir
    except Exception as e:
        print(f"Error: {str(e)}")
        return None
    
def log_to_text_file(text):
    file_path = Path("byoeb-v1/byoeb/log.txt")  # relative path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with file_path.open("a", encoding="utf-8") as f:
        f.write(text + "\n")

def is_idk(
    text: str
):
    idks = [
        "idk",
        "i don't know",
        "i do not know",
        "i don't know the answer",
        "i do not know the answer to your question"
    ]
    text = text.lower()
    return any(idk in text for idk in idks)  # Check if any phrase exists in text

def is_onboard(
    text: str,
    lang: str = "en"
):
    match lang:
        case "en": onboards = constants.ONBOARD_MESSAGES_EN
        case "hi": onboards = constants.ONBOARD_MESSAGES_HI
        case "kn": onboards = constants.ONBOARD_MESSAGES_KN
        case "mr": onboards = constants.ONBOARD_MESSAGES_MR
        case "te": onboards = constants.ONBOARD_MESSAGES_TE
        case _:    onboards = []  # TODO: we should probably raise a ValueError than short-circuiting a False for unexpected languages.
    text = unquote(text)  # "%20%" -> " "
    text = text.lower().replace("-", " ")  # "onboard-asha" -> "onboard asha"
    return any(phrase in text for phrase in onboards)  # Check if any phrase exists in text
