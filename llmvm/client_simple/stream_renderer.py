"""Raw stream renderer that displays content without formatting"""
import sys
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from rich.console import Console


class StreamRenderer:
    """Raw stream renderer that displays content as-is without formatting"""

    def __init__(self, config):
        self.config = config
        self.console = Console(width=120)
        self.buffer = ""
        self.response_started = False

    def start_response(self):
        """Start a new response"""
        self.buffer = ""
        self.response_started = True

        if self.config.show_timestamps:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.console.print(f"[{timestamp}] ", style="dim", end="")

        # Response started - no markers needed

    def render_text(self, text: str):
        """Process incoming text - just print it raw with minimal filtering"""
        if not self.response_started:
            self.start_response()

        # Only skip completely empty chunks or single whitespace characters
        if text and not (len(text) == 1 and text in ' \n\t\r'):
            self.console.print(text, end="")
            self.buffer += text

    def render_code(self, code: str, language: Optional[str] = None):
        """Handle explicit code blocks - just print them"""
        if code.strip():
            self.console.print("\n[CODE BLOCK]")
            self.console.print(code)
            self.console.print("[END CODE BLOCK]\n")

    def render_image(self, image_data: bytes):
        """Open image in external viewer and add note"""
        try:
            # Detect image type
            suffix = '.png'
            if image_data[:3] == b'\xff\xd8\xff':
                suffix = '.jpg'
            elif image_data[:4] == b'RIFF':
                suffix = '.webp'

            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(image_data)
                temp_path = f.name

            # Use system viewer
            if sys.platform == "darwin":
                subprocess.run(["open", temp_path])
            elif sys.platform.startswith("linux"):
                subprocess.run(["xdg-open", temp_path])
            elif sys.platform == "win32":
                subprocess.run(["start", "", temp_path], shell=True)

            self.console.print(f"\n[Image opened: {temp_path}]\n")

        except Exception as e:
            self.render_error(str(e))

    def render_error(self, error: str):
        """Render error message"""
        self.console.print(f"\n[Error: {error}]\n", style="bold red")

    def render_command_output(self, message: str):
        """Render slash command output"""
        self.console.print("\n[Command Output]")
        self.console.print(message)
        self.console.print("[End Command Output]\n")

    def finish_response(self):
        """Finish response and clean up"""
        if not self.response_started:
            return

        # Response finished - add simple separator
        self.console.print("\n")

        self.response_started = False
        self.buffer = ""

    def show_welcome(self):
        """Show welcome message"""
        self.console.print("LLMVM Stream Client (Raw Mode)", style="bold blue")
        self.console.print("─" * 40)
        self.console.print(f"Server: {self.config.server_url}")
        self.console.print(f"Mode: {self.config.mode}")
        self.console.print(f"Model: {self.config.executor}/{self.config.model}")
        self.console.print("─" * 40)
        self.console.print("• Raw streaming mode - no formatting")
        self.console.print("• ESC to interrupt streaming")
        self.console.print("• Ctrl-D to delete character (or exit on empty prompt)")
        self.console.print("• Type 'exit' to quit")
        self.console.print()

    def show_goodbye(self):
        """Show exit message"""
        self.console.print("\nGoodbye!")

    def show_interrupt_hint(self):
        """Show hint after Ctrl-C"""
        self.console.print("\n(Use Ctrl-D or type 'exit' to quit)", style="dim")

    def show_interrupted(self):
        """Show message when stream interrupted"""
        self.console.print("\n[Interrupted]", style="yellow")

    def show_message(self, message: str, style: str = "default"):
        """Show a temporary message with optional styling"""
        self.console.print(f"\n{message}", style=style)

