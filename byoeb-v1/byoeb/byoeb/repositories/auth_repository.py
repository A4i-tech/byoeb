from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from uuid import UUID

from byoeb.repositories.base_repository import BaseRepository


class AuthRepository(BaseRepository, ABC):

    @abstractmethod
    async def find_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def update_user_by_username(self, username: str, updates: Dict[str, Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def update_user_roles_for_tenant(self, username: str, tenant_id: UUID, roles: list[str]) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def find_tenant_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def update_tenant_roles(self, tenant_id: UUID, roles: Dict[str, Any]) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def insert_tenant(self, tenant_doc: Dict[str, Any], roles: Dict[str, Any]) -> str:
        raise NotImplementedError

    @abstractmethod
    async def find_tenant_roles_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        raise NotImplementedError
