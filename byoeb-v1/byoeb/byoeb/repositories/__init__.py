"""
Repository package for abstracting data access patterns.
"""
from .base_repository import BaseRepository
from .message_repository import MessageRepository
from .user_repository import UserRepository
from .auth_repository import AuthRepository
from .auth_tenant_repository import AuthTenantRepository
from .mongodb_message_repository import MongoMessageRepository
from .mongodb_user_repository import MongoUserRepository
from .mongodb_auth_repository import MongoAuthRepository
from .mongodb_auth_tenant_repository import MongoAuthTenantRepository
from .repository_factory import RepositoryFactory

__all__ = [
    "BaseRepository",
    "MessageRepository", 
    "UserRepository",
    "AuthRepository",
    "AuthTenantRepository",
    "MongoMessageRepository",
    "MongoUserRepository",
    "MongoAuthRepository",
    "MongoAuthTenantRepository",
    "RepositoryFactory"
]
