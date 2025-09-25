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

    def get_approval_decision(self, approval_request) -> bool:
        """Get approval decision using simple input() like main client"""
        from llmvm.common.objects import ApprovalRequest
        from rich.console import Console

        if not isinstance(approval_request, ApprovalRequest):
            return False

        # Use Rich console for colored output like main client
        console = Console()

        # Show approval prompt with colors (exactly like main client)
        console.print("\n🔐 [bold red]Bash Command Approval Required[/bold red]")
        console.print(f"[bold]Command:[/bold] {approval_request.command}")
        console.print(f"[bold]Working Directory:[/bold] {approval_request.working_directory}")
        if approval_request.justification:
            console.print(f"[bold]Justification:[/bold] {approval_request.justification}")

        console.print("\n[dim]Options:[/dim]")
        console.print("  [green](a)pprove[/green] - Execute this command once")
        console.print("  [yellow](s)ession[/yellow] - Execute and auto-approve for this session")
        console.print("  [red](d)eny[/red] - Do not execute this command")

        # Get approval decision from user
        while True:
            try:
                # Use simple input() like main client - no PromptSession complexity
                response = input("\nYour choice [a/s/d]: ").lower().strip()

                if response in ['a', 'approve']:
                    console.print("[green]✓ Command approved for execution[/green]")
                    return True
                elif response in ['s', 'session']:
                    console.print("[yellow]✓ Command approved for execution and session[/yellow]")
                    # Note: Session approval would need additional server-side support
                    return True
                elif response in ['d', 'deny']:
                    console.print("[red]✗ Command denied[/red]")
                    return False
                else:
                    console.print("[red]Invalid choice. Please enter 'a', 's', or 'd'[/red]")

            except (KeyboardInterrupt, EOFError):
                console.print("\n[red]✗ Approval cancelled[/red]")
                return False


if __name__ == "__main__":
    client = SimpleClient()
    exit_code = client.run()
    sys.exit(exit_code)