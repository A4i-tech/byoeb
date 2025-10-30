"""
Base repository interface for abstracting data access patterns.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime


class BaseRepository(ABC):
    """Base repository interface defining common data access operations."""

    @abstractmethod
    async def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Find a single document by its ID."""
        pass

    @abstractmethod
    async def find_all(self, filter_dict: Optional[Dict[str, Any]] = None, 
                      projection: Optional[Dict[str, Any]] = None,
                      sort: Optional[List[tuple]] = None,
                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Find multiple documents with optional filtering, projection, sorting, and limiting."""
        pass

    @abstractmethod
    async def count(self, filter_dict: Optional[Dict[str, Any]] = None) -> int:
        """Count documents matching the filter criteria."""
        pass

    @abstractmethod
    async def insert_one(self, document: Dict[str, Any]) -> str:
        """Insert a single document and return its ID."""
        pass

    @abstractmethod
    async def insert_many(self, documents: List[Dict[str, Any]]) -> List[str]:
        """Insert multiple documents and return their IDs."""
        pass

    @abstractmethod
    async def update_one(self, filter_dict: Dict[str, Any], 
                        update_dict: Dict[str, Any]) -> bool:
        """Update a single document matching the filter criteria."""
        pass

    @abstractmethod
    async def update_many(self, filter_dict: Dict[str, Any], 
                         update_dict: Dict[str, Any]) -> int:
        """Update multiple documents matching the filter criteria."""
        pass

    @abstractmethod
    async def delete_one(self, filter_dict: Dict[str, Any]) -> bool:
        """Delete a single document matching the filter criteria."""
        pass

    @abstractmethod
    async def delete_many(self, filter_dict: Dict[str, Any]) -> int:
        """Delete multiple documents matching the filter criteria."""
        pass

    @abstractmethod
    async def bulk_update(self, bulk_queries: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> int:
        """Execute multiple heterogeneous update operations as a bulk update."""
        pass
