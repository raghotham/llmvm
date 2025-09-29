"""Two-pane renderer with live streaming in one window and persistent input in another"""
import sys
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from prompt_toolkit.application import Application
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys


class PaneRenderer:
    """Two-pane renderer with streaming content above and input below"""

    def __init__(self, config):
        self.config = config
        self.buffer = ""
        self.response_started = False

        # Content area - scrollable streaming output
        self.content_lines = []
        self.content_control = FormattedTextControl(text="")
        self.content_area = Window(
            content=self.content_control,
            wrap_lines=True
        )

        # Input area - persistent prompt at bottom
        self.input_area = TextArea(
            prompt=">> ",
            multiline=False,
            wrap_lines=False
        )

        # Two-pane layout: content area above, input area below
        self.layout = Layout(
            HSplit([
                self.content_area,  # Takes most space
                Window(height=Dimension.exact(3), content=self.input_area.control)  # Fixed height input
            ])
        )

        # Key bindings
        self.key_bindings = self._create_keybindings()

        # Application
        self.app = Application(
            layout=self.layout,
            key_bindings=self.key_bindings,
            full_screen=True,
            mouse_support=False
        )

    def _create_keybindings(self):
        """Create key bindings for the pane interface"""
        kb = KeyBindings()

        @kb.add(Keys.Escape)
        def _(event):
            """ESC to interrupt streaming or clear input"""
            if self.input_area.text:
                self.input_area.text = ""
                self.add_content("\n🧹 Input cleared\n")
            else:
                self.add_content("\n⏹️ ESC pressed\n")

        @kb.add(Keys.ControlC)
        def _(event):
            """Ctrl-C to exit"""
            event.app.exit()

        @kb.add(Keys.ControlD)
        def _(event):
            """Ctrl-D to delete char or exit"""
            if self.input_area.text:
                # Delete character at cursor
                if self.input_area.document.cursor_position < len(self.input_area.text):
                    current_text = self.input_area.text
                    cursor_pos = self.input_area.document.cursor_position
                    self.input_area.text = current_text[:cursor_pos] + current_text[cursor_pos+1:]
            else:
                # Exit on empty input
                event.app.exit()

        @kb.add(Keys.Enter)
        def _(event):
            """Enter to submit input"""
            text = self.input_area.text.strip()
            if text:
                # Add user input to content area
                self.add_content(f"\n[You] {text}\n")

                # Handle special commands
                if text.lower() == "exit":
                    event.app.exit()
                elif text.lower() == "clear":
                    self.clear_content()
                else:
                    # This would normally send to server
                    self.add_content(f"[Echo] You said: {text}\n")

                # Clear input
                self.input_area.text = ""

        return kb

    def add_content(self, text: str):
        """Add content to the streaming area"""
        self.content_lines.append(text)
        self._update_display()

    def clear_content(self):
        """Clear the content area"""
        self.content_lines = []
        self._update_display()

    def _update_display(self):
        """Update the content display"""
        full_text = "".join(self.content_lines)
        self.content_control.text = FormattedText([("", full_text)])
        self.app.invalidate()

    def start_response(self):
        """Start a new response"""
        self.buffer = ""
        self.response_started = True

        if self.config.show_timestamps:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.add_content(f"[{timestamp}] ")

    def render_text(self, text: str):
        """Process incoming text - add to content area"""
        if not self.response_started:
            self.start_response()

        # Only skip completely empty chunks or single whitespace characters
        if text and not (len(text) == 1 and text in ' \n\t\r'):
            self.add_content(text)
            self.buffer += text

    def render_code(self, code: str, language: Optional[str] = None):
        """Handle explicit code blocks"""
        if code.strip():
            self.add_content(f"\n[CODE BLOCK]\n{code}\n[END CODE BLOCK]\n")

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

            self.add_content(f"\n[Image opened: {temp_path}]\n")

        except Exception as e:
            self.render_error(str(e))

    def render_error(self, error: str):
        """Render error message"""
        self.add_content(f"\n[Error: {error}]\n")

    def render_command_output(self, message: str):
        """Render slash command output"""
        self.add_content(f"\n[Command Output]\n{message}\n[End Command Output]\n")

    def finish_response(self):
        """Finish response and clean up"""
        if not self.response_started:
            return

        # Response finished - add separator
        self.add_content("\n")
        self.response_started = False
        self.buffer = ""

    def show_welcome(self):
        """Show welcome message"""
        welcome_text = (
            "LLMVM Pane Client (Live Mode)\n"
            "─" * 40 + "\n"
            f"Server: {self.config.server_url}\n"
            f"Mode: {self.config.mode}\n"
            f"Model: {self.config.executor}/{self.config.model}\n"
            "─" * 40 + "\n"
            "• Live streaming in top pane, persistent input in bottom pane\n"
            "• ESC to clear input\n"
            "• Ctrl-D to delete character (or exit on empty prompt)\n"
            "• Enter to submit, 'exit' to quit, 'clear' to clear content\n\n"
        )
        self.add_content(welcome_text)

    def show_goodbye(self):
        """Show exit message"""
        self.add_content("\nGoodbye!\n")

    def show_interrupt_hint(self):
        """Show hint after Ctrl-C"""
        self.add_content("\n(Use Ctrl-C to quit)\n")

    def show_interrupted(self):
        """Show message when stream interrupted"""
        self.add_content("\n[Interrupted]\n")

    def show_message(self, message: str, style: str = "default"):
        """Show a message"""
        self.add_content(f"\n{message}\n")

    def run(self):
        """Run the application"""
        return self.app.run()

    def get_input_text(self):
        """Get current input text"""
        return self.input_area.text

    def clear_input(self):
        """Clear input area"""
        self.input_area.text = ""