import pytest
from byoeb.utils.utils import is_onboard

@pytest.mark.parametrize("text,lang,expected", [
    # english tests
    ("onboard-asha", "en", True),
    ("Need to onboard asha quickly", "en", True),
    ("ONBOARD ASHA", "en", True),  # case insensitive test
    ("this isOnboard-asha test", "en", True),  # substring test
    ("onboard", "en", False),  # partial phrase test
    ("random text", "en", False),

    # hindi tests
    ("में एक आशा हूँ और मुझे आशा सहेली बोट से जुड़ना है", "hi", True),
    ("  में एक आशा हूँ और मुझे आशा सहेली बोट से जुड़ना है  ", "hi", True),  # with space
    ("नमस्ते", "hi", False),

    # kannada tests
    ("ನಾನು ಆಶಾ ಮತ್ತು ನಾನು ಆಶಾ ಸಹೇಲಿ ಬಾಟ್‌ಗೆ ಸೇರಲು ಬಯಸುತ್ತೇನೆ", "kn", True),
    ("Some prefix...ನಾನು ಆಶಾ ಮತ್ತು ನಾನು ಆಶಾ ಸಹೇಲಿ ಬಾಟ್‌ಗೆ ಸೇರಲು ಬಯಸುತ್ತೇನೆ...suffix", "kn", True),
    ("ಕನ್ನಡ random", "kn", False),

    # marathi tests
    ("मी आशा आहे आणि मला आशा सहेली बॉटमध्ये सामील व्हायचे आहे", "mr", True),
    ("मी आशा आहे", "mr", False),  # partial phrase
    ("मराठी random", "mr", False),

    # telugu tests
    ("నేను ఆశాను మరియు ఆశా సహేలి బాట్‌లో చేరాలనుకుంటున్నాను", "te", True),
    ("text... నేను ఆశాను మరియు ఆశా సహేలి బాట్‌లో చేరాలనుకుంటున్నాను ...text", "te", True),
    ("తెలుగు random", "te", False),

    # other cases
    ("", "en", False),
    ("    ", "en", False),
    ("onboard-asha", "fr", False),  # unsupported lang always returns False
    ("में एक आशा हूँ और मुझे आशा सहेली बोट से जुड़ना है", "fr", False),  # unsupported lang with valid text
    ("नमस्ते\u2028", "hi", False),  # line separator U+2028 should not affect logic
])
def test_is_onboard(text, lang, expected):
    assert is_onboard(text, lang) == expected
