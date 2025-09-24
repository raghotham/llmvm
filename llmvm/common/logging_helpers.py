import datetime as dt
import json
import logging
import os
import sys
import time
from logging import Logger
from typing import Any, Dict, List

import rich

from llmvm.common.container import Container
from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install


def detect_terminal_background():
    """Detect if terminal has dark or light background"""
    # Check for forced theme first
    forced_theme = os.environ.get("LLMVM_FORCE_THEME", "").lower()
    if forced_theme in ("light", "dark"):
        return forced_theme

    # Try to detect terminal background using various methods

    # Method 1: Check COLORFGBG environment variable (common in many terminals)
    colorfgbg = os.environ.get("COLORFGBG", "")
    if colorfgbg:
        # Format is usually "foreground;background" where higher numbers = lighter
        parts = colorfgbg.split(";")
        if len(parts) >= 2:
            try:
                bg = int(parts[-1])
                # In COLORFGBG, 0-7 are typically dark backgrounds, 8-15 are light
                return "light" if bg >= 8 else "dark"
            except ValueError:
                pass

    # Method 2: Apple Terminal - use AppleScript to get actual background color
    term_program = os.environ.get("TERM_PROGRAM", "")
    if term_program == "Apple_Terminal":
        try:
            import subprocess

            script = 'tell application "Terminal" to get background color of selected tab of window 1'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=True,
                timeout=2,
            )
            # Parse RGB values (16-bit format: 0-65535)
            colors = result.stdout.strip().split(", ")
            if len(colors) == 3:
                r, g, b = [int(c) for c in colors]
                # Calculate luminance using relative luminance formula
                # Convert to 0-1 range and apply gamma correction
                r_norm = (r / 65535) ** 2.2
                g_norm = (g / 65535) ** 2.2
                b_norm = (b / 65535) ** 2.2
                luminance = 0.2126 * r_norm + 0.7152 * g_norm + 0.0722 * b_norm
                # If luminance > 0.5, it's a light background
                return "light" if luminance > 0.5 else "dark"
        except Exception:
            # Fall back to other methods if AppleScript fails
            pass

    # Method 3: Check terminal program names that typically default to light/dark
    if "iterm" in term_program.lower():
        # iTerm2 usually defaults to dark, but we can't know for sure
        return "dark"

    # Method 4: Check if running in VS Code terminal (often light)
    if (
        os.environ.get("VSCODE_INJECTION")
        or "code" in os.environ.get("TERM_PROGRAM", "").lower()
    ):
        return "light"

    # Default to dark theme (most terminals default to dark)
    return "dark"


def get_theme_colors():
    """Get color scheme based on terminal background"""
    theme = detect_terminal_background()

    if theme == "light":
        return {
            "client_stream_token_color": "dim",  # Dark gray for light backgrounds
            "client_stream_thinking_token_color": "blue",  # Blue for light backgrounds
            "client_role_color": "bold blue",  # Blue instead of cyan
            "client_repl_color": "blue",  # Blue instead of bright cyan
            "client_assistant_color": "default",  # Default text for better compatibility
            "client_info_color": "blue",  # Blue for info text
            "client_info_bold_color": "bold blue",  # Bold blue for emphasis
        }
    else:
        return {
            "client_stream_token_color": "dim",  # Light gray for dark backgrounds
            "client_stream_thinking_token_color": "gray",  # Original blue-gray
            "client_role_color": "bold bright_blue",  # Bright blue instead of cyan
            "client_repl_color": "ansibrightblue",  # Bright blue instead of bright cyan
            "client_assistant_color": "default",  # Default text for better compatibility
            "client_info_color": "bold green",  # Green for info text
            "client_info_bold_color": "bright_blue",  # Bright blue for emphasis
        }


def detect_terminal_background():
    """Detect if terminal has dark or light background"""
    # Check for forced theme first
    forced_theme = os.environ.get('LLMVM_FORCE_THEME', '').lower()
    if forced_theme in ('light', 'dark'):
        return forced_theme

    # Try to detect terminal background using various methods

    # Method 1: Check COLORFGBG environment variable (common in many terminals)
    colorfgbg = os.environ.get('COLORFGBG', '')
    if colorfgbg:
        # Format is usually "foreground;background" where higher numbers = lighter
        parts = colorfgbg.split(';')
        if len(parts) >= 2:
            try:
                bg = int(parts[-1])
                # In COLORFGBG, 0-7 are typically dark backgrounds, 8-15 are light
                return 'light' if bg >= 8 else 'dark'
            except ValueError:
                pass

    # Method 2: Apple Terminal - use AppleScript to get actual background color
    term_program = os.environ.get('TERM_PROGRAM', '')
    if term_program == 'Apple_Terminal':
        try:
            import subprocess
            script = 'tell application "Terminal" to get background color of selected tab of window 1'
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                check=True,
                timeout=2
            )
            # Parse RGB values (16-bit format: 0-65535)
            colors = result.stdout.strip().split(', ')
            if len(colors) == 3:
                r, g, b = [int(c) for c in colors]
                # Calculate luminance using relative luminance formula
                # Convert to 0-1 range and apply gamma correction
                r_norm = (r / 65535) ** 2.2
                g_norm = (g / 65535) ** 2.2
                b_norm = (b / 65535) ** 2.2
                luminance = 0.2126 * r_norm + 0.7152 * g_norm + 0.0722 * b_norm
                # If luminance > 0.5, it's a light background
                return 'light' if luminance > 0.5 else 'dark'
        except Exception:
            # Fall back to other methods if AppleScript fails
            pass

    # Method 3: Check terminal program names that typically default to light/dark
    if 'iterm' in term_program.lower():
        # iTerm2 usually defaults to dark, but we can't know for sure
        return 'dark'

    # Method 4: Check if running in VS Code terminal (often light)
    if os.environ.get('VSCODE_INJECTION') or 'code' in os.environ.get('TERM_PROGRAM', '').lower():
        return 'light'

    # Default to dark theme (most terminals default to dark)
    return 'dark'


def get_theme_colors():
    """Get color scheme based on terminal background"""
    theme = detect_terminal_background()

    if theme == 'light':
        return {
            'client_stream_token_color': '#333333',      # Dark gray for light backgrounds
            'client_stream_thinking_token_color': '#0066cc',  # Blue for light backgrounds
            'client_role_color': 'bold blue',            # Blue instead of cyan
            'client_repl_color': 'blue',                 # Blue instead of bright cyan
            'client_assistant_color': 'black',          # Black text for light backgrounds
            'client_info_color': 'blue',                # Blue for info text
            'client_info_bold_color': 'bold blue'       # Bold blue for emphasis
        }
    else:
        return {
            'client_stream_token_color': '#dddddd',      # Light gray for dark backgrounds
            'client_stream_thinking_token_color': '#5f819d',  # Original blue-gray
            'client_role_color': 'bold cyan',            # Original cyan
            'client_repl_color': 'ansibrightcyan',      # Original bright cyan
            'client_assistant_color': 'white',          # White text for dark backgrounds
            'client_info_color': 'bold green',          # Green for info text
            'client_info_bold_color': 'cyan'            # Cyan for emphasis
        }




def __trace(content):
    try:
        if Container.get_config_variable("LLMVM_EXECUTOR_TRACE", default=""):
            with open(
                os.path.expanduser(
                    Container.get_config_variable("LLMVM_EXECUTOR_TRACE")
                ),
                "a+",
            ) as f:
                f.write(content)
    except Exception as e:
        rich.print(f"Error tracing: {e}")


def messages_trace(messages: List[Dict[str, Any]]):
    if Container.get_config_variable("LLMVM_EXECUTOR_TRACE", default=""):
        for m in messages:
            if "content" in m:
                __trace(
                    f"<{m['role'].capitalize()}:>{m['content']}</{m['role'].capitalize()}>\n\n"
                )
            elif (
                "parts" in m
                and isinstance(m["parts"], list)
                and isinstance(m["parts"][0], dict)
                and "inline_data" in m["parts"][0]
            ):
                # ImageContent todo fix properly
                __trace(
                    f"<{m['role'].capitalize()}:>[ImageContent()]</{m['role'].capitalize()}>\n\n"
                )
            elif "parts" in m:
                content = " ".join(m["parts"])
                __trace(
                    f"<{m['role'].capitalize()}:>{content}</{m['role'].capitalize()}>\n\n"
                )


def serialize_messages(messages):
    if Container.get_config_variable("LLMVM_SERIALIZE", default=""):
        result = json.dumps([m.to_json() for m in messages], indent=2)
        file_path = os.path.expanduser(Container.get_config_variable("LLMVM_SERIALIZE"))
        with open(file_path, "a+") as f:
            f.write(result + "\n\n")
            f.flush()


class TimedLogger(logging.Logger):
    def __init__(self, name="timing", level=logging.NOTSET):
        super().__init__(name, level)
        self._start_time = None
        self._intermediate_timings = {}
        self._prepend = ""

    def start(self, prepend=""):
        self._start_time = time.time()
        self._intermediate_timings.clear()  # Clear previous intermediate timings
        self._prepend = prepend

    def save_intermediate(self, label):
        if self._start_time is None:
            self.warning("Timer was not started!")
            return

        if label in self._intermediate_timings:
            return

        current_time = time.time()
        elapsed_time = (
            current_time - self._start_time
        ) * 1000  # Convert to milliseconds
        self._intermediate_timings[label] = elapsed_time
        self.debug(f"'{label}' timing: {elapsed_time:.2f} ms {self._prepend}")

    def end(self, message="Elapsed time"):
        if self._start_time is None:
            self.warning("Timer was not started!")
            return
        elapsed_time = (
            time.time() - self._start_time
        ) * 1000  # Convert to milliseconds
        self.debug(f"{message}: {elapsed_time:.2f} ms {self._prepend}")
        # Optionally, log intermediate timings at the end
        for label, timing in self._intermediate_timings.items():
            self.debug(f"'{label}' timing: {timing:.2f} ms {self._prepend}")
        self._start_time = None
        self._intermediate_timings.clear()


timing = TimedLogger()
global_loggers: Dict[str, Logger] = {}
handler = RichHandler()

if not os.path.exists(
    Container.get_config_variable("log_directory", default="~/.local/share/llmvm/logs")
):
    os.makedirs(
        Container.get_config_variable(
            "log_directory", default="~/.local/share/llmvm/logs"
        )
    )


def no_indent_debug(logger, message) -> None:
    if logger.level <= logging.DEBUG:
        console = Console(file=sys.stderr)
        console.print(message)


def role_debug(logger, callee, role, message) -> None:
    def split_string_by_width(input_string, width=20):
        result = ""
        width_counter = 0

        for i in range(0, len(input_string)):
            if width_counter >= width:
                width_counter = 0
                result += "\n"

            if input_string[i] == "\n":
                result += input_string[i]
                width_counter = 0
            elif width_counter < width:
                result += input_string[i]
                width_counter += 1
        return result.split("\n")

    if logger.level <= logging.DEBUG:
        if callee.startswith("prompts/"):
            callee = callee.replace("prompts/", "")

        console = Console(file=sys.stderr)
        width, _ = console.size
        callee_column = 20
        role_column = 10
        text_column = width - callee_column - role_column - 4

        # message_lines = message.split('\n')
        message_lines = split_string_by_width(message, width=text_column)
        header = True
        counter = 1
        max_lines = 20
        try:
            for message in message_lines:
                if header:
                    console.print(
                        "[orange]{}[/orange][green]{}[/green][grey]{}[/grey]".format(
                            callee[0 : callee_column - 1].ljust(callee_column)[
                                :callee_column
                            ],
                            role.ljust(role_column)[:role_column],
                            message.ljust(text_column)[:text_column],
                        )
                    )
                    header = False
                elif counter < max_lines or counter >= len(message_lines) - 5:
                    console.print(
                        "{}{}{}".format(
                            "".ljust(callee_column),
                            "".ljust(role_column),
                            message.ljust(text_column)[:text_column],
                        )
                    )
                elif counter == max_lines:
                    console.print(
                        "{}{}{}".format(
                            "".ljust(callee_column), "".ljust(role_column), "..."
                        )
                    )
                counter += 1
        except Exception as _:
            pass


def setup_logging(
    module_name="root",
    default_level=logging.DEBUG,
    enable_timing=False,
):
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("markdown_it").setLevel(logging.WARNING)
    logging.getLogger("numexpr").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("pdfminer").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("parso.python.diff").disabled = True
    logging.getLogger("parso").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.CRITICAL)
    logging.getLogger("PIL").setLevel(logging.CRITICAL)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("grpc").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
    logging.getLogger("dateparser").setLevel(logging.CRITICAL)
    logging.getLogger("tesseract").setLevel(logging.CRITICAL)
    logging.getLogger("pytesseract").setLevel(logging.CRITICAL)
    logging.getLogger("tzlocal").setLevel(logging.CRITICAL)
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.CRITICAL)
    logging.getLogger("transformers.utils.import_utils").setLevel(logging.ERROR)

    logger: Logger = logging.getLogger()

    handlers_to_remove = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    for handler in handlers_to_remove:
        logger.removeHandler(handler)

    if module_name in global_loggers:
        return global_loggers[module_name]

    install(show_locals=False, max_frames=20, suppress=["importlib, site-packages"])
    handler = RichHandler(
        console=Console(file=sys.stderr),
        show_time=True,
        show_level=True,
        show_path=False,
    )
    handler.setLevel(default_level)

    # Set a format that includes timestamps
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s    %(message)s", datefmt="%m/%d/%y %H:%M:%S"
    )

    logger.setLevel(default_level)
    logger.addHandler(handler)

    if enable_timing:
        handlers_to_remove = [
            h for h in timing.handlers if isinstance(handler, logging.StreamHandler)
        ]
        for h in handlers_to_remove:
            timing.removeHandler(h)

        timing.setLevel(default_level)
        timing.addHandler(handler)
    else:
        timing.setLevel(logging.CRITICAL)

    global_loggers[module_name] = logger
    return logger


def suppress_logging():
    logging.getLogger().setLevel(logging.CRITICAL)
    logging.getLogger("root").setLevel(logging.CRITICAL)
    logging.getLogger("asyncio").setLevel(logging.CRITICAL)
    logging.getLogger("markdown_it").setLevel(logging.CRITICAL)
    logging.getLogger("numexpr").setLevel(logging.CRITICAL)
    logging.getLogger("rich").setLevel(logging.CRITICAL)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    logging.getLogger("PIL.PngImagePlugin").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)
    logging.getLogger("grpc").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("matplotlib.font_manager").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.CRITICAL)


def get_timer():
    return timing


def disable_timing(name="timing"):
    timing.setLevel(logging.DEBUG)


def response_writer(callee, message):
    with open(f"{Container().get('log_directory')}/ast.log", "a") as f:
        f.write(f"{str(dt.datetime.now())} {callee}: {message}\n")
