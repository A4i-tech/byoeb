from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class AuthRepository(ABC):
    @abstractmethod
    async def find_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def update_user_by_username(self, username: str, updates: Dict[str, Any]) -> bool:
        raise NotImplementedError
