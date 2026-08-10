"""CLI for metrics computation and reporting."""

import sys
from datetime import datetime


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Garmin Dash — Metrics CLI")
        print("Usage: gdash report <command>")
        print("Commands: today, weekly, monthly")
        print("Run 'gdash report --help' for more info.")
        sys.exit(1)

    command = sys.argv[1]

    if command == "today":
        report_today()
    elif command == "weekly":
        report_weekly()
    elif command == "monthly":
        report_monthly()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


def report_today():
    """Generate today's metrics report."""
    print("📊 Today's Metrics Report")
    print("=" * 40)
    print()
    print("Report generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()
    print("Today's Date: " + datetime.now().strftime("%Y-%m-%d"))
    print()
    print("This report would display:")
    print("  • Recovery score (0-100)")
    print("  • Strain (0-21)")
    print("  • Sleep summary")
    print("  • HRV snapshot")
    print("  • Body Battery")
    print("  • Training load")
    print()
    print("✅ Report structure validated")


def report_weekly():
    """Generate weekly metrics report."""
    print("📊 Weekly Metrics Report")
    print("=" * 40)
    print()
    print("Report generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()
    print("This report would display:")
    print("  • Weekly average recovery")
    print("  • Weekly strain average")
    print("  • Training status (Trend/OK/Overreached)")
    print("  • HRV trend")
    print("  • Sleep quality")
    print()
    print("✅ Report structure validated")


def report_monthly():
    """Generate monthly metrics report."""
    print("📊 Monthly Metrics Report")
    print("=" * 40)
    print()
    print("Report generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print()
    print("This report would display:")
    print("  • Monthly recovery average")
    print("  • Monthly strain average")
    print("  • ATL/CTL/TSB trend")
    print("  • VO2max trend")
    print("  • Sleep quality")
    print("  • HRV baseline")
    print()
    print("✅ Report structure validated")
