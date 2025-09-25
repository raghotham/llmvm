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
from .slash_commands import SlashCommandHandler


class SimpleClient:
    """Simple LLMVM client that connects to server and provides basic REPL"""

    def __init__(self):
        self.config = Config.from_env()
        self.server = ServerProxy(self.config)
        self.renderer = Renderer(self.config)
        self.key_handler = KeyHandler(self)
        self.keybindings = create_keybindings(self.key_handler)
        self.slash_handler = SlashCommandHandler(self)

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
                # Get user input with thread ID and token usage in prompt
                thread_id = getattr(self.server.thread, 'id', 'new') if self.server.thread else 'new'

                # Get token usage from server
                total_tokens = 0
                if self.server.thread and hasattr(self.server.thread, 'id') and self.server.thread.id > 0:
                    try:
                        total_tokens = asyncio.run(self._get_session_tokens(self.server.thread.id))
                    except Exception:
                        pass  # Ignore token fetching errors

                if total_tokens > 0:
                    prompt = f"[{thread_id}|{total_tokens}t]>> "
                else:
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
                    # Check for slash commands first
                    if self.slash_handler.is_slash_command(user_input):
                        # Handle locally, don't send to server
                        result = asyncio.run(self.slash_handler.execute_command(user_input))
                        if result.success:
                            self.renderer.render_command_output(result.message)
                        else:
                            self.renderer.render_error(result.message)
                    else:
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
                elif chunk.type == "approval":
                    # Handle approval request directly in the streaming loop (like main client)
                    approved = self.get_approval_decision(chunk.content)
                    # Send approval response and continue streaming
                    async for response_chunk in self.server.send_approval_response(chunk.content, approved):
                        if response_chunk.type == "text":
                            self.renderer.render_text(response_chunk.content)
                        elif response_chunk.type == "image":
                            self.renderer.render_image(response_chunk.content)
                        elif response_chunk.type == "code":
                            language = response_chunk.metadata.get("language") if response_chunk.metadata else None
                            self.renderer.render_code(response_chunk.content, language)
                        elif response_chunk.type == "error":
                            self.renderer.render_error(response_chunk.content)
                            break
                        else:
                            self.renderer.render_text(str(response_chunk.content))
                else:
                    # Unknown type, render as text
                    self.config.debug_print(f"Unknown chunk type: {chunk.type}")
                    self.renderer.render_text(str(chunk.content))

            # Finish the response
            if response_received:
                self.config.log_to_file("[CLIENT] Response completed")
                self.renderer.finish_response()
                # Show token usage summary
                await self._show_token_usage()
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

    async def _show_token_usage(self):
        """Display token usage information after each response"""
        if not self.server.thread or not hasattr(self.server.thread, 'id'):
            return

        try:
            session_tokens = await self._get_session_tokens(self.server.thread.id)
            if session_tokens > 0:
                self.renderer.console.print(
                    f"[dim]Session tokens: {session_tokens}[/dim]"
                )
        except Exception as e:
            self.config.debug_print(f"Error showing token usage: {e}")


if __name__ == "__main__":
    client = SimpleClient()
    exit_code = client.run()
    sys.exit(exit_code)