import re
import hashlib
from typing import List, Dict, Any
from datetime import datetime, timezone
from byoeb.chat_app.configuration.config import bot_config
from byoeb.chat_app.configuration.dependency_setup import vector_store, user_db_service, llm_translate_and_rewrite_client, llm_client
from byoeb.models.experiment import QueryInput, QueryOutput
from byoeb_core.models.vector_stores.chunk import Chunk
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError

QUERY_EN = "query_en"
QUERY_EN_ADDCONTEXT = "query_en_addcontext"
QUERY_TYPE = "query_type"
QUESTION = "question"
ANSWER = "answer"
TIMESTAMP = "timestamp"

conversations: Dict[str, List[Dict[str, str]]] = {}

def update_conversations(user_id, question, answer, history_length):
    """
    Update the conversation history for a user.
    If the user does not exist, create a new entry.
    """
    if user_id not in conversations:
        conversations[user_id] = []
    
    # Create a new conversation entry
    conversation_entry = {
        QUESTION: question,
        ANSWER: answer,
        TIMESTAMP: int(datetime.now(timezone.utc).timestamp())
    }
    
    # Append the new conversation entry
    conversations[user_id].append(conversation_entry)
    
    # Limit the history length to 1000 entries
    if len(conversations[user_id]) > 1000:
        conversations[user_id] = conversations[user_id][-history_length:]  # Keep only the last 1000 entries
def get_conversation_history(user_id, history_length):
    last_convs = conversations.get(user_id, [])
    conversation_history = []
    curr_time = datetime.now(timezone.utc).timestamp()
    for i, conv in enumerate(last_convs[-history_length:]):
        question = conv.get(QUESTION, None)
        answer = conv.get(ANSWER, None)
        timestamp = int(conv.get(TIMESTAMP, 0))
        if curr_time - timestamp > 2000:
            continue  # Skip conversations older than 30 min
        if question is None or answer is None:
            continue
        conversation_history.append(f"query{i+1}: {question} answer{i+1}: {answer}")
        i+=1
    return conversation_history

async def llm_translation_and_query_rewritting(system_prompt, question, conversation_history):
    def parse_xml_with_regex(xml_string: str):
        # Patterns for extracting the required tags, ignoring their position in XML
        patterns = {
            QUERY_EN: r"<query_en\s*>(.*?)</query_en\s*>",
            QUERY_EN_ADDCONTEXT: r"<query_en_addcontext\s*>(.*?)</query_en_addcontext\s*>",
            QUERY_TYPE: r"<query_type\s*>(.*?)</query_type\s*>",
        }

        extracted_data = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, xml_string, re.DOTALL | re.IGNORECASE)  # Supports multiline and case-insensitive matches
            extracted_data[key] = match.group(1).strip() if match else None  # Strip removes extra spaces and newlines

        return extracted_data[QUERY_EN], extracted_data[QUERY_EN_ADDCONTEXT], extracted_data[QUERY_TYPE]
    conversation_history_str = ", ".join(conversation_history)
    template_user_prompt = bot_config["llm_response"]["translation_and_rewrite_prompts"]["user_prompt"]
    user_prompt = template_user_prompt.replace("<QUERY>", question).replace("<CONVERSATION_HISTORY>", conversation_history_str)
    augmented_prompts = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    llm_response, response_text = await llm_translate_and_rewrite_client.agenerate_response(augmented_prompts)
    tokens = llm_translate_and_rewrite_client.get_response_tokens(llm_response)
    query_en, query_en_addcontext, query_type  = parse_xml_with_regex(response_text)
    if query_en is None or query_en_addcontext is None or query_type is None:
        raise Exception("LLM response is not in expected format")
    return query_en, query_en_addcontext, query_type, tokens

async def aretrieve_top_k_chunks(query_text, k, search_type, select=None):
    print(f"Retrieving top {k} chunks for query: {query_text} with search type: {search_type}")
    retrieved_chunks = await vector_store.aretrieve_top_k_chunks(
        query_text,
        k,
        search_type=search_type,
        select=["id", "text", "metadata", "related_questions"],
        vector_field="text_vector_3072"
    )
    return retrieved_chunks

@retry(
    stop=stop_after_attempt(3),  # Retry up to 3 times
    wait=wait_exponential(multiplier=1, max=10),  # Exponential backoff with a max wait time of 10 seconds
)
async def agenerate_answer(
    system_prompt,
    query,
    query_type,
    retrieved_chunks: List[Chunk],
):
    def parse_response_xml(xml_string: str):
        # Patterns for extracting response_en and response_hi
        patterns = {
            "response_en": r"<response_en\s*>(.*?)</response_en\s*>",
            "response_src": r"<response_src\s*>(.*?)</response_src\s*>",
        }

        extracted_data = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, xml_string, re.DOTALL | re.IGNORECASE)  # Supports multiline and case-insensitive matches
            extracted_data[key] = match.group(1).strip() if match else None  # Strip removes extra spaces and newlines

        return extracted_data["response_en"], extracted_data["response_src"]
    
    update_kb = [chunk.text for chunk in retrieved_chunks if "KB Updated" in chunk.metadata.source]
    raw_kb = [chunk.text for chunk in retrieved_chunks if "KB Updated" not in chunk.metadata.source]
    update_kb_list = ", ".join(update_kb)
    raw_kb_list = ", ".join(raw_kb)

    template_user_prompt = bot_config["llm_response"]["answer_prompts"]["user_prompt"]
    # Replace placeholders with actual values
    
    user_prompt = template_user_prompt.replace("<QUERY_TYPE>", query_type).replace("<QUERY_EN_ADDCONTEXT>", query).replace("<RAW_KB>", raw_kb_list).replace("<NEW_KB>", update_kb_list)
    augmented_prompts = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    llm_response, response_text = await llm_client.agenerate_response(augmented_prompts)
    tokens = llm_client.get_response_tokens(llm_response)
    response_en, response_source = parse_response_xml(response_text)
    if response_en is None or query_type is None:
        raise ValueError("Parsing failed, response or query_type is None.")
    return response_en, response_source, tokens

async def process_message(input: QueryInput) -> QueryOutput:
    translation_and_rewritting_prompt = input.translation_prompt
    answer_prompt = input.answer_prompt
    top_k = input.top_k
    phone_number_id = input.phone_number_id
    history_length = input.history_length
    search_type = input.search_type.lower()
    question = input.question

    user_id = hashlib.md5(phone_number_id.encode()).hexdigest()
    conversation_history = get_conversation_history(user_id, history_length)
    query_en, query_en_addcontext, query_type, tokens = await llm_translation_and_query_rewritting(translation_and_rewritting_prompt, question, conversation_history)
    retrieved_chunks = await aretrieve_top_k_chunks(query_en_addcontext, top_k, search_type)
    response_en, response_source, tokens = await agenerate_answer(answer_prompt, query_en_addcontext, query_type, retrieved_chunks)
    retrieved_data = []
    for i, chunk in enumerate(retrieved_chunks):
        data = {
            "rank": i+1,
            "source": chunk.metadata.source,
            "text": chunk.text
        }
        retrieved_data.append(data)

    update_conversations(user_id, question, response_en, history_length)
    return QueryOutput(
        query_type=query_type,
        query_en=query_en,
        query_en_addcontext=query_en_addcontext,
        top_documents=retrieved_data,
        answer_en=response_en,
        answer_source=response_source
    )

def clear_history(phone_number_id):
    """
    Clear the conversation history for a user.
    """
    print(f"Clearing history for phone number ID: {phone_number_id}")
    user_id = hashlib.md5(phone_number_id.encode()).hexdigest()
    if user_id in conversations:
        del conversations[user_id]