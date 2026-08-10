"""CLI entry point for the Garmin Dash application."""

from .settings import get_settings


def main():
    """CLI entry point."""
    import sys
    from .auth import cli as auth_cli
    from .ingestion import cli as ingestion_cli
    from .metrics import cli as metrics_cli

    if len(sys.argv) < 2:
        print("Garmin Dash CLI")
        print("Usage: gdash <command>")
        print("Commands: auth, ingest, report")
        print("Run 'gdash --help' for more info.")
        sys.exit(1)

    command = sys.argv[1]

    if command == "auth":
        auth_cli()
    elif command == "ingest":
        ingestion_cli()
    elif command == "report":
        metrics_cli()
    else:
        print(f"Unknown command: {command}")
        print("Run 'gdash --help' for available commands.")
        sys.exit(1)


if __name__ == "__main__":
    main()
