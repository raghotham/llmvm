"""
Execution continuation system for bash approval flow.

When a bash command needs approval, we pause the execution and store the context.
After approval, we resume execution with the BashResult replacing the ApprovalRequest.
"""

import uuid
import asyncio
import logging
from typing import Dict, Optional, Any, Callable, Awaitable
from dataclasses import dataclass

from llmvm.common.objects import ApprovalRequest, AstNode
from llmvm.server.bash_helper import BashResult

logging = logging.getLogger(__name__)

@dataclass
class ExecutionContext:
    """Complete stored execution context for continuation after approval"""
    # Core execution data
    approval_request: ApprovalRequest
    execution_id: str
    code_execution_result: list  # The original result list with ApprovalRequest
    runtime_state: Any
    messages: list

    # Original request parameters needed for continuation
    thread_id: int
    temperature: float
    model: str
    max_output_tokens: Optional[int]
    compression: Any  # TokenCompressionMethod
    cookies: list[dict]
    helpers: list  # list[Callable]
    template_args: dict[str, Any]
    thinking: bool

    # Response handling
    stream_handler: Callable[[AstNode], Awaitable[None]]
    original_queue: Any  # The original response queue
    original_controller: Any  # Reference to the original ExecutionController
    continuation_callback: Optional[Callable] = None

class ExecutionContinuationRegistry:
    """Registry for paused executions waiting for bash approval"""

    _instance: Optional['ExecutionContinuationRegistry'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._pending: Dict[str, ExecutionContext] = {}
        return cls._instance

    def pause_execution(self,
                       approval_request: ApprovalRequest,
                       code_execution_result: list,
                       runtime_state: Any,
                       messages: list,
                       # Original request context
                       thread_id: int,
                       temperature: float,
                       model: str,
                       max_output_tokens: Optional[int],
                       compression: Any,
                       cookies: list[dict],
                       helpers: list,
                       template_args: dict[str, Any],
                       thinking: bool,
                       # Response handling
                       stream_handler: Callable[[AstNode], Awaitable[None]],
                       original_queue: Any,
                       original_controller: Any) -> str:
        """
        Pause execution and store context for later resumption.

        Returns:
            execution_id: Unique ID to resume execution later
        """
        execution_id = str(uuid.uuid4())

        # Add execution_id to approval request for client to send back
        approval_request.execution_id = execution_id

        context = ExecutionContext(
            approval_request=approval_request,
            execution_id=execution_id,
            code_execution_result=code_execution_result.copy(),
            runtime_state=runtime_state,
            messages=messages.copy(),
            # Original request context
            thread_id=thread_id,
            temperature=temperature,
            model=model,
            max_output_tokens=max_output_tokens,
            compression=compression,
            cookies=cookies.copy(),
            helpers=helpers.copy(),
            template_args=template_args.copy(),
            thinking=thinking,
            # Response handling
            stream_handler=stream_handler,
            original_queue=original_queue,
            original_controller=original_controller
        )

        self._pending[execution_id] = context

        logging.info(f"🔍 CONTINUATION: Paused execution {execution_id} for approval")
        return execution_id


    async def resume_execution(self, execution_id: str, bash_result: BashResult,
                                        controller: Any, stream_handler: Any) -> tuple[bool, list]:
        """
        Resume paused execution within the current request context.

        This method reuses the current controller and stream_handler instead of
        creating a new execution context, allowing for proper streaming.
        """
        if execution_id not in self._pending:
            logging.error(f"🔍 CONTINUATION: No pending execution found for {execution_id}")
            return (False, [])

        context = self._pending[execution_id]

        # Replace ApprovalRequest with BashResult in the execution results
        updated_results = []
        replaced_count = 0
        logging.info(f"🔍 CONTINUATION: Processing {len(context.code_execution_result)} execution results")

        for i, item in enumerate(context.code_execution_result):
            logging.info(f"🔍   Result {i}: {type(item).__name__}")

            if isinstance(item, ApprovalRequest) and item.execution_id == execution_id:
                # Replace ApprovalRequest with BashResult
                updated_results.append(bash_result)
                replaced_count += 1
                logging.info(f"🔍   REPLACED ApprovalRequest with BashResult at position {i}")
                logging.info(f"🔍   BashResult: stdout='{bash_result.stdout[:100]}...', exit_code={bash_result.exit_code}")
            else:
                updated_results.append(item)

        logging.info(f"🔍 CONTINUATION: Replaced {replaced_count} ApprovalRequest(s) with BashResult")

        # Build the continuation message with results
        from llmvm.common.helpers import Helpers
        from llmvm.common.objects import TextContent, User

        # Build content messages with clear context about what happened
        content_messages = [
            TextContent("The bash command you requested has been completed. Here are the results:"),
            TextContent("<helpers_result>")
        ]

        for c in updated_results:
            from llmvm.common.objects import Content
            if isinstance(c, Content):
                content_messages.append(c)
            else:
                content_messages.append(TextContent(Helpers.str_get_str(c)))

        content_messages.extend([
            TextContent("</helpers_result>"),
            TextContent("Please process these results and provide a complete response to the user's original request. Do not run the command again.")
        ])

        # Create User message with the results
        completed_code_user_message = User(content_messages, hidden=False)

        # Add the completed message to the message list
        continuation_messages = context.messages.copy()
        continuation_messages.append(completed_code_user_message)

        logging.info(f"🔍 CONTINUATION: Built continuation with {len(continuation_messages)} messages")

        # Clean up pending execution
        del self._pending[execution_id]

        # Continue execution using the provided controller and stream_handler
        try:
            logging.info(f"🔍 CONTINUATION: Continuing execution with provided controller")

            # Convert messages to the format expected by aexecute_continuation
            from llmvm.common.objects import MessageModel
            converted_messages = [MessageModel.to_message(msg) if hasattr(msg, 'content') else msg
                                for msg in continuation_messages]

            result_messages, updated_runtime_state = await controller.aexecute_continuation(
                messages=converted_messages,
                temperature=context.temperature,
                model=context.model,
                max_output_tokens=context.max_output_tokens,
                compression=context.compression,
                stream_handler=stream_handler,  # Use the current request's stream handler
                template_args=context.template_args,
                helpers=context.helpers,
                cookies=context.cookies,
                runtime_state=context.runtime_state,
                thinking=context.thinking
            )

            logging.info(f"🔍 CONTINUATION: Execution completed successfully with {len(result_messages)} result messages")
            return (True, result_messages)

        except Exception as e:
            logging.error(f"🔍 CONTINUATION: Failed to continue execution: {e}")
            import traceback
            traceback.print_exc()
            return (False, [])


    def get_pending_count(self) -> int:
        """Get number of pending executions"""
        return len(self._pending)