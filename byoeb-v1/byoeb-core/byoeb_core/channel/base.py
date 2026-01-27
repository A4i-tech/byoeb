from abc import ABC, abstractmethod
from typing import Any, Dict
from byoeb_core.models.byoeb.response import ByoebResponseModel

class BaseChannelRegister(ABC):
    @abstractmethod
    async def register(
        self,
        request: str,
        **kwargs
    )-> ByoebResponseModel:
        pass

class BaseChannel(ABC):
    @abstractmethod
    async def send_message(
        self,
        message: Any,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def receive_message(
        self,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def reply_to_message(
        self,
        message: Any,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def send_reaction(
        self,
        reactions,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def send_template(
        self,
        template: Any,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def send_poll(
        self,
        poll: Any,
        **kwargs
    ) -> Any:
        pass

    async def send_interactive_message(
        self,
        message: Any,
        **kwargs
    ) -> Any:
        pass