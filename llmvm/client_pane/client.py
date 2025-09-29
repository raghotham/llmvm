"""Simple pane client with two-pane interface"""
import threading
import time
from prompt_toolkit.application import Application
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from .config import Config


class PaneClient:
    """Simple two-pane client - content above, input below"""

    def __init__(self):
        self.config = Config.from_env()
        self.should_exit = False
        self.is_processing = False
        self.stop_streaming = False  # Flag to stop streaming

        # Content storage
        self.content_lines = []

        # Create UI components
        self._setup_ui()

    def _setup_ui(self):
        """Set up the two-pane UI"""
        # Content area - displays output
        self.content_control = FormattedTextControl(text="")
        self.content_area = Window(
            content=self.content_control,
            wrap_lines=True
        )

        # Input area - where user types
        self.input_area = TextArea(
            prompt=">> ",
            multiline=False,
            wrap_lines=False
        )

        # Layout: content above, input below
        self.layout = Layout(
            HSplit([
                self.content_area,  # Takes most space
                Window(height=Dimension.exact(3), content=self.input_area.control)  # Fixed height
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
        """Create key bindings"""
        kb = KeyBindings()

        @kb.add(Keys.Enter)
        def _(event):
            """Handle Enter key"""
            text = self.input_area.text.strip()
            if text and not self.is_processing:
                # Show what user typed
                self.add_content(f"[You] {text}\n")

                # Handle commands
                if text.lower() == "exit":
                    self.should_exit = True
                    event.app.exit()
                elif text.lower() == "clear":
                    self.clear_content()
                elif text.lower() == "test":
                    # Start dummy streaming in background
                    self.is_processing = True
                    self.stop_streaming = False  # Reset stop flag
                    thread = threading.Thread(target=self._dummy_stream)
                    thread.start()
                else:
                    # Echo back
                    self.add_content(f"[Echo] You said: {text}\n")

                # Clear input
                self.input_area.text = ""

        @kb.add(Keys.Escape)
        def _(event):
            """Handle ESC key - only stop streaming"""
            if self.is_processing:
                # Stop streaming
                self.stop_streaming = True
                self.add_content("\n⏹️ Streaming stopped\n")
            else:
                self.add_content("⏹️ ESC pressed (no active stream)\n")

        @kb.add(Keys.ControlC)
        def _(event):
            """Handle Ctrl-C"""
            self.should_exit = True
            event.app.exit()

        @kb.add(Keys.ControlD)
        def _(event):
            """Handle Ctrl-D"""
            if not self.input_area.text:
                # Exit on empty input
                self.should_exit = True
                event.app.exit()
            else:
                # Delete character at cursor
                if self.input_area.document.cursor_position < len(self.input_area.text):
                    current_text = self.input_area.text
                    cursor_pos = self.input_area.document.cursor_position
                    self.input_area.text = current_text[:cursor_pos] + current_text[cursor_pos+1:]

        return kb

    def add_content(self, text: str):
        """Add content to display area"""
        self.content_lines.append(text)
        self._update_display()

    def clear_content(self):
        """Clear the display area but preserve welcome text"""
        self.content_lines = []
        self._show_welcome()

    def _update_display(self):
        """Update the display"""
        full_text = "".join(self.content_lines)
        self.content_control.text = FormattedText([("", full_text)])
        self.app.invalidate()

    def _dummy_stream(self):
        """Dummy streaming function for testing"""
        try:
            self.add_content("\n[Assistant] Starting dummy stream...\n")

            for i in range(20):  # More lines for better testing
                if self.should_exit or self.stop_streaming:
                    break
                self.add_content(f"Line {i+1}: This is streaming content.\n")

                # Sleep in smaller chunks so we can respond to ESC faster
                for _ in range(10):  # 10 * 0.1 = 1 second total per line
                    if self.should_exit or self.stop_streaming:
                        break
                    time.sleep(0.1)

            if not self.stop_streaming and not self.should_exit:
                self.add_content("\n[Assistant] Stream complete!\n")
        except Exception as e:
            self.add_content(f"\nError: {e}\n")
        finally:
            self.is_processing = False

    def _show_welcome(self):
        """Show welcome message"""
        self.add_content("LLMVM Pane Client\n")
        self.add_content("─" * 40 + "\n")
        self.add_content("Commands: 'test' (dummy stream), 'clear', 'exit'\n")
        self.add_content("Keys: ESC (stop streaming), Ctrl-C (exit)\n\n")

    def run(self):
        """Run the client"""
        # Show welcome
        self._show_welcome()

        try:
            self.app.run()
        except KeyboardInterrupt:
            pass

        return 0


if __name__ == "__main__":
    import sys
    client = PaneClient()
    sys.exit(client.run())