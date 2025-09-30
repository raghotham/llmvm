"""Slash commands handler for LLMVM Simple Client"""
import asyncio
from typing import Dict, Callable, Optional, Any
from dataclasses import dataclass
import httpx


@dataclass
class CommandResult:
    """Result of executing a slash command"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class SlashCommandHandler:
    """Handler for slash commands in the simple client"""

    def __init__(self, client):
        self.client = client
        self.commands: Dict[str, Callable] = {
            'usage': self._handle_usage,
            'help': self._handle_help,
            'clear': self._handle_clear,
            'status': self._handle_status,
        }

    def is_slash_command(self, user_input: str) -> bool:
        """Check if input is a slash command"""
        return user_input.strip().startswith('/')

    async def execute_command(self, user_input: str) -> CommandResult:
        """Execute a slash command"""
        if not self.is_slash_command(user_input):
            return CommandResult(success=False, message="Not a slash command")

        # Parse command and arguments
        parts = user_input.strip()[1:].split()  # Remove leading '/' and split
        if not parts:
            return CommandResult(success=False, message="Empty command")

        command = parts[0].lower()
        args = parts[1:] if len(parts) > 1 else []

        if command not in self.commands:
            available = ', '.join(f'/{cmd}' for cmd in self.commands.keys())
            return CommandResult(
                success=False,
                message=f"Unknown command '/{command}'. Available commands: {available}"
            )

        try:
            return await self.commands[command](args)
        except Exception as e:
            return CommandResult(success=False, message=f"Command error: {str(e)}")

    async def _handle_usage(self, args: list) -> CommandResult:
        """Handle /usage command"""
        try:
            # Get current session ID
            session_id = None
            if self.client.server.thread and hasattr(self.client.server.thread, 'id'):
                session_id = self.client.server.thread.id


            async with httpx.AsyncClient() as http_client:
                if args and args[0] == 'global':
                    # Global usage across all sessions
                    url = f"{self.client.config.server_url}/v1/usage"
                    response = await http_client.get(url, timeout=5.0)
                elif session_id is not None and session_id > 0:
                    # Current session usage
                    url = f"{self.client.config.server_url}/v1/usage?session_id={session_id}"
                    response = await http_client.get(url, timeout=5.0)
                else:
                    # No active session - show global usage instead
                    url = f"{self.client.config.server_url}/v1/usage"
                    response = await http_client.get(url, timeout=5.0)


                if response.status_code == 200:
                    data = response.json()

                    if 'sessions' in data:
                        # Global usage response
                        if session_id is not None and session_id > 0:
                            message = f"Session {session_id} Usage:\n"
                            message += f"  Current session ID: {session_id}\n"
                            if str(session_id) in data['sessions']:
                                session_data = data['sessions'][str(session_id)]
                                message += f"  Total tokens: {session_data['total_tokens']:,}\n"
                                message += f"  Requests: {session_data['request_count']}\n"
                                if 'start_time' in session_data:
                                    import time
                                    duration = time.time() - session_data['start_time']
                                    message += f"  Duration: {duration/60:.1f} minutes\n"
                            else:
                                message += f"  Status: No usage data tracked for this session yet\n"
                                message += f"  Note: Session may not have made any LLM calls\n"
                        else:
                            message = f"Global Usage:\n"
                            message += f"  Current session ID: None (no active session)\n"

                        message += f"\nGlobal totals:\n"
                        message += f"  Total tokens: {data['total_tokens']:,}\n"
                        message += f"  Total requests: {data['total_requests']:,}\n"
                        message += f"  Active sessions: {data['active_sessions']}\n"

                        if data['sessions']:
                            message += f"\nActive sessions being tracked:\n"
                            for sid, session_data in data['sessions'].items():
                                current_marker = " (current)" if str(session_id) == str(sid) else ""
                                message += f"  Session {sid}{current_marker}: {session_data['total_tokens']:,} tokens, {session_data['request_count']} requests\n"
                        else:
                            message += f"\nNo sessions with token usage found.\n"
                    else:
                        # Session-specific usage response
                        message = f"Session {data['session_id']} Usage:\n"
                        message += f"  Total tokens: {data['total_tokens']:,}\n"
                        message += f"  Requests: {data['request_count']}\n"
                        if 'start_time' in data:
                            import time
                            duration = time.time() - data['start_time']
                            message += f"  Duration: {duration/60:.1f} minutes\n"

                    return CommandResult(success=True, message=message, data=data)
                elif response.status_code == 404:
                    # Session not found - fall back to global usage
                    if session_id is not None and session_id > 0:
                        # Make another request for global usage
                        global_response = await http_client.get(
                            f"{self.client.config.server_url}/v1/usage",
                            timeout=5.0
                        )
                        if global_response.status_code == 200:
                            data = global_response.json()
                            message = f"Session {session_id} not found. Showing global usage instead:\n\n"
                            message += f"Requested session ID: {session_id}\n"
                            message += f"Global totals:\n"
                            message += f"  Total tokens: {data['total_tokens']:,}\n"
                            message += f"  Total requests: {data['total_requests']:,}\n"
                            message += f"  Active sessions: {data['active_sessions']}\n"

                            if data.get('sessions'):
                                message += f"\nActive sessions being tracked:\n"
                                for sid, session_data in data['sessions'].items():
                                    message += f"  Session {sid}: {session_data['total_tokens']:,} tokens, {session_data['request_count']} requests\n"
                            else:
                                message += f"\nNo sessions with token usage found.\n"
                                message += f"Note: Sessions only appear here after making LLM calls.\n"

                            return CommandResult(success=True, message=message, data=data)

                    return CommandResult(
                        success=False,
                        message=f"Session {session_id} not found and unable to fetch global usage"
                    )
                else:
                    return CommandResult(
                        success=False,
                        message=f"Server error: {response.status_code}"
                    )

        except httpx.ConnectError:
            return CommandResult(
                success=False,
                message=f"Cannot connect to server at {self.client.config.server_url}"
            )
        except Exception as e:
            return CommandResult(success=False, message=f"Usage command error: {str(e)}")

    async def _handle_clear(self, args: list) -> CommandResult:
        """Handle /clear command"""
        try:
            # Reset the client's conversation context
            if hasattr(self.client, 'clear_context'):
                self.client.clear_context()
            elif hasattr(self.client, 'server') and hasattr(self.client.server, 'clear_context'):
                self.client.server.clear_context()
            else:
                # Fallback: try to reset thread/conversation state
                if hasattr(self.client, 'server') and hasattr(self.client.server, 'thread'):
                    self.client.server.thread = None

            return CommandResult(success=True, message="Context cleared. Starting fresh conversation.")
        except Exception as e:
            return CommandResult(success=False, message=f"Failed to clear context: {str(e)}")

    async def _handle_status(self, args: list) -> CommandResult:
        """Handle /status command - show server and client status"""
        try:
            # Get server health
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(
                    f"{self.client.config.server_url}/health",
                    timeout=5.0
                )

                if response.status_code == 200:
                    health_data = response.json()
                    status_text = f"Server Status:\n"
                    status_text += f"  URL: {self.client.config.server_url}\n"
                    status_text += f"  Status: {health_data.get('status', 'unknown')}\n"

                    # Add session info if available
                    if self.client.server.thread and hasattr(self.client.server.thread, 'id'):
                        session_id = self.client.server.thread.id
                        message_count = len(self.client.server.thread.messages) if hasattr(self.client.server.thread, 'messages') else 0
                        status_text += f"\nClient Session:\n"
                        status_text += f"  Session ID: {session_id}\n"
                        status_text += f"  Messages: {message_count}\n"
                        status_text += f"  Model: {self.client.config.model}\n"
                        status_text += f"  Executor: {self.client.config.executor}\n"
                    else:
                        status_text += f"\nClient Session:\n"
                        status_text += f"  Status: No active session\n"
                        status_text += f"  Model: {self.client.config.model}\n"
                        status_text += f"  Executor: {self.client.config.executor}\n"

                    # Add history info
                    history_count = len(self.client.input_history)
                    status_text += f"\nInput History:\n"
                    status_text += f"  Commands in history: {history_count}\n"

                    return CommandResult(success=True, message=status_text, data=health_data)
                else:
                    return CommandResult(
                        success=False,
                        message=f"Server returned status {response.status_code}"
                    )

        except httpx.ConnectError:
            return CommandResult(
                success=False,
                message=f"Cannot connect to server at {self.client.config.server_url}"
            )
        except Exception as e:
            return CommandResult(success=False, message=f"Status command error: {str(e)}")

    async def _handle_help(self, args: list) -> CommandResult:
        """Handle /help command"""
        help_text = """Available slash commands:

/usage          - Show token usage for current session
/usage global   - Show global usage across all sessions
/clear          - Clear conversation context and start fresh
/status         - Show server and client status
/help           - Show this help message

Slash commands are processed locally and don't require server round-trips."""

        return CommandResult(success=True, message=help_text)

    def get_available_commands(self) -> list:
        """Get list of available commands"""
        return list(self.commands.keys())