#!/usr/bin/env python3
"""
LLMVM CLI - Unified command-line interface for LLMVM
Starts both server and client similar to Claude Code
"""

import argparse
import atexit
import os
import signal
import subprocess
import sys
import time
import requests
from pathlib import Path
from typing import Optional

# Colors for terminal output
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

def log_info(message: str) -> None:
    print(f"{Colors.BLUE}[INFO]{Colors.NC} {message}")

def log_success(message: str) -> None:
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {message}")

def log_warning(message: str) -> None:
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {message}")

def log_error(message: str) -> None:
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}")

class LLMVMManager:
    def __init__(self, port: int = 8011, log_level: str = "INFO", logs_dir: Optional[Path] = None):
        self.port = port
        self.log_level = log_level
        self.server_process: Optional[subprocess.Popen] = None

        # Use provided logs directory (already resolved by caller)
        if logs_dir:
            self.logs_dir = Path(logs_dir).resolve()  # Make absolute
        else:
            self.logs_dir = (Path.cwd() / "logs").resolve()  # Make absolute

        self.logs_dir.mkdir(exist_ok=True)

        # For server execution, use the actual project root where llmvm package is
        self.project_root = Path(__file__).parent.parent

        self.log_file = self.logs_dir / "llmvm-server.log"
        self.pid_file = self.logs_dir / "llmvm-server.pid"

        # Always register cleanup - server lifetime tied to client
        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        log_info("Received shutdown signal, cleaning up...")
        self.cleanup()
        sys.exit(0)

    def is_server_running(self) -> bool:
        """Check if server is already running"""
        if self.pid_file.exists():
            try:
                with open(self.pid_file, 'r') as f:
                    pid = int(f.read().strip())
                # Check if process is still running
                os.kill(pid, 0)
                return True
            except (OSError, ValueError):
                # Process is dead or PID file is invalid
                self.pid_file.unlink(missing_ok=True)
                return False
        return False

    def wait_for_server_ready(self, timeout: int = 30) -> bool:
        """Wait for server to be ready by checking health endpoint"""
        log_info("Waiting for server to be ready...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to connect to the health endpoint
                response = requests.get(f"http://localhost:{self.port}/health", timeout=2)
                if response.status_code == 200:
                    try:
                        health_data = response.json()
                        if health_data.get("status") == "healthy":
                            log_success("Server is ready!")
                            return True
                    except:
                        # If JSON parsing fails but got 200, still consider it ready
                        log_success("Server is ready!")
                        return True
                elif response.status_code == 503:
                    # Server responded but not healthy - check if it's a permanent failure
                    try:
                        health_data = response.json()
                        reason = health_data.get("reason", "unknown")
                        missing_helpers = health_data.get("missing_helpers", [])

                        # If we've been waiting for a while and still have missing helpers, fail
                        elapsed = time.time() - start_time
                        if missing_helpers and elapsed > 10:  # Give 10 seconds for helpers to load
                            log_error("Server startup failed due to missing helpers:")
                            for helper in missing_helpers:
                                log_error(f"  - {helper}")
                            log_error(f"Full server logs available at: {self.log_file}")
                            return False

                        # Still starting up, show progress
                        if missing_helpers:
                            log_info(f"Server starting up... ({reason})")
                            if len(missing_helpers) <= 3:
                                log_info(f"Missing helpers: {', '.join(missing_helpers)}")
                        else:
                            log_info(f"Server starting up... ({reason})")
                    except:
                        log_info("Server starting up...")
                # Continue waiting for any other status codes
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                # Server not ready yet, keep waiting
                pass

            time.sleep(0.5)  # Check every 500ms

        log_error(f"Server did not become ready within {timeout} seconds")
        log_error("Server startup failed. Here are the last few lines from the server log:")
        print()
        self._show_recent_logs(lines=15)
        print()
        log_error(f"Full server logs available at: {self.log_file}")
        return False

    def start_server(self) -> bool:
        """Start the LLMVM server"""
        if self.is_server_running():
            log_error("LLMVM server is already running on this port")
            log_error("Please stop the existing server first or use a different port")
            log_error("You can check server status with: uv run llmvm --status")
            log_error("You can stop the server with: uv run llmvm --stop")
            return False

        log_info(f"Starting LLMVM server on port {self.port}...")

        # Start server process
        try:
            # Open log file using absolute path
            log_f = open(self.log_file, 'w')

            server_process = subprocess.Popen(
                [
                    sys.executable, "-m", "llmvm.server.server",
                    "--port", str(self.port),
                    "--log-level", self.log_level
                ],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                cwd=str(self.project_root),  # Ensure it's a string
                start_new_session=True
            )

            # Write PID file
            with open(self.pid_file, 'w') as pid_f:
                pid_f.write(str(server_process.pid))

            # Wait a moment and check if server started successfully
            time.sleep(2)
            if server_process.poll() is None:
                log_success(f"Server started successfully (PID: {server_process.pid})")
                log_info(f"Server logs: {self.log_file}")

                # Always keep reference to manage server lifetime
                self.server_process = server_process

                return True
            else:
                log_error("Server failed to start. Check logs for details.")
                self._show_recent_logs()
                log_f.close()
                return False

        except Exception as e:
            log_error(f"Failed to start server: {e}")
            return False

    def stop_server(self) -> None:
        """Stop the LLMVM server"""
        if not self.is_server_running():
            log_warning("Server is not running")
            return

        try:
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())

            log_info(f"Stopping LLMVM server (PID: {pid})...")

            # Try graceful shutdown first
            os.kill(pid, signal.SIGTERM)

            # Wait for graceful shutdown
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(1)
                except OSError:
                    break
            else:
                # Force kill if graceful shutdown failed
                log_warning("Server didn't stop gracefully, forcing shutdown...")
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

            self.pid_file.unlink(missing_ok=True)
            log_success("Server stopped")

        except (OSError, ValueError) as e:
            log_error(f"Error stopping server: {e}")
            self.pid_file.unlink(missing_ok=True)

    def show_status(self) -> None:
        """Show server status"""
        if self.is_server_running():
            with open(self.pid_file, 'r') as f:
                pid = int(f.read().strip())
            log_success(f"Server is running (PID: {pid}) on port {self.port}")
        else:
            log_warning("Server is not running")

    def _show_recent_logs(self, lines: int = 20) -> None:
        """Show recent log entries"""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r') as f:
                    all_lines = f.readlines()
                    recent_lines = all_lines[-lines:]
                    print("=== Recent Server Logs ===")
                    for line in recent_lines:
                        print(line.rstrip())
            except Exception as e:
                log_error(f"Could not read log file: {e}")
        else:
            log_warning(f"No log file found at {self.log_file}")

    def show_logs(self, lines: int = 50) -> None:
        """Show server logs"""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r') as f:
                    all_lines = f.readlines()
                    recent_lines = all_lines[-lines:]
                    print("=== LLMVM Server Logs ===")
                    for line in recent_lines:
                        print(line.rstrip())
            except Exception as e:
                log_error(f"Could not read log file: {e}")
        else:
            log_warning(f"No log file found at {self.log_file}")

    def start_client(self, client_args: list) -> None:
        """Start the LLMVM client"""
        log_info("Starting LLMVM client...")

        try:
            # Run client as subprocess to preserve CLI wrapper for cleanup
            cmd = [sys.executable, "-m", "llmvm.client.cli"] + client_args
            # Inherit stdin/stdout/stderr to preserve terminal behavior
            subprocess.run(cmd, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)

        except KeyboardInterrupt:
            log_info("Client interrupted by user")
        except Exception as e:
            log_error(f"Error starting client: {e}")
        finally:
            # Always cleanup server when client exits (for any reason)
            log_info("Client exited, shutting down server...")
            self.cleanup()

    def check_api_keys(self) -> bool:
        """Check if at least one API key is set"""
        api_keys = [
            'OPENAI_API_KEY',
            'ANTHROPIC_API_KEY',
            'GEMINI_API_KEY',
            'BEDROCK_API_KEY',
            'DEEPSEEK_API_KEY',
            'LLAMA_API_KEY'
        ]

        for key in api_keys:
            if os.getenv(key):
                return True

        log_error("No API keys found in environment variables.")
        log_error("Please set at least one of the following environment variables:")
        for key in api_keys:
            log_error(f"  - {key}")
        log_error("")
        log_error("Example: export ANTHROPIC_API_KEY=your_api_key_here")
        return False

    def cleanup(self) -> None:
        """Cleanup on exit - always shutdown server when client exits"""
        if self.server_process and self.server_process.poll() is None:
            log_info("Shutting down server...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()

            # Clean up PID file
            self.pid_file.unlink(missing_ok=True)

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="LLMVM - Unified CLI tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run llmvm                 # Start server and client (server stops when client exits)
  uv run llmvm --status        # Show server status
  uv run llmvm --logs          # Show server logs

Environment variables:
  LLMVM_SERVER_PORT       Override default server port (default: 8011)
  LLMVM_LOG_LEVEL         Override default log level (default: INFO)
  LLMVM_LOGS_DIR          Override default logs directory (default: ./logs)
        """
    )

    parser.add_argument(
        "-p", "--port",
        type=int,
        default=int(os.getenv("LLMVM_SERVER_PORT", "8011")),
        help="Server port (default: 8011)"
    )

    parser.add_argument(
        "-l", "--log-level",
        default=os.getenv("LLMVM_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)"
    )

    parser.add_argument(
        "--logs-dir",
        default=os.getenv("LLMVM_LOGS_DIR"),
        help="Directory for log files (default: ./logs)"
    )


    parser.add_argument(
        "--status",
        action="store_true",
        help="Show server status"
    )

    parser.add_argument(
        "--logs",
        action="store_true",
        help="Show server logs"
    )

    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the server"
    )

    # Parse known args to allow passing remaining args to client
    args, client_args = parser.parse_known_args()

    # Handle logs directory - if relative path, make it relative to original working directory
    if args.logs_dir:
        if not os.path.isabs(args.logs_dir):
            # Relative path - make it relative to where user called uvx from
            logs_dir = Path.cwd() / args.logs_dir
        else:
            # Absolute path - use as-is
            logs_dir = Path(args.logs_dir)
    else:
        # Default: ./logs in user's working directory
        logs_dir = Path.cwd() / "logs"

    manager = LLMVMManager(port=args.port, log_level=args.log_level, logs_dir=logs_dir)

    # Handle special commands
    if args.status:
        manager.show_status()
        return

    if args.logs:
        manager.show_logs()
        return

    if args.stop:
        manager.stop_server()
        return

    # Main mode: start server and client with tied lifetimes
    log_info("Starting LLMVM (server + client)")

    # Check API keys before starting server
    if not manager.check_api_keys():
        sys.exit(1)

    if not manager.start_server():
        sys.exit(1)

    # Wait for server to be ready before starting client
    if not manager.wait_for_server_ready():
        sys.exit(1)

    # Start client (this will block until client exits)
    # When client exits, cleanup will automatically stop the server
    manager.start_client(client_args)

if __name__ == "__main__":
    main()