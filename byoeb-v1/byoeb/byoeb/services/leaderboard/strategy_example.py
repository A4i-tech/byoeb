"""
Example usage of the Strategy Pattern for time window calculations in leaderboard functionality.
"""
import asyncio
import logging
from byoeb.services.leaderboard.time_window_strategies import TimeWindowFactory
from byoeb.services.leaderboard.leaderboard_service import LeaderboardService
from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService
from byoeb.chat_app.configuration.dependency_setup import user_db_service, message_db_service

logger = logging.getLogger(__name__)


async def demonstrate_strategy_pattern():
    """Demonstrate different time window strategies for leaderboard generation."""

    logger.info("🎯 Strategy Pattern Demonstration")
    logger.info("=" * 50)

    # Create services
    leaderboard_service = LeaderboardService(user_db_service, message_db_service)

    # Show available strategies
    logger.info("📋 Available strategies: %s", leaderboard_service.get_available_strategies())
    logger.info("🔧 Current strategy: %s", leaderboard_service.get_current_strategy_name())

    # Example 1: Use default strategy (week)
    logger.info("📊 Example 1: Default Strategy (Week)")
    try:
        df = await leaderboard_service.build_district_leaderboard()
        logger.info("Generated leaderboard with %s districts", len(df))
        if not df.empty:
            logger.info("\n%s", df.head(3).to_string(index=False))
    except Exception as e:
        logger.error("Error in default strategy: %s", e, exc_info=True)

    # Example 2: Use monthly strategy
    logger.info("📊 Example 2: Monthly Strategy")
    try:
        monthly_strategy = TimeWindowFactory.create_strategy('month')
        df = await leaderboard_service.build_district_leaderboard(time_window_strategy=monthly_strategy)
        logger.info("Generated monthly leaderboard with %s districts", len(df))
        if not df.empty:
            logger.info("\n%s", df.head(3).to_string(index=False))
    except Exception as e:
        logger.error("Monthly strategy error: %s", e, exc_info=True)

    # Example 3: Use custom strategy (last 14 days)
    logger.info("📊 Example 3: Custom Strategy (Last 14 Days)")
    try:
        custom_strategy = TimeWindowFactory.create_strategy('custom', days_back=14, name='Last 14 Days')
        df = await leaderboard_service.build_district_leaderboard(time_window_strategy=custom_strategy)
        logger.info("Generated 14-day leaderboard with %s districts", len(df))
        if not df.empty:
            logger.info("\n%s", df.head(3).to_string(index=False))
    except Exception as e:
        logger.error("Custom 14-day strategy error: %s", e, exc_info=True)

    # Example 4: Change service strategy dynamically
    logger.info("📊 Example 4: Dynamic Strategy Change")
    try:
        yearly_strategy = TimeWindowFactory.create_strategy('year')
        leaderboard_service.set_time_window_strategy(yearly_strategy)
        logger.info("Changed strategy to: %s", leaderboard_service.get_current_strategy_name())

        df = await leaderboard_service.build_district_leaderboard()
        logger.info("Generated yearly leaderboard with %s districts", len(df))
        if not df.empty:
            logger.info("\n%s", df.head(3).to_string(index=False))
    except Exception as e:
        logger.error("Yearly strategy error: %s", e, exc_info=True)

    # Example 5: Test different custom periods
    logger.info("📊 Example 5: Multiple Custom Periods")
    custom_periods = [
        (7, "Last 7 Days"),
        (30, "Last 30 Days"),
        (90, "Last 90 Days")
    ]

    for days, name in custom_periods:
        try:
            strategy = TimeWindowFactory.create_strategy('custom', days_back=days, name=name)
            df = await leaderboard_service.build_district_leaderboard(time_window_strategy=strategy)
            logger.info("%s: %s districts", name, len(df))
        except Exception as e:
            logger.error("%s: Error - %s", name, e, exc_info=True)

    logger.info("✅ Strategy pattern demonstration completed!")


if __name__ == "__main__":
    asyncio.run(demonstrate_strategy_pattern())
