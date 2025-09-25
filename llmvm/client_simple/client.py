"""Main simple client orchestrator"""
import asyncio
import os
import sys
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

from .config import Config
from .keybindings import create_keybindings, KeyHandler
from .renderer import Renderer
from .server_proxy import ServerProxy


class SimpleClient:
    """Simple LLMVM client that connects to server and provides basic REPL"""

    def __init__(self):
        self.config = Config.from_env()
        self.server = ServerProxy(self.config)
        self.renderer = Renderer(self.config)
        self.key_handler = KeyHandler(self)
        self.keybindings = create_keybindings(self.key_handler)

        # Prompt session with history - only if we have a TTY
        self.session = None
        if sys.stdin.isatty() and sys.stdout.isatty():
            try:
                self.session = PromptSession(
                    history=FileHistory(self.config.history_file),
                    key_bindings=self.keybindings,
                    enable_system_prompt=False
                )
            except Exception as e:
                self.config.debug_print(f"Error setting up prompt session: {e}")
                # Fallback to simple session without history
                try:
                    self.session = PromptSession(
                        key_bindings=self.keybindings,
                        enable_system_prompt=False
                    )
                except Exception as e2:
                    self.config.debug_print(f"Error setting up fallback prompt session: {e2}")
                    self.session = None

        self.should_exit = False

    def run(self):
        """Main REPL loop"""
        self.renderer.show_welcome()

        # Check server connectivity
        if not asyncio.run(self.check_server()):
            return 1

        # Check if we can run interactive mode
        if not self.session:
            self.renderer.render_error(
                "Cannot run in interactive mode (no TTY available). "
                "Simple client requires a terminal for interactive use."
            )
            return 1

        while not self.should_exit:
            try:
                # Get user input with thread ID in prompt
                thread_id = getattr(self.server.thread, 'id', 'new') if self.server.thread else 'new'
                prompt = f"[{thread_id}]>> "
                user_input = self.session.prompt(prompt)

                # Handle None from Ctrl-D on empty prompt
                if user_input is None:
                    self.should_exit = True
                    break

                # Handle exit command
                if user_input.strip().lower() == "exit":
                    self.should_exit = True
                    break

                if user_input.strip():
                    # Send to server and render response
                    asyncio.run(self.handle_message(user_input))

            except EOFError:
                # Shouldn't happen with our keybindings, but handle gracefully
                self.config.debug_print("EOFError caught")
                break
            except KeyboardInterrupt:
                # Ctrl-C - just show hint
                self.renderer.show_interrupt_hint()
                continue
            except Exception as e:
                self.config.debug_print(f"Unexpected error in main loop: {e}")
                self.renderer.render_error(str(e))
                continue

        self.renderer.show_goodbye()
        return 0

    async def check_server(self) -> bool:
        """Check if server is available"""
        self.config.debug_print("Checking server health...")

        if not await self.server.check_health():
            self.renderer.render_error(
                f"Cannot connect to server at {self.config.server_url}. "
                f"Please start the server first:\n  uv run llmvm --status\n  uv run llmvm"
            )
            return False

        self.config.debug_print("Server is healthy")
        return True

    async def handle_message(self, message: str):
        """Send message to server and render response"""
        try:
            self.config.log_to_file(f"[CLIENT] Sending message: {message}")
            self.config.debug_print(f"Sending message: {message[:50]}...")

            response_received = False

            async for chunk in self.server.stream_chat(message):
                response_received = True

                if chunk.type == "text":
                    self.renderer.render_text(chunk.content)
                elif chunk.type == "image":
                    self.renderer.render_image(chunk.content)
                elif chunk.type == "code":
                    language = chunk.metadata.get("language") if chunk.metadata else None
                    self.renderer.render_code(chunk.content, language)
                elif chunk.type == "error":
                    self.renderer.render_error(chunk.content)
                    break  # Stop processing on error
                else:
                    # Unknown type, render as text
                    self.config.debug_print(f"Unknown chunk type: {chunk.type}")
                    self.renderer.render_text(str(chunk.content))

            # Finish the response
            if response_received:
                self.config.log_to_file("[CLIENT] Response completed")
                self.renderer.finish_response()
            else:
                # No response received
                self.config.log_to_file("[CLIENT] No response from server")
                self.renderer.render_error("No response from server")

        except Exception as e:
            self.config.log_to_file(f"[CLIENT] Error handling message: {e}")
            self.config.debug_print(f"Error handling message: {e}")
            self.renderer.render_error(f"Communication error: {e}")

    def request_exit(self):
        """Called by keybindings to exit"""
        self.config.debug_print("Exit requested")
        self.should_exit = True

    def interrupt_current_request(self):
        """Interrupt current streaming request"""
        if self.server.is_streaming:
            self.server.interrupt()
            self.renderer.show_interrupted()


if __name__ == "__main__":
    client = SimpleClient()
    exit_code = client.run()
    sys.exit(exit_code)