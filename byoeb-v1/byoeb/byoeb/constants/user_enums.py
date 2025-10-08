from enum import Enum

class UserType(Enum):
    """Enum for different types of users in the system."""
    ASHA = "asha"
    ANM = "anm"
    OTHERS = "others"

class LanguageCode(Enum):
    """Enum for supported language codes."""
    HINDI = "hi"
    ENGLISH = "en"
    MARATHI = "mr"
    TELUGU = "te"
