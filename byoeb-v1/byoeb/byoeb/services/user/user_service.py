"""
User Service for managing user-related operations.
"""
from typing import List, Dict, Any, Optional
from byoeb.repositories.repository_factory import get_repository_factory

class UserService:
    """Service class for user-related operations."""

    def __init__(self):
        pass

    async def fetch_phone_numbers_for_asha_and_test_users(self) -> List[str]:
        """
        Retrieves phone numbers for all ASHA workers and test users from the database.

        Returns:
            List[str]: Phone numbers of ASHA workers and test users
        """
        repository_factory = await get_repository_factory()
        user_repository = await repository_factory.get_user_repository()

        # Use repository method to find ASHA and test users
        asha_and_test_users = await user_repository.find_asha_and_test_users()

        # Extract phone numbers from the results
        collected_phone_numbers = []
        for user_document in asha_and_test_users:
            phone_number = user_document.get("User", {}).get("phone_number_id")
            if phone_number:
                collected_phone_numbers.append(phone_number)

        return collected_phone_numbers

    async def hydrate_users(
        self, 
        message_documents: List[Dict[str, Any]], 
        user_objects_cache: Dict[str, Any]
    ) -> None:
        """
        Hydrate user objects for message documents.

        Args:
            message_documents: List of message documents
            user_objects_cache: Cache to store user objects
        """
        from types import SimpleNamespace

        # Collect unique user IDs from messages
        user_ids = set()
        for message_document in message_documents:
            message_data = message_document.get("message_data", {})
            user_id = message_data.get("user", {}).get("user_id")
            if user_id and user_id not in user_objects_cache:
                user_ids.add(user_id)

        if not user_ids:
            return

        # Get repository instances
        repository_factory = await get_repository_factory()
        user_repository = await repository_factory.get_user_repository()

        # Fetch users from database
        users_data = await user_repository.find_users_by_ids(list(user_ids))

        # Convert to user objects and cache them
        for user_document in users_data:
            user_data = user_document.get("User", {})
            user_id = user_data.get("user_id")
            if user_id:
                user_object = SimpleNamespace(**user_data)
                user_objects_cache[user_id] = user_object
