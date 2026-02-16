from enum import Enum

class FeatureFlag(Enum):
    # cache user queries in runtime so ASHAbot loads known questions from its local memory
    CACHE_MESSAGES = "cache_messages"

    # disambiguate user queries by asking follow-up questions to clarify intent
    QUERY_DISAMBIGUATION = "query_disambiguation"

    # use gpt-4o-transcribe instead of whisper for speech-to-text
    STT_LATENCY_MITIGATION = "stt_latency_mitigation"