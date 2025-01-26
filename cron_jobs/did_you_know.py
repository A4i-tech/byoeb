import yaml
import os
from cachetools import TTLCache

local_path = os.environ["APP_PATH"]
with open(os.path.join(local_path, "config.yaml")) as file:
    config = yaml.load(file, Loader=yaml.FullLoader)
import sys

sys.path.append(local_path + "/src")
sys.path.append(local_path + "/cron_jobs")

from leaderboard import create_leaderboard_hi_messages
from knowledge_base import KnowledgeBase
from database import UserDB, UserConvDB, BotConvDB, AppLogger
from conversation_database import LoggingDatabase
from messenger.whatsapp import WhatsappMessenger
from azure_language_tools import translator
import os
import random
import datetime
import pandas as pd

# 3 days in seconds: 3 days * 24 hours/day * 60 minutes/hour * 60 seconds/minute
three_days_ttl = 3 * 24 * 60 * 60  # 259200 seconds
cache = TTLCache(ttl=three_days_ttl, maxsize=1000)

DID_YOU_KNOW = "did_you_know"
GUID = 'GUID'
FACT = 'Did you know - Hindi'
FACT_GUID_KEY = 'dyk_guids'
EVENT_NAME = "did_you_know"
template_name = "did_you_know"

user_db = UserDB(config)
user_conv_db = UserConvDB(config)
bot_conv_db = BotConvDB(config)
app_logger = AppLogger()
messenger = WhatsappMessenger(config, app_logger)
azure_translate = translator()

print("Date: ", datetime.datetime.now())

leaderboard_hi = create_leaderboard_hi_messages()
    
# users = [user_db.get_from_whatsapp_id('918837701828')]
# print("Total users: ", len(users))
facts_df = pd.read_csv(local_path + "/data/asha_bot/did_you_know/dyk_v1.csv", encoding='utf-8')
facts_df.set_index(GUID, inplace=True)

def get_user_district_leaderboard_message(district):
    if district is None or pd.isna(district):
        return None
    return leaderboard_hi.get(district, None)

def get_next_fact(user_row):
    fact_guids = facts_df.index.tolist()
    user_fact_guids = user_row.get(FACT_GUID_KEY, [])
    if not isinstance(user_fact_guids, list):
        user_fact_guids = []
    remaining_guids = list(set(fact_guids) - set(user_fact_guids))
    if remaining_guids == []:
        remaining_guids = fact_guids
        user_fact_guids = []
    next_fact_guid = random.choice(remaining_guids)
    user_fact_guids.append(next_fact_guid)
    return facts_df.loc[next_fact_guid][FACT], user_fact_guids

def send_fact(users_df):
    for _, user_row in users_df.iterrows():
        if user_row.get("opt out", False) and not pd.isna(user_row["opt out"]):
            print("User opted out: ", user_row["whatsapp_id"], user_row["opt out"])
            continue
        try:
            fact, user_fact_guids = get_next_fact(user_row)
            user_leaderboard = get_user_district_leaderboard_message(user_row["District"])
            param_list = [fact]
            param_list.extend(user_leaderboard.split("\n"))  # Extends the list in place
            print(param_list)
            sent_msg_id = messenger.send_template(
                user_row["whatsapp_id"],
                template_name,
                user_row["user_language"],
                [param_list],
                None
            )
            user_db.update_user(user_row["user_id"], {FACT_GUID_KEY: user_fact_guids})

            bot_conv_db.insert_row(
                receiver_id=user_row["user_id"],
                message_type=DID_YOU_KNOW,
                message_id=sent_msg_id,
                audio_message_id=None,
                message_source_lang="en",
                message_language=user_row["user_language"],
                message_english=fact,
                reply_id=None,
                citations=None,
                message_timestamp=datetime.datetime.now(),
                transaction_message_id=None,
                did_you_know_id=user_fact_guids[-1],
            )
        except Exception as e:
            print("Error in sending fact: ", str(e))
            app_logger.add_log(event_name=EVENT_NAME, details={"message": f"Error in sending fact: {str(e)} for user: {user_row['user_id']}"})

def get_suggested_questions_based_on_fact(
    id,
    row_lt,
    knowledge_base: KnowledgeBase,
    onboarding_questions,
):
    if id in cache:
        return cache[id]
    fact = facts_df.loc[id][FACT]
    source_lang = row_lt["user_language"]
    fact_en = azure_translate.translate_text(fact, "hi", "en", app_logger)
    next_questions = knowledge_base.follow_up_questions(
        fact_en, "ignore chatbot answer", row_lt['user_type'], app_logger
    )
    questions_source = []
    for question in next_questions:
        question_source = azure_translate.translate_text(
            question, "en", source_lang, app_logger
        )
        questions_source.append(question_source)
    title, list_title = (
        onboarding_questions[source_lang]["title"],
        onboarding_questions[source_lang]["list_title"],
    )
    cache[id] = (title, list_title, questions_source)
    return title, list_title, questions_source

def send_fact_to_Asha():
    # users = user_db.get_all_users(user_type="Asha")
    users = [user_db.get_from_whatsapp_id('918837701828')]
    user_df = pd.DataFrame(users)
    if "Location" in user_df.columns:
        location_df = pd.json_normalize(user_df["Location"])  # Flatten Location into columns
        user_df = pd.concat([user_df.drop(columns=["Location"]), location_df], axis=1)  # Combine

    app_logger.add_log(event_name=EVENT_NAME, details={"message": f"Total users: {len(users)}"})
    try:
        send_fact(user_df)
        app_logger.add_log(event_name=EVENT_NAME, details={"message": "Successfully sent facts to Asha"})
    except Exception as e:
        print("Error in sending facts to Asha: ", str(e))
        app_logger.add_log(event_name=EVENT_NAME, details={"message": f"Error in sending facts to Asha: {str(e)}"})
    
if __name__ == "__main__":
    send_fact_to_Asha()
