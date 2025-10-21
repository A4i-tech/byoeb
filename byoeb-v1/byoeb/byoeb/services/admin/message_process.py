import re
import hashlib
import httpx
import os
from typing import List, Dict, Any
from datetime import datetime, timezone
from byoeb.chat_app.configuration.config import bot_config
from byoeb.chat_app.configuration.dependency_setup import embedding_fn, llm_translate_and_rewrite_client, llm_client, DefaultAzureCredential
from byoeb.models.experiment import QueryInput, QueryOutput
from byoeb_core.models.vector_stores.chunk import Chunk, Chunk_metadata
from tenacity import retry, stop_after_attempt, wait_exponential, RetryError
from azure.search.documents.models import VectorizedQuery
from byoeb_core.models.vector_stores.azure.azure_search import AzureSearchNode
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore

QUERY_EN = "query_en"
QUERY_EN_ADDCONTEXT = "query_en_addcontext"
QUERY_TYPE = "query_type"
QUESTION = "question"
ANSWER = "answer"
TIMESTAMP = "timestamp"

conversations: Dict[str, List[Dict[str, str]]] = {}

service_name = "khushi-baby-asha-search"
doc_index_name = "khushi-baby-asha-doc-index-3"

# Use API key authentication instead of DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
azure_search_api_key = os.getenv("AZURE_SEARCH_API_KEY")

if azure_search_api_key:
    print("[INFO] Using AzureKeyCredential (API key from environment).")
    vector_store = AzureVectorStore(
        service_name=service_name,
        index_name=doc_index_name,
        embedding_function=embedding_fn,
        credential=AzureKeyCredential(azure_search_api_key)
    )
else:
    print("[INFO] Using DefaultAzureCredential (no API key found).")
    vector_store = AzureVectorStore(
        service_name=service_name,
        index_name=doc_index_name,
        embedding_function=embedding_fn,
        credential=DefaultAzureCredential()
    )

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
    
    # Limit the history length
    if len(conversations[user_id]) > history_length:
        # Remove the oldest conversation if history exceeds the limit
        conversations[user_id] = conversations[user_id][-history_length:]
def get_conversation_history(user_id, history_length):
    last_convs = conversations.get(user_id, [])
    conversation_history = []
    curr_time = datetime.now(timezone.utc).timestamp()
    for i, conv in enumerate(last_convs[:history_length]):
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

    # Fallback parsing if XML format fails
    if query_en is None or query_en_addcontext is None or query_type is None:
        print(f"Warning: LLM response not in expected XML format. Response: {response_text}")
        # Use fallback values
        query_en = question  # Use original question as English translation
        query_en_addcontext = question  # Use original question as context
        query_type = "Clinical"  # Default query type

        print(f"Using fallback values - query_en: {query_en}, query_type: {query_type}")

    return query_en, query_en_addcontext, query_type, tokens

async def get_embedding(text):
    url = "https://ee8e-20-163-117-70.ngrok-free.app/embed"
    payload = {
        "text": text
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result
        except httpx.RequestError as e:
            print(f"An error occurred: {e}")
            return None
        except httpx.HTTPStatusError as e:
            print(f"Bad status code: {e.response.status_code} - {e.response.text}")
            return None
        
async def aretrieve_top_k_chunks(query_text, k, search_type, embedding_type = "text-embedding-3-large", select=None):
    print(f"Retrieving top {k} chunks for query: {query_text} with search type: {search_type} and embedding type: {embedding_type}")

    # Map similarity to valid search types
    if search_type == "similarity":
        search_type = "hybrid"  # Use hybrid search for similarity

    if embedding_type == "text-embedding-3-large":
        retrieved_chunks = await vector_store.aretrieve_top_k_chunks(
            query_text,
            k,
            search_type=search_type,
            select=["id", "text", "metadata", "related_questions"],
            vector_field="text_vector_3072"
        )
        return retrieved_chunks
    
    # This is not running from azure but a vm wiht A100 GPU whose endpoint is exposed via ngrok
    if embedding_type == "qwen3-embedding-8b":
        chunk_list: List[Chunk] = []
        qwen_embedding = await get_embedding(query_text)
        vector_query = VectorizedQuery(
            vector=qwen_embedding['embedding'],
            k_nearest_neighbors=10,
            fields="qwen_3_4096"
        )
        if search_type == "hybrid":
            results = vector_store.search_client.search(
                search_text=query_text,
                vector_queries=[vector_query],
                select=["id", "text", "metadata", "related_questions"],
                top=3
            )
        elif search_type == "dense":
            results = vector_store.search_client.search(
                vector_queries=[vector_query],
                select=["id", "text", "metadata", "related_questions"],
                top=3
            )
        results = vector_store.search_client.search(
            vector_queries=[vector_query],
            select=["id", "text", "metadata", "related_questions"],
            top=3
        )
        for result in results:
            azure_search_result = AzureSearchNode(**result)
            if azure_search_result.metadata is None:
                metadata = None
            else:
                metadata = Chunk_metadata(
                    source=azure_search_result.metadata.source,
                    creation_timestamp=azure_search_result.metadata.creation_timestamp,
                    update_timestamp=azure_search_result.metadata.update_timestamp
                )
            chunk = Chunk(
                chunk_id=azure_search_result.id,
                text=azure_search_result.text,
                metadata=metadata,
                related_questions=azure_search_result.related_questions
            )
            chunk_list.append(chunk)
        return chunk_list

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

    # Fallback parsing if XML format fails
    if response_en is None or query_type is None:
        print(f"Warning: Answer generation XML parsing failed. Response: {response_text}")
        # Use fallback values
        response_en = response_text if response_text else "I don't have enough information to answer this question."
        response_source = "fallback"

        print(f"Using fallback answer: {response_en}")

    return response_en, response_source, tokens

async def process_message(input: QueryInput) -> QueryOutput:
    translation_and_rewritting_prompt = input.translation_prompt
    answer_prompt = input.answer_prompt
    top_k = input.top_k
    phone_number_id = input.phone_number_id
    history_length = input.history_length
    search_type = input.search_type.lower()
    embedding_type = input.embedding_type.lower()
    question = input.question

    user_id = hashlib.md5(phone_number_id.encode()).hexdigest()
    conversation_history = get_conversation_history(user_id, history_length)
    print(conversation_history)
    query_en, query_en_addcontext, query_type, tokens = await llm_translation_and_query_rewritting(translation_and_rewritting_prompt, question, conversation_history)
    retrieved_chunks = await aretrieve_top_k_chunks(query_en_addcontext, top_k, search_type, embedding_type)
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