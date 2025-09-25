#!/usr/bin/env python3
"""
Bash Helper for LLMVM - Provides safe bash command execution with approval and sandboxing.

Inspired by query-muse's sophisticated sandbox and approval system.
"""

import os
import shlex
import subprocess
import time
import signal
from dataclasses import dataclass
from typing import Optional, List, Set
import sys

from llmvm.common.logging_helpers import setup_logging
from llmvm.common.container import Container

logging = setup_logging()


@dataclass
class BashResult:
    """Result of executing a bash command."""
    stdout: str
    stderr: str
    exit_code: int
    command: str
    execution_time: float
    was_sandboxed: bool = False
    was_approved: bool = True

    def get_str(self) -> str:
        """Return stdout and stderr (if present) for use with result()."""
        if self.stderr:
            return f"{self.stdout}\nSTDERR:\n{self.stderr}"
        return self.stdout


class CommandSafetyAssessor:
    """Assesses the safety of bash commands."""

    def __init__(self):
        """Initialize with configuration."""
        try:
            container = Container(throw=False)
            # Check if container was properly initialized
            if hasattr(container, 'configuration'):
                config = container.get('bash_helper', {})
            else:
                config = {}  # No config file available

            # Load safe commands from config, with fallback defaults
            self.known_safe_commands = set(config.get('known_safe_commands', [
                'ls', 'cat', 'head', 'tail', 'grep', 'find', 'pwd', 'echo',
                'which', 'whereis', 'date', 'whoami', 'id', 'uname', 'uptime'
            ]))

            # Load dangerous commands from config, with fallback defaults
            self.dangerous_commands = set(config.get('dangerous_commands', [
                'rm', 'rmdir', 'mv', 'cp', 'dd', 'mkfs', 'fdisk', 'mount',
                'umount', 'chmod', 'chown', 'su', 'sudo', 'passwd'
            ]))

        except (ValueError, FileNotFoundError):
            # Fallback to defaults if config is not available
            self.known_safe_commands = {
                'ls', 'cat', 'head', 'tail', 'grep', 'find', 'pwd', 'echo',
                'which', 'whereis', 'date', 'whoami', 'id', 'uname', 'uptime'
            }
            self.dangerous_commands = {
                'rm', 'rmdir', 'mv', 'cp', 'dd', 'mkfs', 'fdisk', 'mount',
                'umount', 'chmod', 'chown', 'su', 'sudo', 'passwd'
            }

    def is_known_safe(self, command: str) -> bool:
        """Check if a command is known to be safe for auto-approval."""
        try:
            # Parse the command to get the base command
            tokens = shlex.split(command)
            if not tokens:
                return False

            base_command = os.path.basename(tokens[0])
            return base_command in self.known_safe_commands

        except ValueError:
            # Invalid shell syntax
            return False

    def needs_approval(self, command: str) -> bool:
        """Check if a command needs explicit approval."""
        try:
            tokens = shlex.split(command)
            if not tokens:
                return True

            base_command = os.path.basename(tokens[0])

            # If it's a known safe command, no approval needed
            if base_command in self.known_safe_commands:
                return False

            # If it's a known dangerous command, definitely needs approval
            if base_command in self.dangerous_commands:
                return True

            # For unknown commands, err on the side of caution
            return True

        except ValueError:
            # Invalid shell syntax, needs approval
            return True


class ApprovalSystem:
    """Handles command approval requests."""

    def __init__(self):
        """Initialize with configuration."""
        try:
            container = Container(throw=False)
            # Check if container was properly initialized
            if hasattr(container, 'configuration'):
                config = container.get('bash_helper', {})
            else:
                config = {}  # No config file available
            self.session_approvals = config.get('session_approvals', True)
        except (ValueError, FileNotFoundError):
            self.session_approvals = True

        self.approved_commands: Set[str] = set()  # Session-persistent approvals

    def request_approval(self, command: str, cwd: str, justification: str = None) -> bool:
        """Request approval for a command execution."""
        # Check if already approved for this session (only if session approvals enabled)
        if self.session_approvals and command in self.approved_commands:
            logging.debug(f"Command '{command}' already approved for session")
            return True

        # For MVP, we'll implement a simple terminal prompt
        # Later this can be extended to support web interface
        return self._terminal_approval_prompt(command, cwd, justification)

    def _terminal_approval_prompt(self, command: str, cwd: str, justification: str = None) -> bool:
        """Show terminal prompt for command approval."""
        # Check if we have an interactive terminal
        import sys
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            # Running in non-interactive mode (e.g., server mode)
            # SECURITY: Never auto-approve commands in non-interactive mode
            # This should be handled by proper client-server approval flow
            logging.warning(f"Command approval required but no interactive terminal available: {command}")
            logging.warning("Denying command execution for security. Implement proper approval flow.")
            return False

        print(f"\n🔐 Bash Command Approval Required")
        print(f"Command: {command}")
        print(f"Working Directory: {cwd}")
        if justification:
            print(f"Justification: {justification}")
        print("\nOptions:")
        print("  (a)pprove - Execute this command once")
        print("  (s)ession - Execute and auto-approve for this session")
        print("  (d)eny - Do not execute this command")

        while True:
            try:
                response = input("Your choice [a/s/d]: ").lower().strip()
                if response in ['a', 'approve']:
                    return True
                elif response in ['s', 'session']:
                    if self.session_approvals:
                        self.approved_commands.add(command)
                    return True
                elif response in ['d', 'deny']:
                    return False
                else:
                    print("Please enter 'a', 's', or 'd'")
            except (KeyboardInterrupt, EOFError):
                print("\nOperation cancelled.")
                return False


def execute_bash_command(
    command: str,
    timeout: Optional[int] = None,
    approval_mode: Optional[str] = None,
    sandbox_mode: Optional[str] = None,
    justification: str = None,
    cwd: str = None,
    approval_system: Optional[ApprovalSystem] = None
) -> BashResult:
    """
    Execute a bash command with approval and sandboxing.

    Args:
        command: The bash command to execute
        timeout: Timeout in milliseconds (uses config default if None)
        approval_mode: "never", "on_request", "on_failure", "unless_trusted" (uses config default if None)
        sandbox_mode: "read_only", "workspace_write", "danger_full_access" (uses config default if None)
        justification: Reason for executing this command
        cwd: Working directory (defaults to current)
        approval_system: Approval system to use (for testing)

    Returns:
        BashResult with execution details
    """
    start_time = time.time()
    cwd = cwd or os.getcwd()

    # Load configuration defaults
    try:
        container = Container(throw=False)
        # Check if container was properly initialized
        if hasattr(container, 'configuration'):
            config = container.get('bash_helper', {})
        else:
            config = {}  # No config file available

        timeout = timeout if timeout is not None else config.get('default_timeout', 10000)
        approval_mode = approval_mode if approval_mode is not None else config.get('default_approval_mode', 'on_request')
        sandbox_mode = sandbox_mode if sandbox_mode is not None else config.get('default_sandbox_mode', 'workspace_write')

    except (ValueError, FileNotFoundError):
        # Fallback to defaults if config is not available
        timeout = timeout if timeout is not None else 10000
        approval_mode = approval_mode if approval_mode is not None else 'on_request'
        sandbox_mode = sandbox_mode if sandbox_mode is not None else 'workspace_write'

    # Initialize systems
    if approval_system is None:
        approval_system = ApprovalSystem()

    safety_assessor = CommandSafetyAssessor()

    # Safety assessment
    needs_approval = False
    if approval_mode == "never":
        needs_approval = False
    elif approval_mode == "unless_trusted":
        needs_approval = not safety_assessor.is_known_safe(command)
    elif approval_mode == "on_request":
        needs_approval = safety_assessor.needs_approval(command)
    elif approval_mode == "on_failure":
        needs_approval = False  # Try first, ask for approval on failure

    # Request approval if needed
    if needs_approval:
        approved = approval_system.request_approval(command, cwd, justification)
        if not approved:
            execution_time = time.time() - start_time
            return BashResult(
                stdout="",
                stderr="Command denied by user",
                exit_code=1,
                command=command,
                execution_time=execution_time,
                was_approved=False
            )

    # Execute the command
    try:
        # For MVP, we'll use basic subprocess execution
        # Later we can add sandboxing for macOS
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout / 1000.0,  # Convert to seconds
            cwd=cwd
        )

        execution_time = time.time() - start_time

        return BashResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.returncode,
            command=command,
            execution_time=execution_time,
            was_approved=True
        )

    except subprocess.TimeoutExpired:
        execution_time = time.time() - start_time
        return BashResult(
            stdout="",
            stderr=f"Command timed out after {timeout}ms",
            exit_code=124,  # Standard timeout exit code
            command=command,
            execution_time=execution_time,
            was_approved=True
        )

    except Exception as e:
        execution_time = time.time() - start_time
        return BashResult(
            stdout="",
            stderr=f"Execution error: {str(e)}",
            exit_code=1,
            command=command,
            execution_time=execution_time,
            was_approved=True
        )


def execute_bash_command_for_testing(
    command: str,
    timeout: Optional[int] = None,
    approval_system=None,
    cwd: str = None,
    justification: str = None
) -> BashResult:
    """
    Test-friendly version of bash command execution.
    Used by unit tests with fake approval system.
    """
    # Special handling for test approval systems that have different interface
    class TestApprovalSystemAdapter(ApprovalSystem):
        def __init__(self, fake_approval_system):
            super().__init__()
            self.fake_system = fake_approval_system

        def request_approval(self, command: str, cwd: str, justification: str = None) -> bool:
            return self.fake_system.request_approval(command, cwd, justification)

    # If we have a test approval system, adapt it
    if approval_system and hasattr(approval_system, 'request_approval'):
        approval_system = TestApprovalSystemAdapter(approval_system)

    return execute_bash_command(
        command=command,
        timeout=timeout,
        approval_mode="on_request",
        sandbox_mode="workspace_write",
        justification=justification,
        cwd=cwd,
        approval_system=approval_system
    )