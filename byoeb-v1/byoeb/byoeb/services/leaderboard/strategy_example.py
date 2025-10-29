"""
Example usage of the Strategy Pattern for time window calculations in leaderboard functionality.
"""
import asyncio
from byoeb.services.leaderboard.time_window_strategies import TimeWindowFactory
from byoeb.services.leaderboard.leaderboard_service import LeaderboardService
from byoeb.services.user.user_service import UserService

async def demonstrate_strategy_pattern():
    """Demonstrate different time window strategies for leaderboard generation."""

    print("🎯 Strategy Pattern Demonstration")
    print("=" * 50)

    # Create services
    user_service = UserService()
    leaderboard_service = LeaderboardService(user_service)

    # Show available strategies
    print(f"📋 Available strategies: {leaderboard_service.get_available_strategies()}")
    print(f"🔧 Current strategy: {leaderboard_service.get_current_strategy_name()}")
    print()

    # Example 1: Use default strategy (week)
    print("📊 Example 1: Default Strategy (Week)")
    print("-" * 30)
    try:
        df = await leaderboard_service.build_district_leaderboard()
        print(f"Generated leaderboard with {len(df)} districts")
        if not df.empty:
            print(df.head(3).to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")
    print()

    # Example 2: Use monthly strategy
    print("📊 Example 2: Monthly Strategy")
    print("-" * 30)
    try:
        monthly_strategy = TimeWindowFactory.create_strategy('month')
        df = await leaderboard_service.build_district_leaderboard(time_window_strategy=monthly_strategy)
        print(f"Generated monthly leaderboard with {len(df)} districts")
        if not df.empty:
            print(df.head(3).to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")
    print()

    # Example 3: Use custom strategy (last 14 days)
    print("📊 Example 3: Custom Strategy (Last 14 Days)")
    print("-" * 30)
    try:
        custom_strategy = TimeWindowFactory.create_strategy('custom', days_back=14, name='Last 14 Days')
        df = await leaderboard_service.build_district_leaderboard(time_window_strategy=custom_strategy)
        print(f"Generated 14-day leaderboard with {len(df)} districts")
        if not df.empty:
            print(df.head(3).to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")
    print()

    # Example 4: Change service strategy dynamically
    print("📊 Example 4: Dynamic Strategy Change")
    print("-" * 30)
    try:
        # Change to yearly strategy
        yearly_strategy = TimeWindowFactory.create_strategy('year')
        leaderboard_service.set_time_window_strategy(yearly_strategy)
        print(f"Changed strategy to: {leaderboard_service.get_current_strategy_name()}")

        df = await leaderboard_service.build_district_leaderboard()
        print(f"Generated yearly leaderboard with {len(df)} districts")
        if not df.empty:
            print(df.head(3).to_string(index=False))
    except Exception as e:
        print(f"Error: {e}")
    print()

    # Example 5: Test different custom periods
    print("📊 Example 5: Multiple Custom Periods")
    print("-" * 30)
    custom_periods = [
        (7, "Last 7 Days"),
        (30, "Last 30 Days"),
        (90, "Last 90 Days")
    ]

    for days, name in custom_periods:
        try:
            strategy = TimeWindowFactory.create_strategy('custom', days_back=days, name=name)
            df = await leaderboard_service.build_district_leaderboard(time_window_strategy=strategy)
            print(f"{name}: {len(df)} districts")
        except Exception as e:
            print(f"{name}: Error - {e}")

    print("\n✅ Strategy pattern demonstration completed!")


if __name__ == "__main__":
    asyncio.run(demonstrate_strategy_pattern())
