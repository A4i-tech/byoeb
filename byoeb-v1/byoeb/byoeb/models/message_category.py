from enum import Enum
from byoeb.chat_app.configuration.config import bot_config, app_config

class MessageCategory(Enum):
    AUDIO_IDK = "audio_idk"
    TEXT_IDK = "text_idk"
    AUDIO_IDK_RECONFIRMATION = "audio_idk_reconfirmation"

    BOT_TO_USER = "bot_to_asha"
    BOT_TO_USER_RESPONSE = "bot_to_asha_response"
    BOT_TO_EXPERT = "bot_to_anm"
    BOT_TO_EXPERT_RESPONSE = "bot_to_anm_response"
    BOT_TO_EXPERT_VERIFICATION = "bot_to_anm_verification"
    BOT_TO_EXPERT_CONSENSUS = "bot_to_anm_consensus"
    
    USER_TO_BOT = "asha_to_bot"
    EXPERT_TO_BOT = "anm_to_bot"
    READ_RECEIPT = "read_receipt"