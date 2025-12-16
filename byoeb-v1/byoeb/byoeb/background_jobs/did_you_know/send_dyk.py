import asyncio
import csv
import json
import random
import uuid
from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
from byoeb.background_jobs.did_you_know.config import bot_config, current_dir
from byoeb.chat_app.configuration.dependency_setup import channel_client_factory
from byoeb.models.dyk import DykFactSheet, DykRecord
from byoeb.repositories.dyk_repository import DykRepository
from byoeb.repositories.user_repository import UserRepository
from byoeb.utils.utils import chunked
from byoeb.constants.user_enums import LanguageCode
from byoeb.repositories.repository_factory import get_repository_factory
from byoeb.services.channel.whatsapp import WhatsAppService
from byoeb.services.chat import constants
from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageContext, MessageTypes
from byoeb_core.models.byoeb.user import User
from byoeb_integrations.channel.whatsapp.meta.async_whatsapp_client import StatusCode
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable, List, Optional, Set, Tuple, TypeAlias
import os
import re


DykBatch: TypeAlias = Iterable[Tuple[User, Set[str]]]

def clean_template_param(text: str) -> str:
    """Make template parameter safe for WhatsApp: no newlines/tabs, no 4+ spaces."""
    # Replace newlines/tabs with single space
    text = re.sub(r"[\r\n\t]+", " ", text)
    # Collapse multiple spaces to single
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()

async def pick_candidates(dyk_repo: DykRepository, user_repo: UserRepository, langs: Iterable[LanguageCode], user_types: List[str], batch_size: int) -> AsyncIterator[DykBatch]:
    """
    Does a buffered fetch operation on users collection and get their set of sent DYK ids.
    Collects only users who meet all the following criteria:
    - the user is an asha user (prod only)
    - the user is a test user (staging only)
    - the user has a language available in `langs`
    - the user has no 'pending' DYKs
    """
    select_test_only = os.getenv("TEST_USERS_ONLY", "false").lower() == "true"
    if len(user_types) > 0:
        if select_test_only and hasattr(user_repo, "find_test_users_by_types"):
            potential_candidates = await user_repo.find_test_users_by_types(user_types)
        else:
            potential_candidates = await user_repo.find_users_by_types(user_types)
    else:
        if select_test_only:
            run_logger.debug(f"{pick_candidates.__name__}: TEST_USERS_ONLY enabled - selecting test users")
            potential_candidates = await user_repo.find_test_users()
        else:
            run_logger.debug(f"{pick_candidates.__name__}: no user_types provided - selecting all users")
            potential_candidates = await user_repo.find_all({})
    
    filtern_user_ids = set(record.user_id for record in await dyk_repo.find_pending_of_langs(langs))
    users = map(lambda x: User(**x["User"]), potential_candidates)
    users = filter(lambda x: x.user_id not in filtern_user_ids, users)

    for chunk in chunked(users, batch_size):
        dyk_id_sets = await dyk_repo.find_sent_dyk_ids([str(u.user_id) for u in chunk])
        yield zip(chunk, dyk_id_sets)


async def queue(dyk_repo: DykRepository, sheet: DykFactSheet, candidates: DykBatch) -> Tuple[str, int, int]:
    """
    Takes a structured set of DYK records and randomly distributes them across the userbase, ensuring:
    - a user is sent DYK message in only their language
    - a user is not sent a DYK message they were previously sent
    Returns lists of queued and exhausted operations.

    Example:
        records = {
            LanguageCode.ENGLISH: {
                "00000000-0000-0000-0000-000000000000": "Blueberries were once red."
            }
        }

        batch_id, queued, exhausted = await queue(records, [])
        print("Queued %d ops, exhausted %d ops", queued, exhausted)
    """

    batch_id = uuid.uuid4().hex
    n_queued = 0
    n_exhausted = 0
    lang_sets = {lang: set(messages.keys()) for lang, messages in sheet.items()}
    queued_client_ops = []
    for user, sent in candidates:
        if user.user_language is None:
            continue
        lang = LanguageCode(user.user_language)
        if not lang in lang_sets:
            continue
        diff = lang_sets[lang] - sent  # deduplication
        if len(diff) == 0:
            # no facts remaining !
            send_logger.warning("User %s is exhausted", user.user_id, extra={AppInsightsLogHandler.DETAILS: {
                "context": queue.__name__,
                "user_id": user.user_id,
                "user_phone_number": user.phone_number_id
            }})
            n_exhausted += 1
            continue
        dyk_id = random.choice(list(diff))
        queued_client_ops.append(DykRecord(
            id="",
            dyk_id=uuid.UUID(dyk_id),
            dyk_lang=lang,
            user_id=str(user.user_id),
            time=datetime.now(),
            status="pending",
            batch_id=batch_id
        ))
        send_logger.info("[batch-%s] User %s is assigned DYK %s", batch_id, user.user_id, dyk_id, extra={AppInsightsLogHandler.DETAILS: {
            "context": queue.__name__,
            "dyk_id": str(dyk_id),
            "user_id": user.user_id,
            "batch_id": batch_id,
            "user_phone_number": user.phone_number_id
        }})
        n_queued += 1

    if len(queued_client_ops) > 0:
        await dyk_repo.insert(queued_client_ops)
    return batch_id, n_queued, n_exhausted


async def dispatch(dyk_repo: DykRepository, user_repo: UserRepository, sheet: DykFactSheet, whatsapp_service: WhatsAppService, batch_id: str) -> Tuple[int, int]:
    """ Dispatches queued DYK messages to WhatsApp. Returns number of successful and unsuccessful operations. """

    pending = await dyk_repo.find_pending_of_batches(sheet.keys(), [batch_id])
    users: dict[str, Optional[User]] = {p.user_id: None for p in pending}
    for user in await user_repo.find_users_by_ids(list(users.keys())):
        user = User(**user["User"])
        users[str(user.user_id)] = user

    ts = int(datetime.now(timezone.utc).timestamp())
    n_success = 0
    n_failure = 0

    aborted = []
    completed = []
    try:
        for record in pending:
            user = users[record.user_id]
            if not user:
                send_logger.warning("User %s not found", record.user_id, extra={AppInsightsLogHandler.DETAILS: {
                    "context": dispatch.__name__,
                    "dyk_id": str(record.dyk_id),
                    "user_id": record.user_id,
                    "batch_id": batch_id
                }})
                aborted.append(record.id)
                continue

            phone_number = user.phone_number_id

            # Build template parameter (1 param: the fact text)
            # Use only the fact text (no decorative prefix) to avoid extra phrasing like "💡 क्या आपको पता है?"
            fact_text = sheet[record.dyk_lang][str(record.dyk_id)]
            template_parameters = [clean_template_param(fact_text)]

            # Create ByoebMessageContext for WhatsApp template message
            byoeb_message = ByoebMessageContext(
                channel_type="whatsapp",
                message_category="did_you_know",
                user=user,
                message_context=MessageContext(
                    message_id=f"did-you-know-{record.id}",
                    message_type=MessageTypes.TEMPLATE_TEXT.value,
                    message_source_text=None,
                    message_english_text=None,
                    media_info=None,
                    additional_info={
                        constants.TEMPLATE_NAME: "did_you_know_v2",
                        constants.TEMPLATE_LANGUAGE: record.dyk_lang.value,
                        constants.TEMPLATE_PARAMETERS: template_parameters,
                    },
                ),
                reply_context=None,
                cross_conversation_id=None,
                cross_conversation_context=None,
                incoming_timestamp=ts,
                outgoing_timestamp=ts
            )

            requests = whatsapp_service.prepare_requests(byoeb_message)
            if not requests:
                send_logger.error("Failed to prepare a request message", extra={AppInsightsLogHandler.DETAILS: {
                    "context": dispatch.__name__,
                    "dyk_id": str(record.dyk_id),
                    "user_id": record.user_id,
                    "batch_id": batch_id,
                    "user_phone_number": phone_number
                }})
                n_failure += 1
                continue

            # TODO: we should probably batch `requests` here so we call send_requests() sparingly...
            responses, message_ids = await whatsapp_service.send_requests(requests)
            assert len(responses) == 1
            if int(responses[0].response_status.status) != StatusCode.SUCCESS.value:
                send_logger.error(responses[0].response_status.error, extra={AppInsightsLogHandler.DETAILS: {
                    "context": dispatch.__name__,
                    "dyk_id": str(record.dyk_id),
                    "user_id": record.user_id,
                    "batch_id": batch_id,
                    "user_phone_number": phone_number,
                    "whatsapp_response_code": responses[0].response_status.status
                }})
                n_failure += 1
                continue

            send_logger.info("Sent DYK %s to user %s", record.dyk_id, record.user_id, extra={AppInsightsLogHandler.DETAILS: {
                "context": dispatch.__name__,
                "dyk_id": str(record.dyk_id),
                "user_id": record.user_id,
                "batch_id": batch_id,
                "user_phone_number": phone_number,
                "whatsapp_message_ids": json.dumps(message_ids)
            }})
            completed.append(record.id)
            n_success += 1
    finally:
        await dyk_repo.update_status(aborted, "aborted")
        await dyk_repo.update_status(completed, "completed")
    return n_success, n_failure


async def main(sheet: DykFactSheet, user_types: List[str], batch_size: int) -> None:
    try:
        factory = await get_repository_factory()
        dyk_repo = await factory.get_dyk_repository()
        user_repo = await factory.get_user_repository()

        # sync (...with runtime. delete pending records with unknown langs, unknown dyk ids)
        synced = await dyk_repo.synchronize({k: list(v.keys()) for k, v in sheet.items()})
        run_logger.info("Synced jobs: %d", synced)  # pending messages that were discarded (because they no longer reference a DYK message)

        # schedule (pick candidates in batches and assign them dyk ids)
        async for batch in pick_candidates(dyk_repo, user_repo, sheet.keys(), user_types, batch_size):
            batch_id, queued, exhausted = await queue(dyk_repo, sheet, batch)
            run_logger.info("[batch-%s] Queued jobs: %d", batch_id, queued, extra={AppInsightsLogHandler.DETAILS: {"batch_id": batch_id}})  # messages that were added to the dispatch queue
            run_logger.info("[batch-%s] Exhausted jobs: %d", batch_id, exhausted, extra={AppInsightsLogHandler.DETAILS: {"batch_id": batch_id}})  # users who could not be sent a DYK message (because they have received every DYK message)

        # dispatch (...to whatsapp. pick a batch of candidates and send them their assigned dyks)
        whatsapp_service = WhatsAppService(channel_client_factory)
        batch_ids = await dyk_repo.find_pending_batch_ids()
        retries = 0
        while True:
            if retries > 0:
                run_logger.warning("Retrying dispatch job... %d / %d", retries + 1, N_RETRIES)

            failed_batches = []
            for batch_id in batch_ids:
                success, fail = await dispatch(dyk_repo, user_repo, sheet, whatsapp_service, batch_id)
                run_logger.info("[batch-%s] Dispatched jobs: %d succeeded, %d failed", batch_id, success, fail, extra={AppInsightsLogHandler.DETAILS: {"batch_id": batch_id}})  # messages that were sent to WhatsApp (includes messages that were just queued)
                if fail > 0:
                    failed_batches.append(batch_id)

            if len(failed_batches) == 0:
                break
            batch_ids = failed_batches
            retries += 1
            if retries == N_RETRIES:
                run_logger.error("Max retries exceeded. Exiting.")
                break
            await asyncio.sleep(2.5)
    finally:
        await channel_client_factory.close()


run_logger = AppInsightsLogHandler.getLogger("dyk_run")
send_logger = AppInsightsLogHandler.getLogger("dyk_send")

user_types_to_send = bot_config["user_types_to_send"]
# WhatsApp-configured templates now drive DYK; keep a simple language list for CSV parsing.
LANGS = [LanguageCode.ENGLISH, LanguageCode.HINDI, LanguageCode.MARATHI, LanguageCode.TELUGU]
N_RETRIES = 5  # number of times to retry dispatch()ing to WhatsApp in the event of failure

SOURCE_PATH = (current_dir / str(bot_config["path"])).resolve()
if not SOURCE_PATH.exists():
    run_logger.error("File not found: %s", SOURCE_PATH)  # we still need this so app insights logs it
    raise FileNotFoundError("File not found: %s" % SOURCE_PATH)

# parse and index facts sheet for quick lookup
with SOURCE_PATH.open(encoding="utf-8") as f:
    reader = csv.reader(f)

    # fail fast - if these expected cols dont exist, python will bail early
    cols = next(reader)
    lang_cols = {}
    for lang in LANGS:
        col = lang.value
        if col not in cols: raise ValueError(f'Column "{col}" does not exist in {SOURCE_PATH.name} - did you forget to create a column for "{col}"?')
        lang_cols[lang] = cols.index(col)

    guid_col = cols.index("GUID")

    expected_cols = {"GUID", *[l.value for l in LANGS]}
    unexpected_cols = [c for c in cols if c not in expected_cols]
    if len(unexpected_cols) > 0:
        run_logger.error("Unexpected columns encountered in %s: %s", SOURCE_PATH.name, ", ".join(unexpected_cols))
        raise ValueError("Unexpected columns encountered in %s: %s" % (SOURCE_PATH.name, ", ".join(unexpected_cols)))

    sheet: DykFactSheet = {lang: {} for lang in lang_cols.keys()}
    for row in reader:
        # Skip completely empty rows
        if not row or all(not cell.strip() for cell in row):
            continue

        # Fail fast on missing/empty GUID cell
        if len(row) <= guid_col:
            raise ValueError(f"Missing GUID column in {SOURCE_PATH.name}, row: {row}")
        guid_raw = row[guid_col].strip()
        if not guid_raw:
            raise ValueError(f"Empty GUID in {SOURCE_PATH.name}, row: {row}")

        # Fail fast on invalid GUID
        id = str(uuid.UUID(guid_raw))

        for lang, lang_col in lang_cols.items():
            # Fail fast if language column is missing in this row
            if len(row) <= lang_col:
                raise ValueError(f"Missing column for language {lang} in {SOURCE_PATH.name}, row: {row}")
            message = row[lang_col].strip()
            if len(message) > 0:
                sheet[lang][id] = message

# Wrapper function for scheduler to call without arguments
async def run():
    """Wrapper function that loads config and calls main() - used by scheduler"""
    await main(sheet, user_types_to_send, 2048)

if __name__ == "__main__":
    asyncio.run(main(sheet, user_types_to_send, 2048))
