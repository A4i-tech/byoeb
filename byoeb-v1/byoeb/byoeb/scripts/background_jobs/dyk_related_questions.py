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

DEFAULT_PAGE_SIZE = 50


async def populate_missing_related_questions(page_size: int = DEFAULT_PAGE_SIZE) -> Dict[str, int]:
    """Populate related questions only for languages that do not have them."""
    from byoeb.kb_app.configuration.dependency_setup import llm_client

    translation_prompts: Dict[str, str] = prompt_config.get("languages_translation_prompts", {})
    factory = await get_repository_factory()
    repository = await factory.get_dyk_repository()

    offset = 0
    entries_updated = 0
    languages_populated = 0

    progress = tqdm(desc="Processing DYK entries", unit="entry")
    try:
        while True:
            entries = await repository.find_all(offset, page_size)
            if not entries:
                break

            for entry in entries:
                updated_languages = await populate_entry(entry, translation_prompts, llm_client)
                progress.update(1)
                if updated_languages:
                    await repository.add(entry)
                    entries_updated += 1
                    languages_populated += len(updated_languages)
                    for payload in updated_languages:
                        print(json.dumps(payload))

            offset += len(entries)
    finally:
        progress.close()

    return {"entries_updated": entries_updated, "languages_populated": languages_populated}


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
    summary = asyncio.run(populate_missing_related_questions())
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
