"""Configuration for simple client"""
import os
from pathlib import Path


class Config:
    def __init__(self):
        # Server connection
        self.server_url = os.environ.get(
            "LLMVM_ENDPOINT",
            f"http://localhost:{os.environ.get('LLMVM_SERVER_PORT', '8011')}"
        )

        # Client behavior
        self.history_file = os.path.expanduser(
            os.environ.get("LLMVM_SIMPLE_HISTORY", "~/.llmvm_simple_history")
        )

        # Timeouts
        self.server_timeout = None  # No timeout by default
        if os.environ.get("LLMVM_SIMPLE_TIMEOUT"):
            self.server_timeout = float(os.environ["LLMVM_SIMPLE_TIMEOUT"])

        # Display settings
        self.show_timestamps = os.environ.get(
            "LLMVM_SIMPLE_TIMESTAMPS", "false"
        ).lower() == "true"

        self.use_colors = os.environ.get(
            "LLMVM_SIMPLE_COLORS", "true"
        ).lower() == "true"

        self.debug = os.environ.get(
            "LLMVM_SIMPLE_DEBUG", "false"
        ).lower() == "true"

        # Streaming settings
        self.disable_streaming = os.environ.get(
            "LLMVM_SIMPLE_NO_STREAM", "false"
        ).lower() == "true"

        # Image viewer (auto-detect if not specified)
        self.image_viewer = os.environ.get("LLMVM_SIMPLE_VIEWER")

        # Exit behavior
        self.exit_confirmation_timeout = 3  # seconds
        self.double_ctrl_d_window = 0.5     # seconds

        # Client logging
        self.logs_dir = os.path.join(os.getcwd(), "logs")
        os.makedirs(self.logs_dir, exist_ok=True)
        self.client_log_file = os.path.join(self.logs_dir, "client.log")

        # Mode and model (for display purposes)
        self.mode = os.environ.get("LLMVM_MODE", "tools")
        self.executor = os.environ.get("LLMVM_EXECUTOR", "anthropic")

        # Set proper default model based on executor
        if self.executor == "openai":
            default_model = "gpt-4o"
        elif self.executor == "anthropic":
            default_model = "claude-3-5-sonnet-20241022"
        else:
            default_model = "default"

        self.model = os.environ.get("LLMVM_MODEL", default_model)

    @classmethod
    def from_env(cls):
        """Create config from environment"""
        return cls()

    def debug_print(self, message: str):
        """Print debug message if debug mode enabled"""
        if self.debug:
            print(f"[DEBUG] {message}")
        self.log_to_file(f"[DEBUG] {message}")

    def log_to_file(self, message: str):
        """Log message to client log file"""
        try:
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(self.client_log_file, "a") as f:
                f.write(f"[{timestamp}] {message}\n")
        except Exception:
            # Ignore logging errors
            pass