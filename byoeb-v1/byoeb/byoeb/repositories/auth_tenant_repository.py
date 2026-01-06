from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from uuid import UUID


class AuthTenantRepository(ABC):
    @abstractmethod
    async def find_tenant_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def update_tenant_roles(self, tenant_id: UUID, roles: Dict[str, Any]) -> bool:
        raise NotImplementedError
