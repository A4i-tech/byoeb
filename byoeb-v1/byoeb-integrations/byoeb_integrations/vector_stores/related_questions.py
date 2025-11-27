import asyncio
import json
import re
from typing import List, Optional
from byoeb_core.llms.base import BaseLLM
from byoeb_core.vector_stores.base import BaseVectorStore
from pydantic import TypeAdapter
from tenacity import retry, stop_after_attempt, wait_fixed

@retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
async def aget_search_queries(text: str, llm_client: BaseLLM) -> List[str]:
    prompt = [{"role": "user", "content": (
        "Produce up to 3 short search keywords. "
        "Each query should identify topics that are somewhat related to the text, "
        "but *not directly answered by it*. "
        "Return ONLY a JSON list of strings. No explanations. "
        "Text:\n\n" + text
    )}]
    _, resp = await llm_client.agenerate_response(prompt)
    start = resp.find("[")
    end = resp.rfind("]") + 1
    words = json.loads(resp[start:end])
    return TypeAdapter(List[str]).validate_python(words)


async def aget_related_questions(
    text,
    llm_client: BaseLLM,
    languages_translation_prompts: dict,
    vector_store: Optional[BaseVectorStore] = None,
    system_prompt = None,
    length: int = 60
):
    related_chunks = []
    if vector_store:
        from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorSearchType
        queries = await aget_search_queries(text, llm_client)
        results = await asyncio.gather(*[vector_store.aretrieve_top_k_chunks(
            q,
            k=2,
            search_type=AzureVectorSearchType.DENSE.value,
            select=["id", "text"],
            vector_field="text_vector_3072"
        ) for q in queries])
        related_chunks = [c.text for r in results for c in r]

    related_questions_dict = {}
    if not system_prompt:
        related_chunks_text = "\n\n".join(related_chunks)
        system_prompt = (
            "Generate three related questions for the given text. "
            "Follow the instructions. "
            "1. Each question MUST be DISTINCT i.e., intended to elicit different information.\n\n"
            f"2. Each question's length MUST be <character_limit>{length}</character_limit> CHARACTERS OR LESS.\n\n"
            "3. Respond with the three questions in XML format.\n\n"
            "Sample output:\n"
            "<related_questions>\n"
            "<q_1>Content of first question</q_1>\n"
            "<q_2>Content of second question</q_2>\n"
            "<q_3>Content of third question</q_3>\n"
            "</related_questions>\n\n"
            "<instructions>\n"
            "Use the following related chunks as additional context:\n"
            "<related_chunks>\n"
            f"{related_chunks_text}\n"
            "</related_chunks>\n"
            "</instructions>"
        )

    prompt = [{"role": "system", "content": system_prompt}]
    prompt.append({"role": "user", "content": text})
    llm_response, resp = await llm_client.generate_response(prompt)
    related_questions = re.findall(r"<q_\d+>(.*?)</q_\d+>", resp)
    related_questions_dict["en"] = related_questions

    for lang, translation_prompt in languages_translation_prompts.items():
        user_prompt = f"""Translate the following list of questions <en_questions> {related_questions} </en_questions> from english to desired language.
        Maintain the output structure as follows:
        <related_questions>
        <q_1>Translated question 1</q_1>
        <q_2>Translated question 2</q_2>
        <q_3>Translated question 3</q_3>
        </related_questions>
        Note above is a sample for three questions follow same based on number of questions.
        """
        prompt = [{"role": "system", "content": translation_prompt}]
        prompt.append({"role": "user", "content": user_prompt})
        llm_response, resp = await llm_client.generate_response(prompt)
        related_questions = re.findall(r"<q_\d+>(.*?)</q_\d+>", resp)
        related_questions_dict[lang] = related_questions
    
    return related_questions_dict
        