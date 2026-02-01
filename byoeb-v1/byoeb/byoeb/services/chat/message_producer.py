from typing import Any
import logging
import byoeb.utils.utils as utils
from byoeb.services.chat import constants
from datetime import datetime, timezone
from byoeb_core.models.byoeb.message_context import ByoebMessageContext
from byoeb_core.message_queue.base import BaseQueue
from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
from byoeb.services.databases.mongo_db.message_db import MessageMongoDBService
from opentelemetry.trace import Status, StatusCode

from byoeb.observability.tracing import (
    get_conversation_tracer,
    inject_trace_context_into_payload,
    SPAN_APUBLISH_MESSAGE,
    SPAN_CONVERT_WHATSAPP,
    SPAN_DUPLICATE_CHECK,
    SPAN_QUEUE_SEND,
    SPAN_DB_WRITE,
)

class MessageProducerService:
    def __init__(
        self,
        config,
        queue_client: BaseQueue,
        message_db_service: MessageMongoDBService
    ):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self.__queue_client = queue_client
        self.__message_db_service = message_db_service
        self._message_pub_logger = AppInsightsLogHandler.getLogger("message_published")
        self._tracer = get_conversation_tracer()

    def __convert_whatsapp_to_byoeb_message(self, message: dict[str, Any]) -> ByoebMessageContext:
        import byoeb_integrations.channel.whatsapp.validate_message as wa_validator
        import byoeb_integrations.channel.whatsapp.convert_message as wa_converter
        _, message_type = wa_validator.validate_whatsapp_message(message)
        self._logger.debug("message=%s", message)
        byoeb_message = wa_converter.convert_whatsapp_to_byoeb_message(message, message_type)
        try:
            msg_ctx = getattr(byoeb_message, "message_context", None)
            if (
                msg_ctx is not None
                and getattr(msg_ctx, "message_type", None) == "interactive_list_reply"
                and not getattr(msg_ctx, "message_source_text", None)
            ):
                entry = (message or {}).get("entry", [])
                changes = entry[0].get("changes", []) if entry else []
                value = changes[0].get("value", {}) if changes else {}
                msgs = value.get("messages", [])
                interactive = msgs[0].get("interactive", {}) if msgs else {}
                list_reply = interactive.get("list_reply", {}) if interactive else {}
                selected_text = list_reply.get("title") or list_reply.get("id")
                if selected_text:
                    msg_ctx.message_source_text = selected_text
                    self._logger.info("[FALLBACK] Set message_source_text='%s' for interactive list reply", selected_text)
        except Exception as e:
            self._logger.exception("[FALLBACK] Error extracting text: %s", e)
        self._logger.debug("byoeb_message=%s", byoeb_message)
        return byoeb_message
    
    def is_older_than_n_minutes(
        self,
        n,
        unix_timestamp
    ) -> bool:
        seconds = n*60
        current_time = datetime.now(timezone.utc).timestamp()
        utils.log_to_text_file(f"Message duration: {current_time - unix_timestamp}")
        self._logger.info(f"Message duration: {current_time - unix_timestamp}")
        if current_time - unix_timestamp > seconds:
            return True
        return False

    async def apublish_message(self, message: dict[str, Any], channel: str, integration_id: str) -> str:
        byoeb_message = None
        n = 5

        with self._tracer.start_as_current_span(SPAN_APUBLISH_MESSAGE) as apub_span:
            apub_span.set_attribute("channel", channel)

            if channel == "whatsapp":
                with self._tracer.start_as_current_span(SPAN_CONVERT_WHATSAPP) as conv_span:
                    byoeb_message = self.__convert_whatsapp_to_byoeb_message(message)
                    conv_span.set_attribute("message_id", byoeb_message.message_context.message_id or "" if byoeb_message.message_context is not None else "")

            if byoeb_message is None or byoeb_message is False:
                raise ValueError("Invalid message")

            byoeb_message.message_context.additional_info = byoeb_message.message_context.additional_info or {}
            byoeb_message.message_context.additional_info[constants.INTEGRATION_ID] = integration_id

            mid = byoeb_message.message_context.message_id if byoeb_message.message_context is not None else None
            mid = mid or ""
            apub_span.set_attribute("message_id", mid)

            if self.is_older_than_n_minutes(n, byoeb_message.incoming_timestamp):
                return f"Skipped. Older than {n} minutes"

            with self._tracer.start_as_current_span(SPAN_DUPLICATE_CHECK) as dup_span:
                dup_span.set_attribute("message_id", mid)
                res = await self.__message_db_service.get_bot_messages_by_ids([mid])
                dup_span.set_attribute("duplicate", len(res) > 0)
            if len(res) > 0:
                return "Already processed"

            # queue publish (inject trace context into payload when available)
            payload_to_send = inject_trace_context_into_payload(byoeb_message)
            with self._tracer.start_as_current_span(SPAN_QUEUE_SEND) as send_span:
                send_span.set_attribute("message_id", mid)
                result = await self.__queue_client.send_message(payload_to_send, time_to_live=self._config["message_queue"]["azure"]["time_to_live"])
                self._logger.info("[apublish_message] ← queue result id=%s", getattr(result, "id", None))

            phone_number_id = byoeb_message.user.phone_number_id if byoeb_message.user is not None else None
            self._message_pub_logger.info(f"Published message_id={mid} phone_number_id={phone_number_id}", extra={AppInsightsLogHandler.DETAILS: {
                "message_id": mid,
                "phone_number_id": phone_number_id
            }})

            # db write
            with self._tracer.start_as_current_span(SPAN_DB_WRITE) as db_span:
                db_span.set_attribute("message_id", mid)
                message_db_queries = {
                    constants.CREATE: self.__message_db_service.message_create_queries(byoeb_messages=[byoeb_message]),
                }
                await self.__message_db_service.execute_queries(message_db_queries)

            return f"Published successfully {getattr(result, 'id', None)}"