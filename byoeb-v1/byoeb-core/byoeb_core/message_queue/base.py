from abc import ABC, abstractmethod
from typing import Any

class BaseQueue(ABC):
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
    async def delete_message(
        self,
        message,
        **kwargs
    ) -> Any:
        pass