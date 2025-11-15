import logging
import sys
import uuid
from azure.monitor.events.extension import track_event

class AppInsightsLogHandler(logging.Handler):
    """
    Attach to a logger to mirror logs to Azure App Insights. Supports structured logging.

    Example:
        from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler

        my_logger = AppInsightsLogHandler.create_logger("my_logger_name")  # <-- also the name of event under 'customEvents'
        my_logger.info("hello")                                             # basic logging
        my_logger.info("hello", extra={AppInsightsLogHandler.DETAILS: {  # structured logging
            "user_id": "xyz",
            "phone_number": "91xx"
        }})
    """

    # map structured logs to this field in 'extra'
    # e.g., logger.info("message", extra={AppInsightsLogHandler.DETAILS: {"key1": "value1"}})
    # 'key1' will be accessible thru customDimenisons.["details.key1"]
    DETAILS = str(uuid.uuid4())

    @staticmethod
    def getLogger(name: str, level: int = logging.DEBUG) -> logging.Logger:
        """
        Create a logger configured with a console handler and App Insights handler.
        """
        logger = logging.getLogger(name)
        logger.setLevel(level)
        formatter = logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s")
        if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)
        if not any(isinstance(handler, AppInsightsLogHandler) for handler in logger.handlers):
            logger.addHandler(AppInsightsLogHandler())
        logger.propagate = False
        return logger

    def emit(self, record):
        details = {"details.level": record.levelname, "details.message": record.getMessage()}
        for k, v in getattr(record, AppInsightsLogHandler.DETAILS, {}).items():
            details["details." + k] = v
        track_event(record.name, details)