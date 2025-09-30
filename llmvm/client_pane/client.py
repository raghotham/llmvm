"""Simple pane client with two-pane interface"""
import asyncio
import os
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
from .server_proxy import ServerProxy
from .slash_commands import SlashCommandHandler


class PaneClient:
    """Simple two-pane client - content above, input below"""

    def __init__(self):
        self.config = Config.from_env()
        self.should_exit = False
        self.is_processing = False
        self.stop_streaming = False  # Flag to stop streaming

        # Server components
        try:
            self.server = ServerProxy(self.config)
            self.slash_handler = SlashCommandHandler(self)
        except Exception as e:
            # Show error but continue with limited functionality
            self.server = None
            self.slash_handler = None
            self._init_error = f"Failed to initialize server components: {e}"

        # Content storage
        self.content_lines = []

        # Viewport management for scrolling
        self.viewport_offset = 0  # Lines scrolled from bottom (0 = show bottom)
        self.viewport_height = 20  # Will be updated based on terminal size

        # Input history
        self.input_history = []
        self.history_index = -1
        self._load_history()

        # Activity indicator
        self.spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_index = 0
        self.spinner_task = None
        self.show_spinner = False
        self.spinner_message = "Processing"

        # Create UI components
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI with proper viewport-based scrolling"""
        # Content area with viewport management
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
        self.current_session_tokens = 0

        # Separator lines - dim gray horizontal lines that work in both light and dark modes
        # These will be updated dynamically to match terminal width
        self.top_separator_control = FormattedTextControl(text=FormattedText([("fg:ansigray", "")]))
        self.top_separator = Window(
            content=self.top_separator_control,
            height=Dimension.exact(1)
        )

        self.bottom_separator_control = FormattedTextControl(text=FormattedText([("fg:ansigray", "")]))
        self.bottom_separator = Window(
            content=self.bottom_separator_control,
            height=Dimension.exact(1)
        )

        # Status area - shows spinner when processing
        self.status_control = FormattedTextControl(text="")
        self.status_area = Window(
            content=self.status_control,
            height=Dimension.exact(1),
            wrap_lines=False
        )

        # Token display
        self.token_control = FormattedTextControl(text="[Session tokens: 0]")
        self.token_area = Window(
            content=self.token_control,
            height=Dimension.exact(1),
            wrap_lines=False
        )

        # Layout: content + separator + input + separator + status + token
        self.layout = Layout(
            HSplit([
                self.content_area,  # Content area
                self.top_separator,  # Line above input
                Window(height=Dimension.exact(3), content=self.input_area.control),  # Input
                self.bottom_separator,  # Line below input
                self.status_area,   # Status/spinner
                self.token_area,    # Token count
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
                # Add to history and save to file
                self.input_history.append(text)
                self.history_index = -1  # Reset history index
                self._save_history()

                # Show what user typed
                self.add_content(f"[You] {text}\n")

                # Handle commands
                if text.lower() == "exit":
                    self.should_exit = True
                    event.app.exit()
                elif text.lower() == "clear":
                    self.clear_content()
                elif text.lower() == "test":
                    # Start dummy streaming in background (keep for testing)
                    self.is_processing = True
                    self.stop_streaming = False  # Reset stop flag
                    thread = threading.Thread(target=self._dummy_stream)
                    thread.start()
                else:
                    # Send to server
                    if not self.server:
                        self.add_content("[Error: Server not available. Use 'test' for demo or restart client.]\n")
                    else:
                        self.is_processing = True
                        self.stop_streaming = False  # Reset stop flag
                        thread = threading.Thread(
                            target=lambda: asyncio.run(self._handle_server_message(text))
                        )
                        thread.start()

                # Clear input
                self.input_area.text = ""

        @kb.add(Keys.Escape)
        def _(event):
            """Handle ESC key - stop streaming and interrupt server"""
            if self.is_processing:
                # Stop streaming and interrupt server
                self.stop_streaming = True
                if self.server and self.server.is_streaming:
                    self.server.interrupt()
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

        @kb.add(Keys.Up)
        def _(event):
            """Handle Up arrow - navigate history backwards"""
            if self.input_history and self.history_index < len(self.input_history) - 1:
                self.history_index += 1
                self.input_area.text = self.input_history[-(self.history_index + 1)]

        @kb.add(Keys.Down)
        def _(event):
            """Handle Down arrow - navigate history forwards"""
            if self.history_index > 0:
                self.history_index -= 1
                self.input_area.text = self.input_history[-(self.history_index + 1)]
            elif self.history_index == 0:
                self.history_index = -1
                self.input_area.text = ""

        @kb.add(Keys.PageUp)
        def _(event):
            """Handle Page Up - scroll content up"""
            self._scroll_up()

        @kb.add(Keys.PageDown)
        def _(event):
            """Handle Page Down - scroll content down"""
            self._scroll_down()

        return kb

    def add_content(self, text: str):
        """Add content to display area with viewport management"""
        self.content_lines.append(text)
        # Auto-scroll to bottom when new content arrives (unless user is scrolled up)
        if self.viewport_offset == 0:
            self._update_display()
        else:
            # User is scrolled up, don't auto-scroll but update display
            self._update_display_viewport()

    def clear_content(self):
        """Clear the display area but preserve welcome text"""
        self.content_lines = []
        self.viewport_offset = 0  # Reset scroll position
        self._show_welcome()

    def _update_display(self):
        """Update display with auto-scroll to bottom (normal operation)"""
        self.viewport_offset = 0  # Reset to bottom
        self._update_display_viewport()

    def _load_history(self):
        """Load input history from file"""
        try:
            history_file = self.config.history_file
            if history_file and os.path.exists(history_file):
                with open(history_file, 'r', encoding='utf-8') as f:
                    self.input_history = [line.rstrip('\n') for line in f if line.strip()]
                self.config.debug_print(f"Loaded {len(self.input_history)} history entries from {history_file}")
        except Exception as e:
            self.config.debug_print(f"Failed to load history: {e}")

    def _save_history(self):
        """Save input history to file"""
        try:
            history_file = self.config.history_file
            if history_file:
                # Create directory if it doesn't exist
                history_dir = os.path.dirname(history_file)
                if history_dir:
                    os.makedirs(history_dir, exist_ok=True)

                with open(history_file, 'w', encoding='utf-8') as f:
                    for entry in self.input_history:
                        f.write(entry + '\n')
                self.config.debug_print(f"Saved {len(self.input_history)} history entries to {history_file}")
        except Exception as e:
            self.config.debug_print(f"Failed to save history: {e}")

    def _update_separator_lines(self):
        """Update separator lines to match terminal width"""
        if hasattr(self.app, 'output') and self.app.output:
            try:
                terminal_width = self.app.output.get_size().columns
                line = "─" * terminal_width
                self.top_separator_control.text = FormattedText([("fg:ansigray", line)])
                self.bottom_separator_control.text = FormattedText([("fg:ansigray", line)])
            except:
                # Fallback to 80 if we can't get terminal width
                self.top_separator_control.text = FormattedText([("fg:ansigray", "─" * 80)])
                self.bottom_separator_control.text = FormattedText([("fg:ansigray", "─" * 80)])

    def _update_display_viewport(self):
        """Simple viewport - just show content with basic scrolling"""
        full_text = "".join(self.content_lines)
        all_lines = full_text.split('\n')

        # Update separator lines to match current terminal width
        self._update_separator_lines()

        # Calculate viewport height
        if hasattr(self.app, 'output') and self.app.output:
            try:
                terminal_height = self.app.output.get_size().rows
                self.viewport_height = max(10, terminal_height - 5)  # Reserve space for input/token
            except:
                self.viewport_height = 20
        else:
            self.viewport_height = 20

        total_lines = len(all_lines)

        if total_lines <= self.viewport_height:
            # All content fits
            visible_text = full_text
        else:
            # Show viewport window
            if self.viewport_offset == 0:
                # Show bottom (most recent)
                start_line = max(0, total_lines - self.viewport_height)
                end_line = total_lines
            else:
                # Show scrolled position
                start_line = max(0, total_lines - self.viewport_height - self.viewport_offset)
                end_line = start_line + self.viewport_height

            visible_lines = all_lines[start_line:end_line]
            visible_text = '\n'.join(visible_lines)

        self.content_control.text = FormattedText([("", visible_text)])
        self.app.invalidate()

    def _scroll_up(self):
        """Scroll content up (show older content)"""
        full_text = "".join(self.content_lines)
        total_lines = len(full_text.split('\n'))

        # Can only scroll if content exceeds viewport
        if total_lines > self.viewport_height:
            max_offset = total_lines - self.viewport_height
            self.viewport_offset = min(max_offset, self.viewport_offset + 5)  # Scroll 5 lines at a time
            self._update_display_viewport()

    def _scroll_down(self):
        """Scroll content down (show newer content)"""
        if self.viewport_offset > 0:
            self.viewport_offset = max(0, self.viewport_offset - 5)  # Scroll 5 lines at a time
            self._update_display_viewport()

    def _start_spinner(self, initial_message: str = "Processing"):
        """Start the spinner animation"""
        self.show_spinner = True
        self.spinner_index = 0
        self.spinner_message = initial_message

        async def animate_spinner():
            while self.show_spinner and not self.should_exit:
                spinner = self.spinner_chars[self.spinner_index % len(self.spinner_chars)]
                self.status_control.text = FormattedText([("fg:ansiblue", f"{spinner} {self.spinner_message}...")])
                self.app.invalidate()
                self.spinner_index += 1
                await asyncio.sleep(0.1)

            # Clear spinner when done
            self.status_control.text = ""
            self.app.invalidate()

        # Start the spinner animation in the background
        if self.spinner_task:
            self.spinner_task.cancel()
        self.spinner_task = asyncio.create_task(animate_spinner())

    def _update_spinner_message(self, message: str):
        """Update spinner message without restarting animation"""
        if self.show_spinner:
            self.spinner_message = message

    def _handle_event(self, event):
        """Handle server event nodes and update status accordingly"""
        from llmvm.common.objects import (
            InferenceStartNode, InferenceEndNode,
            HelpersExtractedNode, HelpersExecutionStartNode, HelpersExecutionEndNode
        )

        if isinstance(event, InferenceStartNode):
            self._update_spinner_message("Thinking")
        elif isinstance(event, HelpersExtractedNode):
            count = event.total_blocks
            self._update_spinner_message(f"Extracting code ({count} block{'s' if count != 1 else ''})")
        elif isinstance(event, HelpersExecutionStartNode):
            block_num = event.block_index + 1
            self._update_spinner_message(f"Executing code block {block_num}")
        elif isinstance(event, HelpersExecutionEndNode):
            # After execution, go back to thinking (continuation style)
            self._update_spinner_message("Thinking")
        elif isinstance(event, InferenceEndNode):
            # Don't stop spinner - there may be more inference rounds
            # Keep current status message
            pass

    def _stop_spinner(self):
        """Stop the spinner animation"""
        self.show_spinner = False
        if self.spinner_task:
            self.spinner_task.cancel()
            self.spinner_task = None
        self.status_control.text = ""
        self.app.invalidate()

    def _update_token_display(self, tokens: int = None):
        """Update the token count display"""
        if tokens is not None:
            self.current_session_tokens = tokens

        token_text = f"[Session tokens: {self.current_session_tokens}]  |  ESC: stop  |  PgUp/PgDn: scroll  |  /help: commands"
        self.token_control.text = FormattedText([("class:token-count", token_text)])
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

    async def _handle_server_message(self, message: str):
        """Handle message by sending to server and processing response"""
        try:
            self.config.log_to_file(f"[CLIENT] Sending message: {message}")
            self.config.debug_print(f"Sending message: {message[:50]}...")

            response_received = False
            first_chunk = True

            # Check for slash commands first
            if self.slash_handler.is_slash_command(message):
                # Handle locally, don't send to server
                result = await self.slash_handler.execute_command(message)
                if result.success:
                    self.add_content(f"\n[Command Output]\n{result.message}\n[End Command Output]\n")
                else:
                    self.add_content(f"\n[Error: {result.message}]\n")
                return

            # Start spinner - it will run until </complete> is seen
            self._start_spinner("Thinking")

            async for chunk in self.server.stream_chat(message):
                # Check for interruption
                if self.should_exit or self.stop_streaming:
                    break

                # Handle completion signal
                if chunk.type == "complete":
                    self._stop_spinner()
                    continue

                # Handle event nodes
                if chunk.type == "event":
                    self._handle_event(chunk.content)
                    continue

                response_received = True

                # Add [Assistant] prefix on first chunk regardless of type
                if first_chunk:
                    self.add_content("\n[Assistant] ")
                    first_chunk = False

                if chunk.type == "text":
                    self.add_content(chunk.content)
                elif chunk.type == "image":
                    # Save image to temp file and open with system viewer
                    try:
                        import tempfile
                        import subprocess
                        import platform

                        # Create temp file with .png extension
                        with tempfile.NamedTemporaryFile(mode='wb', suffix='.png', delete=False) as f:
                            f.write(chunk.content)
                            temp_path = f.name

                        # Open with system viewer
                        system = platform.system()
                        if system == 'Darwin':  # macOS
                            subprocess.Popen(['open', temp_path])
                        elif system == 'Linux':
                            subprocess.Popen(['xdg-open', temp_path])
                        elif system == 'Windows':
                            subprocess.Popen(['start', temp_path], shell=True)

                        self.add_content(f"[Image opened in system viewer - {len(chunk.content)} bytes]\n")
                    except Exception as e:
                        self.add_content(f"[Image received but failed to open - {len(chunk.content)} bytes: {e}]\n")
                elif chunk.type == "code":
                    language = chunk.metadata.get("language") if chunk.metadata else None
                    lang_str = f" ({language})" if language else ""
                    self.add_content(f"\n[CODE BLOCK{lang_str}]\n{chunk.content}\n[END CODE BLOCK]\n")
                elif chunk.type == "error":
                    self.add_content(f"[Error: {chunk.content}]\n")
                    break  # Stop processing on error
                else:
                    # Unknown type, render as text
                    self.config.debug_print(f"Unknown chunk type: {chunk.type}")
                    self.add_content(str(chunk.content))

            # Finish the response
            if response_received and not self.stop_streaming:
                self.config.log_to_file("[CLIENT] Response completed")
                self.add_content("\n")
                # Show token usage summary
                await self._show_token_usage()
            elif not response_received:
                # No response received
                self.config.log_to_file("[CLIENT] No response from server")
                self.add_content("\n[No response from server]\n")

        except Exception as e:
            self.config.log_to_file(f"[CLIENT] Error handling message: {e}")
            self.config.debug_print(f"Error handling message: {e}")
            self.add_content(f"\n[Communication error: {e}]\n")
        finally:
            self._stop_spinner()
            self.is_processing = False

    async def _show_token_usage(self):
        """Update token usage display after each response"""
        if not self.server or not self.server.thread or not hasattr(self.server.thread, 'id'):
            return

        try:
            session_tokens = await self._get_session_tokens(self.server.thread.id)
            self._update_token_display(session_tokens)
        except Exception as e:
            self.config.debug_print(f"Error showing token usage: {e}")

    async def _get_session_tokens(self, session_id: int) -> int:
        """Get token count for session from server"""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.config.server_url}/v1/usage?session_id={session_id}",
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get('total_tokens', 0)
        except Exception as e:
            self.config.debug_print(f"Error getting token usage from server: {e}")
        return 0

    def _show_welcome(self):
        """Show welcome message"""
        self.add_content("LLMVM Pane Client\n")
        self.add_content("─" * 40 + "\n")
        self.add_content("Type any message to chat with the LLM\n")
        self.add_content("Commands: 'clear' (clear chat), 'exit' (quit)\n")
        self.add_content("Slash commands: /help, /status, etc.\n")
        self.add_content("Keys: ESC (stop streaming), Ctrl-C (exit)\n")
        self.add_content("Scroll: Page Up/Down (terminal scroll is disabled)\n\n")
        # Initialize token display
        self._update_token_display(0)

    async def check_server(self) -> bool:
        """Check if server is available"""
        # Check if server components were initialized
        if hasattr(self, '_init_error'):
            self.add_content(f"❌ {self._init_error}\n\n")
            return False

        if not self.server:
            self.add_content("❌ Server components not initialized\n\n")
            return False

        self.config.debug_print("Checking server health...")

        try:
            if not await self.server.check_health():
                self.add_content(f"❌ Cannot connect to server at {self.config.server_url}\n")
                self.add_content("Please start the server first:\n")
                self.add_content("  uv run llmvm --status\n")
                self.add_content("  uv run llmvm\n\n")
                return False

            self.config.debug_print("Server is healthy")
            self.add_content(f"✅ Connected to server at {self.config.server_url}\n\n")
            return True
        except Exception as e:
            self.add_content(f"❌ Error checking server health: {e}\n\n")
            return False

    def run(self):
        """Run the client"""
        # Show welcome
        self._show_welcome()

        # Check server connectivity
        if not asyncio.run(self.check_server()):
            self.add_content("Press Ctrl-C to exit.\n")
            try:
                self.app.run()
            except KeyboardInterrupt:
                pass
            return 1

        try:
            self.app.run()
        except KeyboardInterrupt:
            pass

        return 0


if __name__ == "__main__":
    import sys
    client = PaneClient()
    sys.exit(client.run())