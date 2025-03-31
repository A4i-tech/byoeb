import hashlib
import os
import byoeb.services.user.constants as user_const
import byoeb.services.chat.constants as chat_const
from typing import List
from byoeb.factory import ChannelClientFactory
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    ReplyContext,
    MessageTypes
)
from byoeb.services.channel.whatsapp import WhatsAppService
from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService
from byoeb_core.models.byoeb.user import User
from datetime import datetime, timezone
from byoeb_core.convertor.audio_convertor import wav_to_ogg_opus_bytes
from byoeb_core.models.whatsapp.requests import media_request as wa_media

def get_language_code(language):
    language_dict = {
        "हिंदी": "hi",
        "English": "en",
    }
    if language in language_dict:
        return language_dict[language]

def get_consent(choice):
    yes = ["हाँ", "Yes"]
    no = ["नहीं", "No"]
    if choice in yes:
        return True
    elif choice in no:
        return False

def get_user_type(choice):
    asha = ["Asha", "आशा"]
    anm = ["ANM", "नर्सदीदी / ए.एन.एम"]
    if choice in asha:
        return "asha"
    elif choice in anm:
        return "anm"

def create_onboarding_message(
    message: ByoebMessageContext
) -> ByoebMessageContext:
    text_message = "🙏🏽नमस्ते! आप कौन हैं?"
    text_options = ["आशा", "नर्सदीदी / ए.एन.एम"]
    message_type = MessageTypes.INTERACTIVE_BUTTON.value
    button_additional_info = {
        chat_const.BUTTON_TITLES: text_options,
    }
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.USER_TYPE,
        user=message.user,
        message_context=MessageContext(
            message_type=message_type,
            message_source_text=text_message,
            additional_info=button_additional_info,
        ),
        reply_context=ReplyContext(
            reply_id=message.message_context.message_id,
            message_category=message.message_category,
        ),
    )

def create_language_selection_message(
    message: ByoebMessageContext
) -> ByoebMessageContext:
    text_message = "🙏🏽नमस्ते! आप किस भाषा में बात करना चाहेंगे?"
    lang_list = ["हिंदी", "English"]
    interactive_list_additional_info = {
        chat_const.DESCRIPTION: "भाषा चुनें:",
        chat_const.ROW_TEXTS: lang_list,
    }
    message_type = MessageTypes.INTERACTIVE_LIST.value
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.LANGUAGE_SELECTION,
        user=message.user,
        message_context=MessageContext(
            message_type=message_type,
            message_source_text=text_message,
            additional_info=interactive_list_additional_info,
        ),
        reply_context=ReplyContext(
            reply_id=message.message_context.message_id,
            message_category=message.message_category,
        ),
    )

def create_consent_message(
    message: ByoebMessageContext,
    user_lang: str = None
) -> ByoebMessageContext:
    consent_dict = {
        "hi": {
            "text": "🙏🏽नमस्ते! क्या आप सहमत हैं?",
            "options": ["हाँ", "नहीं"]
        },
        "en": {
            "text": "🙏🏽Hello! Do you agree?",
            "options": ["Yes", "No"]
        }
    }
    text_message = consent_dict[user_lang]["text"]
    text_options = consent_dict[user_lang]["options"]
    message_type = MessageTypes.INTERACTIVE_BUTTON.value
    button_additional_info = {
        chat_const.BUTTON_TITLES: text_options,
    }
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.CONSENT,
        user=message.user,
        message_context=MessageContext(
            message_type=message_type,
            message_source_text=text_message,
            additional_info=button_additional_info,
        ),
        reply_context=ReplyContext(
            reply_id=message.message_context.message_id,
            message_category=message.message_category,
        ),
    )

def create_audio(
    user_lang: str,
    user_type: str
):
    # Get the directory of the current script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    audio_path = os.path.join(current_dir, 'onboarding', user_lang, f'welcome_messages_{user_type}.wav')
    audio_path = os.path.normpath(audio_path)
    audio_bytes = None
    with open(audio_path, 'rb') as file:
        audio_bytes = file.read()
    ogg_bytes = wav_to_ogg_opus_bytes(audio_bytes)
    media_type=wa_media.FileMediaType.AUDIO_OGG.value
    return ogg_bytes, media_type
    
        
def create_initial_message(
    message: ByoebMessageContext
) -> ByoebMessageContext:
    user_type = message.user.user_type
    user_lang = message.user.user_language
    thank_you_dict = {
        "asha": {
            "hi": "🙏🏽 \"ख़ुशी बेबी\" की ओर से नमस्ते। मैं आशा सहेली हूँ। आप मुझसे गर्भावस्था, शिशु देखभाल और आशा के रूप में अपने काम के बारे में कोई भी प्रश्न लिखकर या वॉइस संदेश भेजकर पूछ सकते हैं।",
            "en": "🙏🏽 Namaste from Khushi Baby. You can ask ASHA Saheli any question about pregnancy, childcare, and your work as an ASHA, by typing or sending me a voice message."
        },
        "anm": {
            "hi": "🙏🏽 \"ख़ुशी बेबी\" की ओर से नमस्ते। हम आशा कार्यकर्ताओं को उनके सवालों में मदद करने के लिए एक नए कार्यक्रम पर काम कर रहे हैं। कृपया उनके सवालो का उत्तर देने में हमारी सहायता करें| इस कार्यक्रम के बारे में अधिक जानकारी के लिए कृपया हमारे हेल्पडेस्क नंबर +91 77270 79678 पर कॉल करें। आपके समर्थन के लिए धन्यवाद।",
            "en": "🙏🏽 Namaste from Khushi Baby. We are working on a new program to help ASHA workers with their questions. For more information about this program, please call our helpdesk number +91 77270 79678. Thank you for your support."
        }
    }
    related_questions = {
        "description": {
            "en": "Suggested Questions",
            "hi": "सुझाए गए प्रश्न"
        },
        "questions": {
            "en": [
                "How much does a 1-year-old typically weigh?",
                "What long-term effects does tobacco cause?",
                "What is Antara injection?"
            ],
            "hi": [
                "1 साल का बच्चा आमतौर पर कितना वज़न रखता है?",
                "तंबाकू के दीर्घकालिक प्रभाव क्या होते हैं?",
                "अंतराल इंजेक्शन क्या है?"
            ]
        }
    }
    audio_bytes, audio_type = create_audio(user_lang, user_type)
    text_message = thank_you_dict[user_type][user_lang]
    if user_type == "anm":
        message_type = MessageTypes.REGULAR_TEXT.value
        return ByoebMessageContext(
            channel_type=message.channel_type,
            message_category=user_const.THANK_YOU,
            user=message.user,
            message_context=MessageContext(
                message_type=message_type,
                message_source_text=text_message,
                additional_info = {
                    chat_const.DATA: audio_bytes,
                    chat_const.MIME_TYPE: audio_type,
                }
            ),
            reply_context=ReplyContext(
                reply_id=message.message_context.message_id,
                message_category=message.message_category,
            ),
        )
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.THANK_YOU,
        user=message.user,
        message_context=MessageContext(
            message_type=MessageTypes.INTERACTIVE_LIST.value,
            message_source_text=text_message,
            additional_info = {
                chat_const.DESCRIPTION: related_questions["description"][user_lang],
                chat_const.ROW_TEXTS: related_questions["questions"][user_lang],
                chat_const.DATA: audio_bytes,
                chat_const.MIME_TYPE: audio_type,
            }
        ),
        reply_context=ReplyContext(
            reply_id=message.message_context.message_id,
            message_category=message.message_category,
        ),
    )

def create_user(
    phone_number_id: str,
    language: str = None,
    user_type: str = None,
    consent: bool = None,
) -> User:
    return User(
        user_id=hashlib.md5(phone_number_id.encode()).hexdigest(),
        phone_number_id=phone_number_id,
        user_language=language,
        user_type=user_type,
        additional_info={
            user_const.CONSENT: consent,
        },
        test_user=False,
        experts={},
        audience=[],
        created_timestamp=int(datetime.now(timezone.utc).timestamp()),
        activity_timestamp=int(datetime.now(timezone.utc).timestamp()),
    )
    
async def handle_unknown_user(
    messages: List[ByoebMessageContext],
    message_db_service: MessageMongoDBService,
    user_db_service: UserMongoDBService,
    channel_factory: ChannelClientFactory,
):
    print("onboarding message")
    channel_service = WhatsAppService(channel_client_factory=channel_factory)
    if not isinstance(channel_service, WhatsAppService):
        raise ValueError("Invalid channel service type")
    for message in messages:
        if message.reply_context is None or message.reply_context.reply_id is None:
            # print(f"onboarding message: {message}")
            byoeb_message = create_onboarding_message(message)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            new_user = create_user(phone_number_id=message.user.phone_number_id)
            print(new_user)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            user_db_queries = {
                chat_const.CREATE: [user_db_service.user_create_query(new_user)]
            }
            try:
                await message_db_service.execute_queries(message_db_queries)
                await user_db_service.execute_queries(user_db_queries)
            except Exception as e:
                print(f"Error in onboarding message: {e}")
        elif message.reply_context.message_category == chat_const.USER_TYPE:
            text = message.message_context.message_source_text
            user_type = get_user_type(text)
            update_user = create_user(
                phone_number_id=message.user.phone_number_id,
                user_type=user_type,
            )
            user_db_queries = {
                chat_const.UPDATE: [user_db_service.user_update_query(update_user)]
            }
            byoeb_message = create_language_selection_message(message)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            await message_db_service.execute_queries(message_db_queries)
            await user_db_service.execute_queries(user_db_queries)
        elif message.reply_context.message_category == chat_const.LANGUAGE_SELECTION:
            text = message.message_context.message_source_text
            code = get_language_code(text)
            print("code", code)
            update_user = create_user(
                phone_number_id=message.user.phone_number_id,
                user_type=message.user.user_type,
                language=code
            )
            user_db_queries = {
                chat_const.UPDATE: [user_db_service.user_update_query(update_user)]
            }
            byoeb_message = create_consent_message(message, code)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            await message_db_service.execute_queries(message_db_queries)
            await user_db_service.execute_queries(user_db_queries)
        elif message.reply_context.message_category == chat_const.CONSENT:
            text = message.message_context.message_source_text
            consent = get_consent(text)
            update_user = create_user(
                phone_number_id=message.user.phone_number_id,
                user_type=message.user.user_type,
                language=message.user.user_language,
                consent=consent
            )
            user_db_queries = {
                chat_const.UPDATE: [user_db_service.user_update_query(update_user)]
            }
            byoeb_message = create_initial_message(message)
            byoeb_message_no_reply = byoeb_message.model_copy(deep=True)
            byoeb_message_no_reply.reply_context = None
            # print(f"Initial message: {byoeb_message}")
            requests = channel_service.prepare_requests(byoeb_message_no_reply)
            responses, message_ids = await channel_service.send_requests(requests)
            await user_db_service.execute_queries(user_db_queries)
        else:
            print(f"onboarding message: {message}")
            byoeb_message = create_onboarding_message(message)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            new_user = create_user(phone_number_id=message.user.phone_number_id)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            user_db_queries = {
                chat_const.CREATE: [user_db_service.user_create_query(new_user)]
            }
            try:
                await message_db_service.execute_queries(message_db_queries)
                await user_db_service.execute_queries(user_db_queries)
            except Exception as e:
                print(f"Error in onboarding message: {e}")