import pymongo
import certifi
import os
import yaml
import pandas as pd
from tqdm import tqdm

config_path = os.path.join(os.environ['APP_PATH'], "config.yaml")
with open(config_path, 'r') as data:
    config = yaml.safe_load(data)

import sys
sys.path.append(os.path.join(os.environ['APP_PATH'], 'src'))


from database.user_db import UserDB
from database.user_relation_db import UserRelationDB

from onboard import onboard_wa_helper, onboard_template
from messenger import WhatsappMessenger
from conversation_database import LoggingDatabase

user_db = UserDB(config)

asha_list = user_db.get_all_users(user_type="Asha")
asha_list = [asha for asha in asha_list if asha.get("test_user", False) == False]
asha_df = pd.DataFrame(asha_list)
if "Location" in asha_df.columns:
    location_df = pd.json_normalize(asha_df["Location"])  # Flatten Location into columns
    asha_df = pd.concat([asha_df.drop(columns=["Location"]), location_df], axis=1)  # Combine

# Create a separate DataFrame where any Location field is missing (NaN or None)
missing_location_df = asha_df[asha_df[["District", "Block", "Sector", "SubCenter"]].isna().any(axis=1)]
complete_location_df = asha_df[asha_df[["District", "Block", "Sector", "SubCenter"]].notna().all(axis=1)]


# Display the DataFrame with missing location info
print("DataFrame with location info:")
print(complete_location_df.shape)
print("DataFrame with missing location info:")
print(missing_location_df.shape)

missing_phone_numbers = missing_location_df['whatsapp_id']
missing_phone_numbers.to_csv("./missing_phone_numbers.csv", index=False)

# csv_file = "/home/rash598/Khushi/byoeb/processing/Asha_location.csv"  # Replace with your Excel file path
# data = pd.read_csv(csv_file)

# for _, row in tqdm(data.iterrows(), total=len(data), desc="Updating MongoDB"):
#     phone_number = str(row["Asha Mobile No."])
#     phone_number_id = "91"+phone_number
#     location_info = {
#         "District": row["District Name"],
#         "Block": row["Block Name"],
#         "Sector": row["PHC/Sector Name"],
#         "SubCenter": row["Sub Center Name"],
#     }
#     user_db.update_location(phone_number_id, location_info)

# user_row = user_db.get_from_whatsapp_id("917891332401")
# print(user_row)

# phone_number = "918837701828"
# location_info = {
#     "District": "Udaipur",
#     "Block": "Kherwara",
#     "Sector": "Bawal Wara",
#     "SubCenter": "Barothi Bheelan",
# }
# user_db.update_location(phone_number, location_info)
# user_row = user_db.get_from_whatsapp_id("918837701828")
# print(user_row)