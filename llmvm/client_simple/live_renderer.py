"""Live renderer using Rich Live display for proper streaming and formatting"""
import sys
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, List, Any

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.live import Live
from rich.panel import Panel
from .themes import create_rich_theme, get_syntax_theme, detect_terminal_background


class LiveRenderer:
    """Renderer that uses Rich Live display for clean streaming and formatting"""

    def __init__(self, config):
        self.config = config

        # Detect terminal theme and create Rich theme
        self.background = detect_terminal_background()
        self.theme = create_rich_theme(self.background)
        self.syntax_theme = get_syntax_theme(self.background)

        self.console = Console(theme=self.theme)

        # Response state
        self.live_display = None
        self.accumulated_text = ""
        self.accumulated_code = []
        self.accumulated_results = []
        self.in_helpers_block = False
        self.in_helpers_result_block = False

    def start_response(self):
        """Start a new response with Live display"""
        self.accumulated_text = ""
        self.accumulated_code = []
        self.accumulated_results = []
        self.in_helpers_block = False
        self.in_helpers_result_block = False

        # Create Live display that will update in place
        self.live_display = Live(
            Text("", style="dim"),
            refresh_per_second=30,
            console=self.console,
            transient=False  # Keep the display after exit
        )
        self.live_display.__enter__()

        if self.config.show_timestamps:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.console.print(f"[{timestamp}] ", style="dim", end="")

    def render_text(self, text: str):
        """Accumulate and stream text"""
        if not self.live_display:
            self.start_response()

        # Check for special blocks
        if "<helpers>" in text:
            self.in_helpers_block = True
        if "</helpers>" in text:
            self.in_helpers_block = False
            # Extract code between tags
            if "<helpers>" in self.accumulated_text and "</helpers>" in self.accumulated_text:
                start = self.accumulated_text.find("<helpers>") + len("<helpers>")
                end = self.accumulated_text.find("</helpers>")
                code = self.accumulated_text[start:end].strip()
                if code:
                    self.accumulated_code.append(code)

        if "<helpers_result>" in text:
            self.in_helpers_result_block = True
        if "</helpers_result>" in text:
            self.in_helpers_result_block = False
            # Extract result between tags
            if "<helpers_result>" in self.accumulated_text and "</helpers_result>" in self.accumulated_text:
                start = self.accumulated_text.find("<helpers_result>") + len("<helpers_result>")
                end = self.accumulated_text.find("</helpers_result>")
                result = self.accumulated_text[start:end].strip()
                if result:
                    self.accumulated_results.append(result)

        # Accumulate all text
        self.accumulated_text += text

        # Update live display with streaming text (dimmed)
        # Always stream when using Live display
        if self.live_display:
            display_text = self._clean_text_for_display(self.accumulated_text)
            self.live_display.update(Text(display_text, style="dim"))

    def render_code(self, code: str, language: Optional[str] = None):
        """Render code block"""
        if not self.live_display:
            self.start_response()

        # Add code to accumulated code blocks
        self.accumulated_code.append(code)

        # Update display
        if self.live_display:
            display_text = self._clean_text_for_display(self.accumulated_text)
            if code:
                display_text += f"\n```{language or 'python'}\n{code}\n```"
            self.live_display.update(Text(display_text, style="dim"))

    def render_image(self, image_data: bytes):
        """Open image in external viewer"""
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

            # Use custom viewer if specified
            if self.config.image_viewer:
                subprocess.run(self.config.image_viewer.split() + [temp_path])
            else:
                # Auto-detect system
                if sys.platform == "darwin":
                    subprocess.run(["open", temp_path])
                elif sys.platform.startswith("linux"):
                    if subprocess.run(["which", "xdg-open"], capture_output=True).returncode == 0:
                        subprocess.run(["xdg-open", temp_path])
                    else:
                        self.console.print(f"\n[No image viewer found. Image saved to: {temp_path}]")
                        return
                elif sys.platform == "win32":
                    subprocess.run(["start", "", temp_path], shell=True)

            # Add note about image in the stream
            self.accumulated_text += f"\n[Image opened: {temp_path}]\n"
            if self.live_display:
                display_text = self._clean_text_for_display(self.accumulated_text)
                self.live_display.update(Text(display_text, style="dim"))

        except Exception as e:
            self.console.print(f"\n[Error displaying image: {e}]\n", style="bold red")

    def render_error(self, error: str):
        """Render error message"""
        self.console.print(f"\n[Error: {error}]\n", style="bold red")

    def render_command_output(self, message: str):
        """Render slash command output without streaming"""
        # Direct output, no streaming needed
        self.console.print(Markdown(message))

    def finish_response(self):
        """Finish response and render final formatted output"""
        if not self.live_display:
            return

        try:
            # Build final formatted output
            renderables = []

            # Clean text and remove special tags
            clean_text = self._clean_text_for_display(self.accumulated_text)

            # Render main text as markdown
            if clean_text.strip():
                renderables.append(Markdown(clean_text.strip()))

            # Add code blocks if any
            for code in self.accumulated_code:
                if code.strip():
                    syntax = Syntax(
                        code.strip(),
                        "python",
                        theme=self.syntax_theme,
                        background_color="default",
                        word_wrap=True,
                        padding=0,
                    )
                    renderables.append(Panel(syntax, title="Code", border_style="blue"))

            # Add results if any
            for result in self.accumulated_results:
                if result.strip():
                    renderables.append(Panel(Text(result.strip()), title="Result", border_style="green"))

            # Update Live display with final formatted output
            if renderables:
                if len(renderables) == 1:
                    self.live_display.update(renderables[0])
                else:
                    self.live_display.update(Group(*renderables))

            # Exit Live context
            self.live_display.__exit__(None, None, None)
            self.live_display = None

            # Add newline for separation
            self.console.print()

        except Exception as e:
            self.config.debug_print(f"Error in finish_response: {e}")
            if self.live_display:
                self.live_display.__exit__(None, None, None)
                self.live_display = None

    def _clean_text_for_display(self, text: str) -> str:
        """Remove special tags from text for display"""
        clean = text

        # Remove helpers blocks
        while "<helpers>" in clean and "</helpers>" in clean:
            start = clean.find("<helpers>")
            end = clean.find("</helpers>") + len("</helpers>")
            clean = clean[:start] + clean[end:]

        # Remove helpers_result blocks
        while "<helpers_result>" in clean and "</helpers_result>" in clean:
            start = clean.find("<helpers_result>")
            end = clean.find("</helpers_result>") + len("</helpers_result>")
            clean = clean[:start] + clean[end:]

        # Remove any remaining tags
        clean = clean.replace("<helpers>", "").replace("</helpers>", "")
        clean = clean.replace("<helpers_result>", "").replace("</helpers_result>", "")
        clean = clean.replace("</complete>", "")

        return clean.strip()

    def show_welcome(self):
        """Show welcome message"""
        self.console.print("LLMVM Simple Client", style="bold blue")
        self.console.print("─" * 40)
        self.console.print(f"Server: {self.config.server_url}")
        self.console.print(f"Mode: {self.config.mode}")
        self.console.print(f"Model: {self.config.executor}/{self.config.model}")
        self.console.print("─" * 40)
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
        if self.live_display:
            self.live_display.__exit__(None, None, None)
            self.live_display = None