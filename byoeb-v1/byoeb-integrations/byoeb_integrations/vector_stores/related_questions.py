import asyncio
import json
import re
from typing import Dict, List, Optional
from byoeb_core.llms.base import BaseLLM
from byoeb_core.vector_stores.base import BaseVectorStore
import grapheme
from pydantic import TypeAdapter
from tenacity import retry, stop_after_attempt, wait_fixed


@retry(stop=stop_after_attempt(3), wait=wait_fixed(1))
async def _aget_search_queries(text: str, llm_client: BaseLLM) -> List[str]:
    """
    Curate 'related questions' queries for vector search lookup.
    """
    prompt = [{"role": "user", "content": (
        "Produce up to 3 short search keywords. "
        "Each query should identify topics that are somewhat related to the text, "
        "but *not directly answered by it*. "
        "Return ONLY a JSON list of strings. No explanations. "
        "Text:\n\n" + text
    )}]
    _, resp = await llm_client.generate_response(prompt)
    start = resp.find("[")
    end = resp.rfind("]") + 1
    words = json.loads(resp[start:end])
    return TypeAdapter(List[str]).validate_python(words)


async def _aget_related_questions(llm_client: BaseLLM, system_prompt: str, user_prompt: str, length: int) -> List[str]:
    resp = None
    errors = ""
    prompts = [
        {"role": "system", "content": system_prompt + f"\n\nEach question must be strictly <= {length} characters (i.e., grapheme clusters)."},
        {"role": "user", "content": user_prompt}
    ]
    for _ in range(5):
        _, resp = await llm_client.generate_response(prompts)
        related_questions = re.findall(r"<q_\d+>(.*?)</q_\d+>", resp)
        prompts.append({"role": "assistant", "content": resp})
        errors = []
        for question in related_questions:
            n_grapheme = grapheme.length(question)
            if n_grapheme > length:
                errors.append(f"- Related question '{question}' is too long ({n_grapheme} > {length}).")

        if not errors:
            return related_questions

        prompts.append({"role": "user", "content": "\n".join(errors) + "\n\nPlease try again."})

    raise ValueError(", ".join(errors))


async def aget_related_questions(
    text: str,
    llm_client: BaseLLM,
    languages_translation_prompts: Dict[str, str],
    vector_store: Optional[BaseVectorStore] = None,
    system_prompt: Optional[str] = None,
    length: int = 60
) -> Dict[str, List[str]]:
    if not system_prompt:
        related_chunks = []
        if vector_store:
            from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorSearchType
            queries = await _aget_search_queries(text, llm_client)
            results = await asyncio.gather(*[vector_store.retrieve_top_k_chunks(
                q,
                k=2,
                search_type=AzureVectorSearchType.DENSE.value,
                select=["id", "text"],
                vector_field="text_vector_3072"
            ) for q in queries])
            related_chunks = [str(c.text) for r in results for c in r]

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

    related_questions = {"en": await _aget_related_questions(llm_client, system_prompt, text, length)}

    user_prompt = f"""Translate the following list of questions <en_questions> {related_questions['en']} </en_questions> from english to desired language.
    Maintain the output structure as follows:
    <related_questions>
    <q_1>Translated question 1</q_1>
    <q_2>Translated question 2</q_2>
    <q_3>Translated question 3</q_3>
    </related_questions>
    Note above is a sample for three questions follow same based on number of questions.
    """
    for lang, translation_prompt in languages_translation_prompts.items():
        related_questions[lang] = await _aget_related_questions(llm_client, translation_prompt, user_prompt, length)

    return related_questions
        