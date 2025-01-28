
import yaml
import os
import smtplib

local_path = os.environ["APP_PATH"]
with open(os.path.join(local_path, "config.yaml")) as file:
    config = yaml.load(file, Loader=yaml.FullLoader)
import sys
sys.path.append(local_path + "/src")

from utils import get_llm_response
from database import UserDB, UserConvDB, BotConvDB, ExpertConvDB, AppLogger
from messenger.whatsapp import WhatsappMessenger
from tabulate import tabulate
import datetime
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

def extract_onboarding_count(onboarding_responses_df, user_ids):
    num_yes = len(user_ids.intersection(set(onboarding_responses_df[onboarding_responses_df["message_source_lang"] == "हाँ"]["user_id"])))
    num_no = len(user_ids.intersection(set(onboarding_responses_df[onboarding_responses_df["message_source_lang"] == "नहीं"]["user_id"])))
    return num_yes, num_no

def get_message_wise_stats(messages_df, user_ids):
    message_count = messages_df[messages_df["user_id"].isin(user_ids)].groupby("user_id").size().to_dict()
    first_message = messages_df[messages_df["user_id"].isin(user_ids)].groupby("user_id")["message_timestamp"].min().to_dict()
    return message_count, first_message

def get_leaderboard():
    NUM_DAYS = 7
    NUM_HOURS = NUM_DAYS*24

    user_db = UserDB(config)
    user_conv_db = UserConvDB(config)
    bot_conv_db = BotConvDB(config)

    asha_list = user_db.get_all_users(user_type="Asha")
    asha_list = [asha for asha in asha_list if asha.get("test_user", False) == False]
    asha_df = pd.DataFrame(asha_list)
    if "Location" in asha_df.columns:
        location_df = pd.json_normalize(asha_df["Location"])  # Flatten Location into columns
        asha_df = pd.concat([asha_df.drop(columns=["Location"]), location_df], axis=1)  # Combine

    asha_df = asha_df[asha_df[["District", "Block", "Sector", "SubCenter"]].notna().all(axis=1)]
    asha_user_ids = asha_df['user_id'].unique().tolist()

    dt_now = datetime.datetime.now()
    dt_from = dt_now - datetime.timedelta(hours=NUM_HOURS)

    messages = user_conv_db.get_all_queries()
    messages_df = pd.DataFrame(messages)
    messages_delta_df = messages_df[messages_df["message_timestamp"] > dt_from]

    result = messages_delta_df[messages_delta_df["user_id"].isin(asha_user_ids)].groupby('user_id').size().reset_index(name='message_count')

    # Merge df1 and df2 on user_id
    merged_df = pd.merge(asha_df, result, on='user_id')

    # Group by District, Sector, and Block to calculate total message_count
    grouped = merged_df.groupby(['District', 'Sector', 'Block'])['message_count'].sum().reset_index()

    # Sort by District and message_count in descending order
    grouped = grouped.sort_values(by=['District', 'message_count'], ascending=[True, False])

    # Select top 3 (Sector, Block) per District, including districts with less than 3 pairs
    top_3_per_district = grouped.groupby('District', group_keys=True).apply(lambda x: x.head(3)).reset_index(drop=True)

    # Print results for all districts
    # for district, group in top_3_per_district.groupby('District'):
    #     print(f"District: {district}")
    #     print(group[['Sector', 'Block', 'message_count']])
    #     print("-" * 40)

    district_dict = {
        district: list(zip(group['Sector'], group['Block']))
        for district, group in top_3_per_district.groupby('District')
    }

    return district_dict

def create_leaderboard_hi_messages():
    district_dict = get_leaderboard()
    messages = {}
    system_prompt = "You are a hindi translator. Translate all to hindi only give translated output"
    for district, sectors_blocks in district_dict.items():
        # Format the leaderboard for the current district
        header = f"इस हफ्ते, {district} ke इन 3 क्षेत्रों की आशा बहनों ने सबसे अधिक सवाल पूछे:\n"
        formatted_entries = [
            f"{i+1}. {sector}, {block}" for i, (sector, block) in enumerate(sectors_blocks)
        ]
        message = header + "\n".join(formatted_entries)
        prompt = [{"role": "system", "content": system_prompt}]
        prompt.append({"role": "user", "content": message})
        hi_message = get_llm_response(prompt)
        messages[district] = hi_message
    return messages
    # district_leaderboard = leaderboard.get(district, None)
    # if district_leaderboard is None:
    #     return None
    
    # # Format the leaderboard for the specified district
    # formatted_entries = [f"{i+1}. {sector}, {block}" for i, (sector, block) in enumerate(district_leaderboard)]
    # body = "\n".join(formatted_entries)
    # return header + body

if __name__ == "__main__":
    messages = create_leaderboard_hi_messages()
    print(messages)
