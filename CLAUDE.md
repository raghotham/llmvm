# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Python Commands
**Always use `uv run` for running anything related to Python.**

- **Server**: `uv run python -m llmvm.server`
- **Client**: `uv run python -m llmvm.client`
- **Install dependencies**: `uv sync` or `pip install -e .`
- **Install Playwright browsers**: `playwright install`

### Web Frontend Commands (llmvm-chat-studio)
Located in `web/llmvm-chat-studio/`:
- **Development**: `npm run dev`
- **Build**: `npm run build`
- **Lint**: `npm run lint`
- **Preview**: `npm run preview`

### JavaScript SDK Commands (js-llmvm-sdk)
Located in `web/js-llmvm-sdk/`:
- **Build**: `npm run build`
- **Link for development**: `npm link`

## High-Level Architecture

### Core Components

**Client-Server Architecture**: LLMVM operates with a client-server model where:
- **Client (`llmvm/client/`)**: CLI interface that handles user input, message rendering, and communication
- **Server (`llmvm/server/`)**: Coordinates tool execution, RAG, document search, and LLM interactions
- **Common (`llmvm/common/`)**: Shared components including LLM executors for different providers

### Key Architecture Patterns

**Continuation Passing Style Execution**: The core programming model follows:
1. Query → Natural language + `<helpers>` blocks
2. Python execution of `<helpers>` blocks
3. Replace `<helpers>` with `<helpers_result>`
4. Continue LLM completion until task complete

**Tool System**: Instead of traditional function calling, LLMVM allows LLMs to emit interleaved natural language and Python code in `<helpers>` blocks that get executed in a persistent Python runtime.

**Multi-LLM Support**: Executors in `llmvm/common/` support:
- Anthropic Claude (claude-sonnet-4, claude-opus-4, etc.)
- OpenAI GPT (4o, 4.1, o3, o4)
- Google Gemini (experimental)
- DeepSeek v3 (experimental)
- Amazon Nova (experimental)

### Key Directories

- **`llmvm/server/tools/`**: Contains specialized tool classes (browser automation, market data, search, etc.)
- **`llmvm/server/base_library/`**: Core library functions like content downloading, search, and source code analysis
- **`llmvm/server/prompts/`**: System prompts and execution templates
- **`llmvm/client/`**: CLI client with markdown rendering, custom completion, and terminal interaction
- **`web/`**: Web frontend (React/TypeScript) and JavaScript SDK

### Python Runtime System

**BCL (Base Class Library) (`llmvm/server/bcl.py`)**: Provides LLM-callable functions like:
- `llm_call()`: Delegate tasks to LLM with fresh call stack
- `llm_bind()`: Bind arbitrary data to function arguments
- `download()`: Web/PDF content retrieval via Playwright
- `result()`: Collect and present task results

**Execution Controller (`llmvm/server/python_execution_controller.py`)**: Manages code execution, error handling, and variable state in the Python runtime.

**Tools Integration**: Class-based tools maintain state between requests (see `browser.py` as example of stateful browser automation).

### Configuration

- **Config Location**: `~/.config/llmvm/config.yaml`
- **Environment Variables**: `LLMVM_EXECUTOR`, `LLMVM_MODEL`, `LLMVM_PROFILING`, etc.
- **API Keys**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.

### Web Frontend Architecture

**Tech Stack**: React 19 + TypeScript + Vite + Tailwind + shadcn/ui components
**Communication**: Uses JavaScript SDK to communicate with LLMVM server API
**Features**: Chat interface with code execution, markdown rendering, and real-time streaming

## Development Notes

- The codebase uses "continuation passing style" where LLM responses can contain both natural language and executable code
- Error correction system allows backtracking and re-writing code when execution fails
- Supports "compilation" of message threads into reusable, parameterized programs
- Browser automation via Playwright with optional headless mode configuration
- Rich terminal experience with image rendering (kitty/WezTerm recommended)