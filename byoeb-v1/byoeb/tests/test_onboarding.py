import pytest
import httpx
import uuid
import time
import requests
import json
import re
# Endpoint
BASE_URL = "http://127.0.0.1:5000/receive"


USER_WA_ID = "919038069298"  # Phone number to onboard
BOT_WA_ID = "183958451475612"

# Payload templates for the 4-step onboarding flow
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
                                    "name": "Lavisha"
                                },
                                "wa_id": "919929959948"
                            }
                        ],
                        "messages": [
                            {
                                "from": "919038069298",
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
                                    "name": "Lavisha"
                                },
                                "wa_id": "919929959948"
              }
            ],
            "messages": [
              {
                "from": "919038069298",
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
                "profile": { "name": "Lavisha" },
                "wa_id": "919038069298"
              }
            ],
            "messages": [
              {
                "from": "919038069298",
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
                "profile": { "name": "Lavisha" },
                "wa_id": "919038069298"
              }
            ],
            "messages": [
              {
                "from": "919038069298",
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

# def extract_reply_pairs(log_text: str):
#     reply_id_list=log_text.split("ReplyContext(")
#     x=[]
#     for i in reply_id_list:
#         if "reply_id='" in i and "text='" in i:
#             text=i.split("reply_id='",1)[1].split("'",1)[0]
#             d=i.split("text='",1)[1].split("'",1)[0]
#             x.append((text,d))
#     return x

# def extract_reply_pairs(log_text: str, msg_id: str):
#     m_text="MessageContext(message_id='"+msg_id
#     message_id_list=log_text.replace("\x00","").split(m_text)
#     #reply_id_list=log_text.split("ReplyContext(")
#     x=[]
#     print("message_id_list:",message_id_list)
#     for i in message_id_list:
#         if "reply_id='" in i:
#             text=i.split("reply_id='",1)[1].split("'",1)[0]
#             t=i.split("text='",1)[1].split("'",1)[0]
#             #d=i.split("message_id='",1)[1].split("'",1)[0]
#             #x.append()

#             return text
def extract_reply_pairs(log_text: str):
    #m_text="MessageContext(message_id='"+msg_id

    message_id_list1=log_text.split("[WhatsAppResponse")
    message_id_list2=log_text.split("ByoebMessageContext")
    #reply_id_list=log_text.split("ReplyContext(")
    text=""
    #print("message_id_list:",message_id_list)
    for i in message_id_list1:
        if "Message(id=" in i:
            text=i.split("Message(id='",1)[1].split("'",1)[0]
            #text=i.split("reply_id='",1)[1].split("'",1)[0]
            #t=i.split("text='",1)[1].split("'",1)[0]
            #d=i.split("message_id='",1)[1].split("'",1)[0]
            #x.append()
            return text
    if text is None or text=="":
        for i in message_id_list2:
            if "message_id=" in i:  
                text=i.split("message_id='",1)[1].split("'",1)[0]

            return text
@pytest.mark.asyncio
async def test_whatsapp_onboarding_flow():
    context_id = None
    print("Starting onboarding flow test...")

    async with httpx.AsyncClient() as client:
        for step, payload_template in enumerate(ONBOARDING_PAYLOADS):
            payload = payload_template.copy()
            msg = payload["entry"][0]["changes"][0]["value"]["messages"][0]
            msg["id"] = generate_message_id()
            msg["timestamp"] = get_current_timestamp()
            #if "context" not in msg or msg.get("type") == "interactive":
            #    msg["context"] = {}
            if step > 0:
                msg["context"]["id"] = context_id
                print("context_id:",context_id)
            print("-------------------------STEP",step+1,"-------------------------")
            #print(payload)
            
            response = await client.post(BASE_URL, json=payload)
            
            print(f"Step {step+1} response: {response.json()}")
            
            # Assertions
            # Print response for debugging
            with open("../../../../output_byoeb.logs","r")as f:
                logs=f.read()
            with open("../../../../output_byoeb.logs","w")as f:
                f.write(f"")
            context_id=extract_reply_pairs(logs)
            print("msg id:",msg["id"])

            #print("\n*****************************\nreply_id_text:",reply_id_text)
            print("\n*****************************\nLogs:",logs)
            #context_id=extract_reply_pairs(logs,msg["id"])
            #print("context_id:",context_id)
            # for i,j in reply_id_text:
            #     if step==0 and j.lower() in ["hi","hello","hey"]:
            #         context_id=i
            #     if step==1 and j.lower() in ["english"]:
            #         context_id=i
            #     if step==2 and j.lower() in ["others"]:
            #         context_id=i
            #     if step==3 and j.lower() in ["yes"]:
            #         context_id=i
            # Update bot message ID for next step
            #previous_bot_wamid =  context_id
            
            assert response.status_code == 200, f"Step {step+1} failed"
            #time.sleep(2)  # Simulate delay between messages




         

