"""Entry point for pane client"""
import sys
from .client import PaneClient


def main():
    """Main entry point"""
    try:
        client = PaneClient()
        return client.run()
    except KeyboardInterrupt:
        print("\nExiting...")
        return 0
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())