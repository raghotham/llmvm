import asyncio
import base64
import json
import os
from typing import Any, Awaitable, Callable, Optional, cast

import tiktoken
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.responses import ResponseContentPartAddedEvent, ResponseCompletedEvent

from llmvm.common.container import Container
from llmvm.common.helpers import Helpers
from llmvm.common.logging_helpers import messages_trace, setup_logging
from llmvm.common.object_transformers import ObjectTransformers
from llmvm.common.objects import (
    Assistant,
    AstNode,
    BrowserContent,
    Content,
    Executor,
    FileContent,
    HTMLContent,
    ImageContent,
    MarkdownContent,
    Message,
    PdfContent,
    System,
    TextContent,
    TokenNode,
    TokenStopNode,
    TokenThinkingNode,
    User,
    awaitable_none,
)
from llmvm.common.perf import TokenPerf, TokenStreamManager

logging = setup_logging()


class ResponseExecutor(Executor):
    """OpenAI Response API Executor - uses only the Responses API for proper token tracking"""

    def __init__(
        self,
        api_key: str = cast(str, Container().get_config_variable("OPENAI_API_KEY")),
        default_model: str = "gpt-5",
        api_endpoint: str = Container().get_config_variable("OPENAI_API_BASE", "OPENAI_API_BASE", "https://api.openai.com/v1"),
        default_max_input_len: int = 4000000,
        default_max_output_len: int = 128000,
        max_images: int = 20,
    ):
        super().__init__(
            default_model=default_model,
            api_endpoint=api_endpoint,
            api_key=api_key,
            default_max_input_len=default_max_input_len,
            default_max_output_len=default_max_output_len,
        )

        self.client = AsyncOpenAI(api_key=api_key, base_url=api_endpoint)
        self.api_key = api_key
        self.max_images = max_images

    def get_schema(self):
        return {
            'type': 'object',
            'properties': {
                'type': {'type': 'string', 'enum': ['response']},
                'model': {'type': 'string', 'description': 'Model to use for the response'},
                'messages': {
                    'type': 'array',
                    'items': {'type': 'object'},
                    'description': 'Array of message objects'
                },
                'max_completion_tokens': {'type': 'integer', 'description': 'Maximum tokens to generate'},
                'temperature': {'type': 'number', 'description': 'Sampling temperature'},
            },
            'required': ['type', 'messages'],
            'additionalProperties': False
        }

    def aexecute_direct(
        self,
        messages: list[Message],
        model: str,
        max_input_len: int,
        max_output_len: int,
        temperature: float = 0.0,
        stop_tokens: Optional[list[str]] = None,
        thinking: int = 0
    ) -> TokenStreamManager:
        """Execute using OpenAI Responses API - returns a coroutine"""
        return self._aexecute_direct_impl(messages, model, max_input_len, max_output_len, temperature, stop_tokens, thinking)

    async def _aexecute_direct_impl(
        self,
        messages: list[Message],
        model: str,
        max_input_len: int,
        max_output_len: int,
        temperature: float = 0.0,
        stop_tokens: Optional[list[str]] = None,
        thinking: int = 0
    ) -> TokenStreamManager:
        """Execute using OpenAI Responses API"""

        logging.debug(f"response_executor: using model={model} with Responses API")

        # Calculate prompt length for token tracking
        message_tokens = await self.count_tokens(messages)

        token_trace = TokenPerf(
            "aexecute_direct", "response", model, prompt_len=message_tokens
        )

        # Separate instructions (system) from input (user/assistant messages) for Responses API
        instructions_content = ""
        input_messages = []

        for message in messages:
            if isinstance(message, System):
                # Collect all system messages as instructions
                for content in message.message:
                    if isinstance(content, TextContent):
                        instructions_content += content.sequence + "\n"

            elif isinstance(message, User):
                content_parts = []
                for content in message.message:
                    if isinstance(content, TextContent):
                        content_parts.append({"type": "input_text", "text": content.sequence})
                    elif isinstance(content, ImageContent):
                        if content.url:
                            content_parts.append({
                                "type": "input_image",
                                "image_url": content.url
                            })
                        elif content.sequence:
                            b64_image = base64.b64encode(content.sequence).decode('utf-8')
                            content_parts.append({
                                "type": "input_image",
                                "image_url": f"data:image/png;base64,{b64_image}"
                            })

                input_messages.append({
                    "role": "user",
                    "content": content_parts if len(content_parts) > 1 else content_parts[0]["text"] if content_parts else ""
                })

            elif isinstance(message, Assistant):
                text_content = ""
                for content in message.message:
                    if isinstance(content, TextContent):
                        text_content += content.sequence

                input_messages.append({
                    "role": "assistant",
                    "content": text_content
                })

        # Models that don't support temperature in Responses API
        no_temperature_models = {'gpt-5'}

        # Build request parameters for Responses API
        params = {
            "model": model,
            "instructions": instructions_content.strip(),
            "input": input_messages,
            "max_output_tokens": max_output_len,
            "stream": True,
        }

        # Only add temperature if the model supports it
        if model not in no_temperature_models:
            params["temperature"] = temperature

        logging.debug(f"response_executor: calling client.responses.create with params={params}")

        # Use the actual Responses API
        response = await self.client.responses.create(**params)
        return TokenStreamManager(response, token_trace)

    async def aexecute(
        self,
        messages: list[Message],
        max_output_tokens: int = 16384,
        temperature: float = 1.0,
        stop_tokens: list[str] = [],
        model: Optional[str] = None,
        thinking: int = 0,
        stream_handler: Callable[[AstNode], Awaitable[None]] = awaitable_none,
    ) -> Assistant:
        """Main execution method"""

        logging.debug(f"response_executor: aexecute called with model={model}")

        model = model if model else self._default_model

        stream = self.aexecute_direct(
            messages=messages,
            model=model,
            max_input_len=self.default_max_input_len,
            max_output_len=max_output_tokens,
            temperature=temperature,
            stop_tokens=stop_tokens,
            thinking=thinking
        )

        text_response: str = ""
        thinking_response: str = ""
        perf = None
        final_usage = None
        final_token = None

        try:
            async with await stream as stream_async:  # type: ignore
                async for token in stream_async:
                    final_token = token

                    # Capture usage information from ResponseCompletedEvent
                    if isinstance(token.underlying, ResponseCompletedEvent) and token.underlying.response.usage:
                        final_usage = token.underlying.response.usage
                        logging.debug(f"response_executor: captured usage from token: {final_usage}")

                    if token.thinking:
                        logging.debug(f"response_executor: thinking chunk: '{token.token}'")
                        await stream_handler(TokenThinkingNode(token.token))
                        thinking_response += token.token
                    else:
                        logging.debug(f"response_executor: text chunk: '{token.token}'")
                        await stream_handler(TokenNode(token.token))
                        text_response += token.token

                await stream_handler(TokenStopNode())
                perf = stream_async.perf
        except Exception as e:
            logging.error(f"response_executor: streaming error: {e}")
            await stream_handler(TokenStopNode())
            raise

        _ = await stream_async.get_final_message()
        perf.log()

        # Extract token usage from final_usage (should always be present with Responses API)
        if final_usage:
            # Extract token counts from Responses API usage
            input_tokens = final_usage.input_tokens
            output_tokens = final_usage.output_tokens
            reasoning_tokens = final_usage.output_tokens_details.reasoning_tokens if final_usage.output_tokens_details else 0
            actual_total_tokens = final_usage.total_tokens

            logging.debug(f"response_executor: usage - input={input_tokens}, output={output_tokens}, reasoning={reasoning_tokens}, total={actual_total_tokens}")
        else:
            # Fallback to perf tokens if no usage found
            actual_total_tokens = perf.total_tokens
            logging.debug(f"response_executor: no final_usage captured, using perf.total_tokens={perf.total_tokens}")

        logging.debug(f"response_executor: creating Assistant with total_tokens={actual_total_tokens}")

        assistant = Assistant(
            message=TextContent(text_response.strip()),
            **({'thinking': thinking_response} if thinking_response else {}),
            total_tokens=actual_total_tokens,
            perf_trace=perf if Container().get_config_variable('LOG_PERFORMANCE') else None,
            underlying=perf.object if hasattr(perf, 'object') else None,
        )

        return assistant

    async def count_tokens(self, messages: list[Message]) -> int:
        """Count tokens in messages"""
        model = self._default_model
        try:
            encoding = tiktoken.encoding_for_model(model.replace('gpt-5', 'gpt-4'))
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        token_count = 0
        for message in messages:
            for content in message.message:
                if isinstance(content, TextContent):
                    token_count += len(encoding.encode(content.sequence))

        return token_count

    def get_executor_name(self) -> str:
        return "response"

    def user_token(self) -> str:
        return "user"

    def assistant_token(self) -> str:
        return "assistant"

    def append_token(self) -> str:
        return "||APPEND||"

    def scratchpad_token(self) -> str:
        return "||SCRATCHPAD||"

    def name(self) -> str:
        return "response"

    def to_dict(self, message: Message) -> dict:
        """Convert message to dictionary format for API"""
        result = {}

        if isinstance(message, User):
            result['role'] = 'user'
            content = ""
            for msg_content in message.message:
                if isinstance(msg_content, TextContent):
                    content += msg_content.sequence
            result['content'] = content

        elif isinstance(message, Assistant):
            result['role'] = 'assistant'
            content = ""
            for msg_content in message.message:
                if isinstance(msg_content, TextContent):
                    content += msg_content.sequence
            result['content'] = content

        elif isinstance(message, System):
            result['role'] = 'system'
            content = ""
            for msg_content in message.message:
                if isinstance(msg_content, TextContent):
                    content += msg_content.sequence
            result['content'] = content

        return result

    def from_dict(self, message: dict) -> Message:
        """Convert dictionary from API to Message object"""
        role = message.get('role', '')
        content = message.get('content', '')

        if role == 'user':
            return User([TextContent(content)])
        elif role == 'assistant':
            return Assistant([TextContent(content)])
        elif role == 'system':
            return System([TextContent(content)])
        else:
            raise ValueError(f"Unknown role: {role}")

    def unpack_and_wrap_messages(self, messages: list[Message], model: Optional[str] = None) -> list[dict]:
        """Convert list of Messages to list of dicts for API"""
        return [self.to_dict(msg) for msg in messages]

    async def count_tokens_dict(self, messages: list[dict], model: str) -> int:
        """Count tokens in dictionary messages"""
        try:
            encoding = tiktoken.encoding_for_model(model.replace('gpt-5', 'gpt-4'))
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        token_count = 0
        for msg in messages:
            if 'content' in msg:
                token_count += len(encoding.encode(msg['content']))
        return token_count

    def execute(
        self,
        messages: list[Message],
        model: str,
        max_input_len: int,
        max_output_len: int,
        temperature: float = 0.0,
        stream_handler: Optional[Callable] = None,
        stop_tokens: Optional[list[str]] = None,
        thinking: int = 0
    ) -> Assistant:
        """Synchronous execute wrapper"""
        import asyncio
        return asyncio.run(self.aexecute(
            messages, model, max_input_len, max_output_len,
            temperature, stream_handler or (lambda x: None), stop_tokens, thinking
        ))
