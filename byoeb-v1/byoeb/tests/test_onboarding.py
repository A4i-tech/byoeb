import pytest
import httpx
import uuid
import time
import requests
import json
import re
from urllib.parse import quote
import os
# Endpoint
BASE_URL = os.getenv("RECIEVE_URL")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
USER_NAME = os.getenv("USER_NAME")
ONBOARDING_PAYLOADS = [
 {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "211506508713627",
            "changes": [
                {
                    "value": {
                        "messaging_product": "whatsapp",
                        "metadata": {
                            "display_phone_number": "919001386867",
                            "phone_number_id": "183958451475612"
                        },
                        "contacts": [
                            {
                                "profile": {
                                    "name": USER_NAME
                                },
                                "wa_id": PHONE_NUMBER_ID
                            }
                        ],
                        "messages": [
                            {
                                "from": PHONE_NUMBER_ID,
                                "id": "",
                                "timestamp": "1758573528",
                                "text": {
                                    "body": "hi"
                                },
                                "type": "text"
                            }
                        ]
                    },
                    "field": "messages"
                }
            ]
        }
    ]
}
,
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "211506508713627",
      "changes": [
        {
           "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "919001386867",
              "phone_number_id": "183958451475612"
            },
            "contacts": [
              {
                "profile": {
                                    "name": USER_NAME
                                },
                                "wa_id": PHONE_NUMBER_ID
              }
            ],
            "messages": [
              {
                "from": PHONE_NUMBER_ID,
                "id": "",
                "timestamp": "1758576570",
                "context": {
                  "from": "183958451475612",
                  "id": ""
                },
                "type": "interactive",
                "interactive": {
                  "type": "list_reply",
                  "list_reply": {
                    "id": "English",
                    "title": "English",
                    "description": ""
                  }
                }
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}
,
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "211506508713627",
        "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "919001386867",
              "phone_number_id": "183958451475612"
            },
            "contacts": [
              {
                "profile": { "name": USER_NAME },
                "wa_id": PHONE_NUMBER_ID
              }
            ],
            "messages": [
              {
                "from": PHONE_NUMBER_ID,
                "id": "",
                "timestamp": "1758576682",
                "context": {
                  "from": "183958451475612",
                  "id": ""
                },
                "type": "interactive",
                "interactive": {
                  "type": "button_reply",
                  "button_reply": {
                    "id": "others",
                    "title": "Others"
                  }
                }
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}
,
{
  "object": "whatsapp_business_account",
  "entry": [
    {
      "id": "211506508713627",
      "changes": [
        {
          "value": {
            "messaging_product": "whatsapp",
            "metadata": {
              "display_phone_number": "919001386867",
              "phone_number_id": "183958451475612"
            },
            "contacts": [
              {
                "profile": { "name": USER_NAME },
                "wa_id": PHONE_NUMBER_ID
              }
            ],
            "messages": [
              {
                "from": PHONE_NUMBER_ID,
                "id": "",
                "timestamp": "1758577083",
                "context": {
                  "from": "183958451475612",
                  "id": ""
                },
                "type": "interactive",
                "interactive": {
                  "type": "button_reply",
                  "button_reply": {
                    "id": "yes",
                    "title": "Yes"
                  }
                }
              }
            ]
          },
          "field": "messages"
        }
      ]
    }
  ]
}
]

def get_current_timestamp():
    return str(int(time.time()))

def generate_message_id():
    return f"wamid.{uuid.uuid4().hex}"

def test_whatsapp_onboarding_flow():
    context_id = None
    print("Starting onboarding flow test...")
    x=0
    m_id=[]
    delete_url = BASE_URL.replace("receive","delete_user")
    headers = {
    "accept": "application/json",
    "Content-Type": "application/json"
    }
    data = [str(PHONE_NUMBER_ID)]  # same as your -d payload

    response = requests.delete(delete_url, headers=headers, data=json.dumps(data))

    c_id=[]
    for step, payload_template in enumerate(ONBOARDING_PAYLOADS):
            payload = payload_template.copy()
            msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            msg["id"] = generate_message_id()
            msg["timestamp"] = get_current_timestamp()
            m_id.append(msg["id"])
            if step > 0:
                msg["context"]["id"] = context_id
                c_id.append(context_id)
                print("context_id:",context_id)
            print("-------------------------STEP",step+1,"-------------------------")
            response = requests.post(BASE_URL, json=payload)
            url = BASE_URL.replace("receive","get_bot_messages?timestamp=%22%22")
            print("paylod: ",payload)
            bot_message = requests.get(url)
            bot_message=bot_message.json()

            valid_timestamps = [ int(str(m["outgoing_timestamp"])) for m in bot_message if m.get("outgoing_timestamp") not in (None, "None", "")]
            max_timestamp=max(valid_timestamps) if valid_timestamps else 0
            print("max_timestamp:",max_timestamp, "msg timestamp:", msg['timestamp'])
          
                  
            print("Waiting for bot response...")
            if step!=len(ONBOARDING_PAYLOADS)-1:
              while max_timestamp<int(msg['timestamp']) and int(time.time())-int(msg['timestamp'])<60:
                  time.sleep(2)
                  print("Checking for new bot messages...")
                  bot_message = requests.get(url)
                  bot_message=bot_message.json()
                  valid_timestamps1 = [ int(str(m["outgoing_timestamp"])) for m in bot_message if m.get("outgoing_timestamp") not in (None, "None", "")]
                  max_timestamp=max(valid_timestamps1) if valid_timestamps1 else 0
                  print("max_timestamp in while:",max_timestamp)
              print("Bot response received.")
              for i in bot_message:
                  if "language" in i["message_context"]["message_source_text"] and step==0 and i["outgoing_timestamp"]!=None and  int(str(i["outgoing_timestamp"]))>int(msg['timestamp']):   
                      context_id=i["message_context"]["message_id"]
                      print(i)
                      break 
                  elif "Who are you" in i["message_context"]["message_source_text"] and step==1 and i["outgoing_timestamp"]!=None and int(str(i["outgoing_timestamp"]))>int(msg['timestamp']):
                      context_id=i["message_context"]["message_id"]
                      print(i)
                      break
                  elif "Researchers" in i["message_context"]["message_source_text"] and step==2 and i["outgoing_timestamp"]!=None and int(str(i["outgoing_timestamp"]))>int(msg['timestamp']):
                      context_id=i["message_context"]["message_id"]
                      print(i)
                      break
                  elif step==3:
                      break
              print(f"Step {step+1} response: {response.json()}")
              assert response.status_code == 200, f"Step {step+1} failed"



