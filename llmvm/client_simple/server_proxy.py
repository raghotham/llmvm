"""Server communication layer for simple client"""
import base64
import json
import os
from dataclasses import dataclass
from typing import AsyncIterator, Optional

import httpx
import jsonpickle

# Import the proper data models
from llmvm.common.objects import SessionThreadModel, MessageModel, User, TextContent, TokenNode, TokenStopNode, StreamingStopNode, StreamNode, ApprovalRequest


@dataclass
class Chunk:
    """Represents a chunk of data from the server"""
    type: str  # "text", "image", "code", "error", "approval"
    content: any
    metadata: Optional[dict] = None


class ServerProxy:
    """Handles communication with the LLMVM server"""

    def __init__(self, config):
        self.config = config
        self.server_url = config.server_url
        self.is_streaming = False
        self.current_request: Optional[httpx.Response] = None

        # Maintain conversation state (server-managed)
        self.thread: Optional[SessionThreadModel] = None

    async def stream_chat(self, message: str) -> AsyncIterator[Chunk]:
        """Stream chat completion from server"""
        self.is_streaming = True

        try:
            # Configure timeout
            timeout_config = httpx.Timeout(
                timeout=self.config.server_timeout,
                connect=10.0  # Always use 10s connect timeout
            ) if self.config.server_timeout else httpx.Timeout(None)

            async with httpx.AsyncClient(timeout=timeout_config) as client:
                # Create user message
                user_message = User(TextContent(message))
                user_message_model = MessageModel.from_message(user_message)

                # Create or update thread
                if self.thread is None:
                    self.config.debug_print("Creating new thread - no existing thread found")
                    # Create new thread for first message
                    self.thread = SessionThreadModel(
                        id=-1,  # Server will assign ID
                        title="",
                        executor=self.config.executor,
                        api_endpoint="",
                        api_key="",
                        model=self.config.model,
                        compression="",
                        temperature=0.0,
                        stop_tokens=[],
                        output_token_len=0,
                        current_mode=self.config.mode,
                        thinking=0,
                        compile_prompt="",
                        cookies=[],
                        messages=[user_message_model],
                        locals_dict={}
                    )
                else:
                    self.config.debug_print(f"Using existing thread with {len(self.thread.messages)} messages, id={self.thread.id}")
                    # Add new user message to existing thread
                    self.thread.messages.append(user_message_model)

                # Convert to dict for JSON serialization
                payload = self.thread.model_dump()

                self.config.log_to_file(f"[SERVER_PROXY] Request payload: {payload}")
                self.config.debug_print(f"Sending request to {self.server_url}/v1/tools/completions")

                # Send request to server - use tools endpoint for database access
                request = client.stream(
                    "POST",
                    f"{self.server_url}/v1/tools/completions",
                    json=payload,
                    headers={"Accept": "text/event-stream"}
                )

                async with request as response:
                    self.current_request = response

                    # Check response status
                    if response.status_code != 200:
                        error_text = await response.aread()
                        error_msg = f"Server error ({response.status_code}): {error_text.decode()}"
                        self.config.log_to_file(f"[SERVER_PROXY] {error_msg}")
                        yield Chunk(
                            type="error",
                            content=error_msg
                        )
                        return

                    # Stream response lines
                    async for line in response.aiter_lines():
                        if not self.is_streaming:  # Check if interrupted
                            break

                        chunk = self._parse_sse_line(line)
                        if chunk:
                            yield chunk

        except httpx.ConnectError:
            yield Chunk(
                type="error",
                content=f"Cannot connect to server at {self.server_url}. "
                       f"Make sure server is running (uv run llmvm --status)"
            )
        except httpx.TimeoutException:
            yield Chunk(
                type="error",
                content=f"Request timed out after {self.config.server_timeout}s"
            )
        except Exception as e:
            if self.is_streaming:  # Only show error if not interrupted
                yield Chunk(type="error", content=str(e))
        finally:
            self.is_streaming = False
            self.current_request = None

    def interrupt(self):
        """Interrupt current streaming request"""
        self.is_streaming = False
        if self.current_request:
            try:
                # Close the response stream
                self.current_request.aclose()
            except:
                pass

    def reset_conversation(self):
        """Reset the conversation history"""
        self.thread = None

    async def send_approval_response(self, approval_request: ApprovalRequest, approved: bool) -> AsyncIterator[Chunk]:
        """Send approval response back to server and resume execution"""
        if not self.thread:
            yield Chunk(type="error", content="No active thread for approval response")
            return

        try:
            # Update thread with approval response
            self.thread.execution_id = approval_request.execution_id
            self.thread.approval_response = {
                "approved": approved,
                "command": approval_request.command,
                "working_directory": approval_request.working_directory,
                "justification": approval_request.justification
            }

            # Configure timeout
            timeout_config = httpx.Timeout(
                timeout=self.config.server_timeout,
                connect=10.0
            ) if self.config.server_timeout else httpx.Timeout(None)

            async with httpx.AsyncClient(timeout=timeout_config) as client:
                # Convert to dict for JSON serialization
                payload = self.thread.model_dump()

                self.config.log_to_file(f"[SERVER_PROXY] Sending approval response: approved={approved}")
                self.config.debug_print(f"Sending approval response to {self.server_url}/v1/tools/completions")

                # Send request to server
                request = client.stream(
                    "POST",
                    f"{self.server_url}/v1/tools/completions",
                    json=payload,
                    headers={"Accept": "text/event-stream"}
                )

                async with request as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        error_msg = f"Server error ({response.status_code}): {error_text.decode()}"
                        self.config.log_to_file(f"[SERVER_PROXY] {error_msg}")
                        yield Chunk(type="error", content=error_msg)
                        return

                    # Stream response lines
                    async for line in response.aiter_lines():
                        chunk = self._parse_sse_line(line)
                        if chunk:
                            yield chunk

        except Exception as e:
            yield Chunk(type="error", content=f"Approval response failed: {e}")
        finally:
            # Clear approval fields after completion
            if self.thread:
                self.thread.execution_id = ""
                self.thread.approval_response = {}

    def _parse_sse_line(self, line: str) -> Optional[Chunk]:
        """Parse Server-Sent Events line into Chunk"""
        if not line:
            return None

        self.config.debug_print(f"SSE line: {line[:100]}...")

        # Handle SSE format
        if not line.startswith("data: "):
            return None

        if line == "data: [DONE]":
            self.config.debug_print("Stream complete")
            return None

        try:
            # Parse JSON data
            json_str = line[6:]  # Remove "data: " prefix

            # First try jsonpickle for LLMVM TokenNode objects
            try:
                if json_str.startswith('{"py/object":'):
                    data = jsonpickle.decode(json_str)

                    # Handle LLMVM StreamNode objects (for binary data like images)
                    if isinstance(data, StreamNode):
                        if data.type == 'bytes':
                            # This is binary image data from BCL.generate_graph_image()
                            return Chunk(
                                type="image",
                                content=data.obj,  # The raw image bytes
                                metadata={"source": "stream_node"}
                            )
                        else:
                            # Other stream node types, convert to string
                            return Chunk(type="text", content=str(data.obj))
                    # Handle LLMVM ApprovalRequest objects
                    elif isinstance(data, ApprovalRequest):
                        return Chunk(
                            type="approval",
                            content=data,
                            metadata={
                                "command": data.command,
                                "working_directory": data.working_directory,
                                "justification": data.justification,
                                "execution_id": data.execution_id
                            }
                        )
                    # Handle LLMVM TokenNode objects
                    elif isinstance(data, TokenNode):
                        return Chunk(type="text", content=data.token)
                    elif isinstance(data, (TokenStopNode, StreamingStopNode)):
                        return None  # Stop nodes don't produce visible output
                    else:
                        # Other LLMVM objects, convert to string
                        return Chunk(type="text", content=str(data))
            except Exception:
                pass

            # Fallback to regular JSON parsing
            data = json.loads(json_str)

            # Check if this is a SessionThreadModel (final response from server)
            if isinstance(data, dict) and "id" in data and "messages" in data and "executor" in data:
                try:
                    # This is the updated thread from the server - capture it
                    updated_thread = SessionThreadModel(**data)
                    self.thread = updated_thread
                    self.config.debug_print(f"Captured updated thread with {len(updated_thread.messages)} messages")
                    return None  # Don't render the raw thread data
                except Exception as e:
                    self.config.debug_print(f"Failed to parse SessionThreadModel: {e}")

            # Handle OpenAI-compatible format
            if "choices" in data:
                choice = data["choices"][0]

                # Check for content
                delta = choice.get("delta", {})
                content = delta.get("content", "")

                if content:
                    return Chunk(type="text", content=content)

                # Check for finish reason
                if choice.get("finish_reason"):
                    self.config.debug_print(f"Finish reason: {choice['finish_reason']}")

            # Handle custom LLMVM formats
            if "type" in data:
                content_type = data["type"]

                if content_type == "image":
                    # Handle base64 encoded image
                    image_data = data.get("content", "")
                    if isinstance(image_data, str):
                        # Decode base64
                        image_bytes = base64.b64decode(image_data)
                    else:
                        image_bytes = image_data

                    return Chunk(
                        type="image",
                        content=image_bytes,
                        metadata=data.get("metadata")
                    )

                elif content_type == "code":
                    return Chunk(
                        type="code",
                        content=data.get("content", ""),
                        metadata={"language": data.get("language")}
                    )

                elif content_type == "error":
                    return Chunk(
                        type="error",
                        content=data.get("content", "Unknown error")
                    )

                else:
                    # Default to text
                    return Chunk(
                        type="text",
                        content=data.get("content", ""),
                        metadata=data.get("metadata")
                    )

            # Handle helpers_result format (special LLMVM format)
            if "helpers_result" in data:
                result = data["helpers_result"]
                if "ImageContent" in str(result):
                    # Extract image data
                    return Chunk(type="text", content=f"[Image result: {result}]")
                else:
                    return Chunk(type="text", content=str(result))

        except json.JSONDecodeError as e:
            self.config.debug_print(f"JSON decode error: {e}")
            # Return the raw line as text if we can't parse it
            if line.startswith("data: "):
                return Chunk(type="text", content=line[6:])

        return None

    async def check_health(self) -> bool:
        """Check if server is healthy"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.server_url}/health",
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("status") == "healthy"
        except:
            pass
        return False