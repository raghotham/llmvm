# LLMVM Bash Helper Implementation Plan

## Phase 1: Core Implementation (Weeks 1-2)

### A. Add Bash Helper to BCL
- Add `bash()` function to `llmvm/server/runtime.py` following existing pattern (`llm_call`, `result`, `download`)
- Add corresponding method to `Runtime` class
- Define `BashResult` dataclass for return values

### B. Basic Command Execution
- Command parsing and validation using `shlex` and basic string analysis
- Subprocess execution with timeout support
- stdout/stderr capture and formatting
- Exit code handling and error reporting

### C. Terminal Approval System
- Safety assessment: auto-approve known-safe read-only commands
- Terminal prompts showing: command, CWD, justification
- Session memory for approved commands (stored in runtime state)
- Support approval modes: `never`, `on_request`, `on_failure`, `unless_trusted`

## Phase 2: macOS Sandboxing (Weeks 3-4)

### A. macOS Seatbelt Integration
- Implement macOS Seatbelt sandbox using query-muse patterns
- Create sandbox profiles for different permission levels
- Execute commands via `sandbox-exec` with appropriate profiles

### B. Sandbox Policies
- `read_only`: Full filesystem read access, no writes
- `workspace_write`: Read-only + write access to current working directory
- `danger_full_access`: No restrictions (explicit user choice)

### C. Error Handling & Escalation
- Detect sandbox failures and offer unsandboxed execution
- Graceful fallback when sandboxing is unavailable
- Clear error messages explaining sandbox restrictions

## Phase 3: Configuration & Polish (Week 5)

### A. Configuration System
- Add bash_helper section to `~/.config/llmvm/config.yaml`
- Default approval and sandbox modes
- Known safe commands list
- Session approval persistence setting

### B. Command Validation
- Known safe commands: `ls`, `cat`, `grep`, `head`, `tail`, `find` (read-only operations)
- Basic argument validation to prevent dangerous patterns
- Path validation to keep operations within workspace

### C. Documentation & Testing
- Update BCL documentation with bash helper usage
- Add unit tests for core functionality
- Integration tests with different sandbox modes

## Later/TODO Items

### Web Interface Integration
- Approval prompts through WebSocket to web frontend
- Visual command preview with syntax highlighting
- Approval history and session management

### Advanced Features
- Command templates and pre-approved patterns
- Audit logging for security tracking
- Performance metrics and monitoring
- Advanced error recovery mechanisms

### Cross-Platform Support
- Linux sandboxing using namespaces/seccomp
- Windows support (if needed)
- Platform-specific command validation

### Advanced Policy Enforcement
- Filesystem access controls beyond basic sandbox
- Network access restrictions
- Resource limits (CPU, memory, time)
- Fine-grained permission system