"""
Repository package for abstracting data access patterns.
"""
from .base_repository import BaseRepository
from .message_repository import MessageRepository
from .user_repository import UserRepository
from .mongodb_message_repository import MongoMessageRepository
from .mongodb_user_repository import MongoUserRepository
from .repository_factory import RepositoryFactory

__all__ = [
    "BaseRepository",
    "MessageRepository", 
    "UserRepository",
    "MongoMessageRepository",
    "MongoUserRepository",
    "RepositoryFactory"
]
