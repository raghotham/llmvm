"""Entry point for simple client"""
import sys
from .client import SimpleClient


def main():
    """Main entry point"""
    try:
        client = SimpleClient()
        return client.run()
    except KeyboardInterrupt:
        print("\nExiting...")
        return 0
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())