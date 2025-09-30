"""
Example usage of the Repository Pattern in the BYOEB project.
"""
from typing import List, Dict, Any
from byoeb.repositories import RepositoryFactory, MessageRepository, UserRepository
from byoeb.factory import MongoDBFactory
from byoeb.background_jobs.config import app_config


async def example_usage():
    """Example demonstrating how to use the repository pattern."""
    
    # Initialize repository factory
    mongo_factory = MongoDBFactory(config=app_config, scope="singleton")
    repository_factory = RepositoryFactory(mongo_factory)
    
    # Get repository instances
    message_repository: MessageRepository = await repository_factory.get_message_repository()
    user_repository: UserRepository = await repository_factory.get_user_repository()
    
    # Example 1: Find messages by time range
    messages = await message_repository.find_messages_by_time_range(
        start_timestamp=1640995200,  # Jan 1, 2022
        end_timestamp=1641081600,    # Jan 2, 2022
        message_categories=["asha_work_related"]
    )
    print(f"Found {len(messages)} messages")
    
    # Example 2: Find users by type
    asha_users = await user_repository.find_users_by_type("asha")
    print(f"Found {len(asha_users)} ASHA users")
    
    # Example 3: Find ASHA and test users
    asha_and_test_users = await user_repository.find_asha_and_test_users()
    print(f"Found {len(asha_and_test_users)} ASHA and test users")
    
    # Example 4: Count messages by category
    message_count = await message_repository.count_messages_by_time_range(
        start_timestamp=1640995200,
        end_timestamp=1641081600,
        message_categories=["small_talk"]
    )
    print(f"Found {message_count} small talk messages")
    
    # Example 5: Find recent messages for a user
    recent_messages = await message_repository.find_recent_messages_by_user(
        user_id="some_user_id",
        limit=5
    )
    print(f"Found {len(recent_messages)} recent messages for user")


if __name__ == "__main__":
    import asyncio
    asyncio.run(example_usage())
