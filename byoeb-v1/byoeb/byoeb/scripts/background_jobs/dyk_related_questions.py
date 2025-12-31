import asyncio
import json
from typing import Dict, List

from byoeb.constants.user_enums import LanguageCode
from byoeb.kb_app.configuration.config import prompt_config
from byoeb.kb_app.configuration.dependency_setup import vector_store
from byoeb.models.dyk import DykEntry
from byoeb.repositories.repository_factory import get_repository_factory
from byoeb_integrations.vector_stores.related_questions import aget_related_questions
from tqdm import tqdm


async def populate_missing_related_questions(concurrency: int) -> Dict[str, int]:
    """Populate related questions only for languages that do not have them."""
    from byoeb.kb_app.configuration.dependency_setup import llm_client

    prompts = prompt_config.get("languages_translation_prompts", {})
    repo = await (await get_repository_factory()).get_dyk_repository()

    updated = 0
    populated = 0
    sem = asyncio.Semaphore(concurrency)
    progress = tqdm(desc="Processing DYK entries", unit="entry")

    async def run(entry):
        nonlocal updated, populated
        async with sem:
            langs = await populate_entry(entry, prompts, llm_client)
            progress.update(1)
            if langs:
                await repo.add(entry)
                updated += 1
                populated += len(langs)
                for p in langs:
                    print(json.dumps(p))

    try:
        await asyncio.gather(*[run(DykEntry.model_validate(e)) async for e in repo.find_all()])
    finally:
        progress.close()

    return {"entries_updated": updated, "languages_populated": populated}


async def populate_entry(entry: DykEntry, translation_prompts: Dict[str, str], llm_client) -> List[Dict[str, object]]:
    """Populate related questions for a single DYK entry."""
    missing_langs = [
        lang for lang, record in entry.languages.items()
        if not record.related_questions
    ]
    if not missing_langs:
        return []

    reference_record = entry.languages.get(LanguageCode.ENGLISH) or next(iter(entry.languages.values()))
    prompt_subset = {
        lang.value: translation_prompts[lang.value]
        for lang in missing_langs
        if lang != LanguageCode.ENGLISH and lang.value in translation_prompts
    }
    if not prompt_subset and LanguageCode.ENGLISH not in missing_langs:
        return []

    related = await aget_related_questions(reference_record.fact, llm_client, prompt_subset, vector_store, length=20)
    updated_payloads: List[Dict[str, object]] = []
    for lang in missing_langs:
        questions = related.get(lang.value)
        if questions:
            entry.languages[lang].related_questions = [text[:20] for text in questions]
            updated_payloads.append({
                "dyk_id": str(entry.id),
                "language": lang.value,
                "questions": questions,
            })
    return updated_payloads


def main() -> None:
    summary = asyncio.run(populate_missing_related_questions(concurrency=5))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
