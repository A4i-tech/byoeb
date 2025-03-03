import logging
import json
import time
import byoeb.utils.utils as utils
from datetime import datetime, timezone
from byoeb_core.models.byoeb.message_status import ByoebMessageStatus
from byoeb_core.models.byoeb.message_context import ByoebMessageContext
from byoeb_core.message_queue.base import BaseQueue
from byoeb.chat_app.configuration.dependency_setup import app_insights_logger

class MessageProducerService:
    def __init__(
        self,
        config,
        queue_client: BaseQueue,
    ):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self.__queue_client = queue_client

    def __convert_whatsapp_to_byoeb_message(
        self,
        message
    ) -> ByoebMessageContext:
        import byoeb_integrations.channel.whatsapp.validate_message as wa_validator
        import byoeb_integrations.channel.whatsapp.convert_message as wa_converter
        _, message_type = wa_validator.validate_whatsapp_message(message)
        byoeb_message = wa_converter.convert_whatsapp_to_byoeb_message(message, message_type)
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
        

    async def apublish_message(
        self,
        message,
        channel
    ):
        byoeb_message: ByoebMessageContext = None
        n = 5
        if channel == "whatsapp":
            byoeb_message = self.__convert_whatsapp_to_byoeb_message(message)
        if byoeb_message is None or byoeb_message is False:
            return None, "Invalid message"
        try:
            if self.is_older_than_n_minutes(
                n,
                byoeb_message.incoming_timestamp,
            ):
                return f"Skipped. Older than {n} minutes", None
            result = await self.__queue_client.asend_message(
                byoeb_message.model_dump_json(),
                time_to_live=self._config["message_queue"]["azure"]["time_to_live"])
            self._logger.info(f"Message sent: {result}")
            print(f"Published successfully {result.id}")
            
            app_insights_logger.add_log(
                event_name="message_published",
                details={
                    "message_id": byoeb_message.message_context.message_id,
                    "user_name": byoeb_message.user.user_name,
                }
            )
            return f"Published successfully {result.id}", None
        except Exception as e:
            return None, e