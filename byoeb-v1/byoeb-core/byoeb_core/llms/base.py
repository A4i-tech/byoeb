from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseLLM(ABC):
    @abstractmethod
    async def generate_response(
        self,
        prompts,
        **kwargs
    ) -> Any:
        pass
    @abstractmethod
    def get_llm_client(self) -> Any:
        pass

    @abstractmethod
    def get_response_tokens(self, response) -> Dict[str, int]:
        pass