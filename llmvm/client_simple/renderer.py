"""Simple content rendering with Rich support"""
import sys
import subprocess
import tempfile
from datetime import datetime
from typing import Optional
from enum import Enum

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.live import Live
from rich.panel import Panel
from .themes import create_rich_theme, get_syntax_theme, detect_terminal_background


class RenderState(Enum):
    """Renderer state machine states"""
    STREAMING_TEXT = "streaming_text"
    TAG_BEGIN_DETECTED = "tag_begin_detected"
    STREAMING_CODE = "streaming_code"
    STREAMING_RESULT = "streaming_result"
    TAG_END_DETECTED = "tag_end_detected"


class TagType(Enum):
    """Types of tags we can detect"""
    HELPERS_OPEN = "<helpers>"
    HELPERS_CLOSE = "</helpers>"
    HELPERS_RESULT_OPEN = "<helpers_result>"
    HELPERS_RESULT_CLOSE = "</helpers_result>"
    COMPLETE_CLOSE = "</complete>"

    @classmethod
    def from_string(cls, tag_str: str) -> Optional['TagType']:
        """Convert string to TagType"""
        for tag_type in cls:
            if tag_type.value == tag_str:
                return tag_type
        return None

    @property
    def is_opening(self) -> bool:
        """Check if this is an opening tag"""
        return not self.value.startswith("</")

    @property
    def is_closing(self) -> bool:
        """Check if this is a closing tag"""
        return self.value.startswith("</")

    @property
    def is_helpers(self) -> bool:
        """Check if this is a helpers tag (not helpers_result)"""
        return "helpers_result" not in self.value

    @property
    def is_helpers_result(self) -> bool:
        """Check if this is a helpers_result tag"""
        return "helpers_result" in self.value


class Renderer:
    def __init__(self, config):
        self.config = config

        # Detect terminal theme and create Rich theme
        self.background = detect_terminal_background()
        self.theme = create_rich_theme(self.background)
        self.syntax_theme = get_syntax_theme(self.background)

        self.console = Console(theme=self.theme)

        # Response state
        self.in_response = False
        self.streaming_enabled = not config.disable_streaming

        # State machine
        self.state = RenderState.STREAMING_TEXT
        self.streamed_line_count = 0  # Track lines streamed for clearing

        # Buffers
        self.full_buffer = ""  # Complete accumulated text
        self.current_buffer = ""  # Current section buffer

        # Tag detection with sliding window buffer
        self.token_window = []  # Keep last 4 tokens for tag detection
        self.last_detected_tag: Optional[TagType] = None  # Track what tag we last detected to avoid duplicates


    def show_welcome(self):
        """Show welcome message"""
        self.console.print("LLMVM Simple Client", style="bold blue")
        self.console.print("─" * 40)
        self.console.print(f"Server: {self.config.server_url}")
        self.console.print(f"Mode: {self.config.mode}")
        self.console.print(f"Model: {self.config.executor}/{self.config.model}")
        self.console.print("─" * 40)
        self.console.print("• ESC to interrupt streaming")
        self.console.print("• Ctrl-D to delete character (or exit on empty prompt)")
        self.console.print("• Type 'exit' to quit")
        self.console.print()

    def show_goodbye(self):
        """Show exit message"""
        self.console.print("\nGoodbye!")


    def show_interrupt_hint(self):
        """Show hint after Ctrl-C"""
        self.console.print("\n(Use Ctrl-D or type 'exit' to quit)", style="dim")

    def show_interrupted(self):
        """Show message when stream interrupted"""
        self.console.print("\n[Interrupted]", style="yellow")
        self.in_response = False

    def render_text(self, text: str):
        """Render text using enhanced state machine"""
        if not self.in_response:
            self.in_response = True
            if self.config.show_timestamps:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.console.print(f"[{timestamp}] ", style="dim", end="")

        # 1. ALWAYS accumulate
        self.full_buffer += text
        self.current_buffer += text

        # 2. Check for tag detection FIRST
        detected_tag = self._detect_tag(text)
        if detected_tag:
            self.config.debug_print(f"Tag detected: {detected_tag}, state: {self.state}")
            self._handle_tag_detection(detected_tag)
            # 3. Handle current state actions (this will clear and re-render)
            self._handle_current_state()
        else:
            # Only stream if no tag was detected and we're not in STREAMING_RESULT state
            # Skip streaming for STREAMING_RESULT to avoid duplicate content
            if self.state != RenderState.STREAMING_RESULT:
                self._stream_text_always(text)
            # Debug: log if we see potential tags that aren't being detected
            if any(tag_part in text for tag_part in ['<helpers', '</helpers', 'helpers_result']):
                self.config.debug_print(f"Potential tag in text but not detected: '{text}'")

    def render_code(self, code: str, language: Optional[str] = None):
        """Render code block"""
        lang = language or ""
        if self.config.use_colors:
            print(f"\n\033[36m```{lang}\033[0m")
            print(code)
            print("\033[36m```\033[0m\n")
        else:
            print(f"\n```{lang}")
            print(code)
            print("```\n")

    def render_image(self, image_data: bytes):
        """Open image in external viewer"""
        try:
            # Detect image type
            suffix = '.png'
            if image_data[:3] == b'\xff\xd8\xff':
                suffix = '.jpg'
            elif image_data[:4] == b'RIFF':
                suffix = '.webp'

            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(image_data)
                temp_path = f.name

            # Use custom viewer if specified
            if self.config.image_viewer:
                subprocess.run(self.config.image_viewer.split() + [temp_path])
            else:
                # Auto-detect system
                if sys.platform == "darwin":
                    subprocess.run(["open", temp_path])
                elif sys.platform.startswith("linux"):
                    if subprocess.run(["which", "xdg-open"], capture_output=True).returncode == 0:
                        subprocess.run(["xdg-open", temp_path])
                    elif subprocess.run(["which", "xv"], capture_output=True).returncode == 0:
                        subprocess.run(["xv", temp_path])
                    elif subprocess.run(["which", "eog"], capture_output=True).returncode == 0:
                        subprocess.run(["eog", temp_path])
                    else:
                        print(f"\n[No image viewer found. Image saved to: {temp_path}]")
                        return
                elif sys.platform == "win32":
                    subprocess.run(["start", "", temp_path], shell=True)

            self.console.print(f"\n[Image opened: {temp_path}]\n", style="green")

        except Exception as e:
            self.console.print(f"\n[Error displaying image: {e}]\n", style="bold red")

    def render_error(self, error: str):
        """Render error message"""
        self.console.print(f"\n[Error: {error}]\n", style="bold red")

    def finish_response(self):
        """Called when response is complete"""
        if self.in_response:
            # Handle any final text
            if self.state == RenderState.STREAMING_TEXT and self.current_buffer.strip():
                self._clear_streaming_lines()
                self._render_markdown_block(self.current_buffer.strip())

            self.console.print()  # Add newline at end of response
            self.in_response = False
            self._reset_state()

    def clear_line(self):
        """Clear current line"""
        print('\r\033[K', end='')

    def _process_complete_blocks(self):
        """Process complete <helpers> and <helpers_result> blocks"""
        # Look for complete helpers blocks
        while "<helpers>" in self.buffer and "</helpers>" in self.buffer:
            start = self.buffer.find("<helpers>")
            end = self.buffer.find("</helpers>") + len("</helpers>")

            # Extract the block
            block = self.buffer[start:end]

            # Remove the block from buffer
            self.buffer = self.buffer[:start] + self.buffer[end:]

            # Extract just the code (between tags)
            code_start = block.find("<helpers>") + len("<helpers>")
            code_end = block.find("</helpers>")
            code = block[code_start:code_end].strip()

            if code:
                self.console.print()  # New line
                self.helper_block_lines += 1  # Count the newline
                self._render_python_block(code)
                # Count lines in the rendered code block
                self.helper_block_lines += code.count('\n') + 2  # +2 for the block wrapper lines

        # Look for complete helpers_result blocks
        while "<helpers_result>" in self.buffer and "</helpers_result>" in self.buffer:
            start = self.buffer.find("<helpers_result>")
            end = self.buffer.find("</helpers_result>") + len("</helpers_result>")

            # Extract the block
            block = self.buffer[start:end]

            # Remove the block from buffer
            self.buffer = self.buffer[:start] + self.buffer[end:]

            # Extract just the content (between tags)
            content_start = block.find("<helpers_result>") + len("<helpers_result>")
            content_end = block.find("</helpers_result>")
            content = block[content_start:content_end].strip()

            if content:
                self.console.print()  # New line
                self.helper_block_lines += 1  # Count the newline
                self._render_markdown_block(content)
                # Count lines in the rendered content
                self.helper_block_lines += content.count('\n') + 1  # +1 for the content itself



    def _render_python_block(self, code: str):
        """Render Python code with syntax highlighting"""
        if not code.strip():
            return

        syntax = Syntax(
            code,
            "python",
            theme=self.syntax_theme,
            background_color="default",
            word_wrap=True,
            padding=0,
        )
        self.console.print(syntax)

    def _render_markdown_block(self, content: str):
        """Render content as markdown"""
        if not content.strip():
            return

        self.console.print(Markdown(content))



    def _filter_block_content(self, text: str) -> str:
        """Remove helpers blocks from text to avoid duplicate rendering"""
        filtered = text

        # Remove complete helpers blocks
        while "<helpers>" in filtered and "</helpers>" in filtered:
            start = filtered.find("<helpers>")
            end = filtered.find("</helpers>") + len("</helpers>")
            filtered = filtered[:start] + filtered[end:]

        # Remove complete helpers_result blocks
        while "<helpers_result>" in filtered and "</helpers_result>" in filtered:
            start = filtered.find("<helpers_result>")
            end = filtered.find("</helpers_result>") + len("</helpers_result>")
            filtered = filtered[:start] + filtered[end:]

        return filtered

    def _stream_text_always(self, text: str):
        """Always stream text - never skip"""
        if text and self.streaming_enabled:
            newlines_added = text.count('\n')
            self.console.print(text, style="stream", end="", markup=False)
            self.streamed_line_count += newlines_added
            if newlines_added > 0:
                self.config.debug_print(f"Streamed text with {newlines_added} newlines, total streamed lines: {self.streamed_line_count}")

    def _detect_tag(self, text: str) -> Optional[TagType]:
        """Detect helper tags using a sliding 4-token window"""
        # Add to sliding window buffer (keep only last 4 tokens)
        self.token_window.append(text)
        if len(self.token_window) > 4:
            self.token_window.pop(0)  # Remove oldest token

        # Check combined tokens
        combined = "".join(self.token_window)

        # Find which tag is detected (if any) - check LONGEST matches first to avoid substring issues
        # Order matters: check longer tags before shorter ones to avoid substring matches
        tag_strings = [
            "<helpers_result>", "</helpers_result>",
            "<helpers>", "</helpers>",
            "</complete>"
        ]

        for tag_str in tag_strings:
            if tag_str in combined:
                tag_type = TagType.from_string(tag_str)
                if tag_type and tag_type != self.last_detected_tag:
                    self.last_detected_tag = tag_type
                    self.config.debug_print(f"Tag detection: '{tag_type.value}' in: '{combined[-50:]}'")
                    return tag_type

        return None

    def _process_tags(self):
        """Process helper tags and print horizontal line when detected"""
        if not self.pending_text:
            return

        # Check for tags and split the text accordingly
        has_tag = ("<helpers>" in self.pending_text or "</helpers>" in self.pending_text or
                   "<helpers_result>" in self.pending_text or "</helpers_result>" in self.pending_text)

        if has_tag:
            # Find the first tag position
            tag_positions = []
            for tag in ["<helpers>", "</helpers>", "<helpers_result>", "</helpers_result>"]:
                pos = self.pending_text.find(tag)
                if pos >= 0:
                    tag_positions.append(pos)

            if tag_positions:
                first_tag_pos = min(tag_positions)

                # Print text before the tag (if any)
                text_before = self.pending_text[:first_tag_pos]
                if text_before and self.streaming_enabled:
                    self.console.print(text_before, style="stream", end="", markup=False)
                    self.streaming_lines += text_before.count('\n')

                # Print the tag detection line
                self.console.print("\n" + "─" * 80 + " [TAG DETECTED]\n", style="yellow")

                # Print the rest (including the tag)
                text_after = self.pending_text[first_tag_pos:]
                if text_after and self.streaming_enabled:
                    self.console.print(text_after, style="stream", end="", markup=False)
                    self.streaming_lines += text_after.count('\n') + 2  # +2 for the detection lines
        else:
            # No tags, just show streaming text as normal
            if self.streaming_enabled:
                self.console.print(self.pending_text, style="stream", end="", markup=False)
                self.streaming_lines += self.pending_text.count('\n')

        self.pending_text = ""

    def _clear_lines(self, num_lines: int):
        """Clear a specific number of lines"""
        for _ in range(num_lines):
            print("\033[1A\033[2K", end="")
        print("\r", end="")

    def _clear_streaming_window(self):
        """Clear the streaming window by moving cursor up and clearing lines"""
        total_lines = self.streaming_lines + self.helper_block_lines
        if total_lines > 0:
            # Move cursor up and clear each line (streaming content + helper blocks)
            for _ in range(total_lines):
                print("\033[1A\033[2K", end="")  # Move up and clear line
            # Move cursor to beginning of line
            print("\r", end="")

    def _handle_tag_detection(self, tag: TagType):
        """Handle state transitions based on detected tags"""
        if tag.is_opening:
            self.state = RenderState.TAG_BEGIN_DETECTED
        elif tag.is_closing:
            self.state = RenderState.TAG_END_DETECTED

    def _handle_current_state(self):
        """Handle current state actions"""
        if self.state == RenderState.TAG_BEGIN_DETECTED:
            self._handle_tag_begin_state()
        elif self.state == RenderState.TAG_END_DETECTED:
            self._handle_tag_end_state()

    def _handle_tag_begin_state(self):
        """Handle TAG_BEGIN_DETECTED state"""
        # Render previously accumulated buffer
        self._clear_streaming_lines()
        clean_text = self._remove_detected_tag_from_end(self.current_buffer)
        self.config.debug_print(f"TAG_BEGIN_DETECTED: clean_text length = {len(clean_text)}")

        if clean_text.strip():
            # For helpers_result, the result() calls come before the tag and should be rendered as plain text
            # to preserve newlines between result() calls
            if self.last_detected_tag == TagType.HELPERS_RESULT_OPEN:
                # Use Text object to avoid any markup interpretation
                text_obj = Text(clean_text.strip())
                self.console.print(text_obj)
            else:
                self._render_markdown_block(clean_text.strip())

        # Print the opening tag (bold for final rendering)
        self.console.print(self.last_detected_tag.value, style="bold")

        # Transition to appropriate streaming state
        if self.last_detected_tag == TagType.HELPERS_OPEN:
            self.state = RenderState.STREAMING_CODE
            self.config.debug_print("Transitioned to STREAMING_CODE")
        elif self.last_detected_tag == TagType.HELPERS_RESULT_OPEN:
            self.state = RenderState.STREAMING_RESULT
            self.config.debug_print("Transitioned to STREAMING_RESULT")

        # Don't reset current_buffer here - we need it for content extraction

    def _handle_tag_end_state(self):
        """Handle TAG_END_DETECTED state"""
        if self.last_detected_tag == TagType.HELPERS_CLOSE:
            self._handle_helpers_close()
        elif self.last_detected_tag == TagType.HELPERS_RESULT_CLOSE:
            self._handle_helpers_result_close()
        elif self.last_detected_tag == TagType.COMPLETE_CLOSE:
            self._handle_complete_close()

        # Clear processed content from token window while preserving any new content after the end tag
        self._clear_processed_content_from_window()
        self.last_detected_tag = None

        # Transition back to text streaming
        self.state = RenderState.STREAMING_TEXT
        self.current_buffer = ""  # Fresh buffer

    def _handle_helpers_close(self):
        """Handle closing of helpers tag"""
        # For helpers, clear streaming lines and use current_buffer as content streams in token by token
        self._clear_streaming_lines()
        clean_content = self._remove_detected_tag_from_end(self.current_buffer)
        self.config.debug_print(f"TAG_END_DETECTED (helpers): clean_content length = {len(clean_content)}")
        self.config.debug_print(f"Using current_buffer length = {len(self.current_buffer)}")

        if clean_content.strip():
            self._render_python_block(clean_content.strip())

        self.console.print(self.last_detected_tag.value, style="bold")
        self.config.debug_print("Rendered code section")

    def _handle_helpers_result_close(self):
        """Handle closing of helpers_result tag"""
        # Check if there's content inside the helpers_result tags
        token_content = "".join(self.token_window)
        clean_content = self._remove_detected_tag_from_end(token_content)
        self.config.debug_print(f"TAG_END_DETECTED (helpers_result): clean_content length = {len(clean_content)}")

        # Only render if there's actual content and it's not just result() calls
        # Sometimes the content is inside the tags, not before them
        if clean_content.strip() and not clean_content.strip().startswith('result('):
            self.config.debug_print(f"Rendering helpers_result content: {repr(clean_content[:100])}")
            # Use Text object to avoid any markup interpretation
            text_obj = Text(clean_content.strip())
            self.console.print(text_obj)
        else:
            self.config.debug_print("No unique helpers_result content to render")

        self.console.print(self.last_detected_tag.value, style="bold")
        self.config.debug_print("Rendered helpers_result section")

    def _handle_complete_close(self):
        """Handle closing of complete tag"""
        # Clear streaming lines and render any preceding text as markdown
        self._clear_streaming_lines()
        clean_text = self._remove_detected_tag_from_end(self.current_buffer)

        if clean_text.strip():
            self._render_markdown_block(clean_text.strip())

        self.console.print(self.last_detected_tag.value, style="bold")
        self.config.debug_print("Rendered complete section")

    def _remove_detected_tag_from_end(self, buffer: str) -> str:
        """Remove the detected tag from end of buffer"""
        if not self.last_detected_tag:
            return buffer

        tag_value = self.last_detected_tag.value
        if tag_value not in buffer:
            return buffer

        # For closing tags, we need to extract content between opening and closing tags
        if self.last_detected_tag.is_closing:
            if self.last_detected_tag == TagType.HELPERS_RESULT_CLOSE:
                # Extract content between <helpers_result> and </helpers_result>
                start_pos = buffer.find(TagType.HELPERS_RESULT_OPEN.value)
                end_pos = buffer.find(TagType.HELPERS_RESULT_CLOSE.value)

                if start_pos >= 0 and end_pos >= 0:
                    content_start = start_pos + len(TagType.HELPERS_RESULT_OPEN.value)
                    content = buffer[content_start:end_pos]
                    self.config.debug_print(f"Extracted helpers_result content: '{content[:100]}...'")
                    return content

            elif self.last_detected_tag == TagType.HELPERS_CLOSE:
                # Extract content between <helpers> and </helpers>
                start_pos = buffer.find(TagType.HELPERS_OPEN.value)
                end_pos = buffer.find(TagType.HELPERS_CLOSE.value)

                if start_pos >= 0 and end_pos >= 0:
                    content_start = start_pos + len(TagType.HELPERS_OPEN.value)
                    content = buffer[content_start:end_pos]
                    self.config.debug_print(f"Extracted helpers content: '{content[:100]}...'")
                    return content
        else:
            # This is an opening tag - just remove it from the end
            tag_pos = buffer.rfind(tag_value)
            if tag_pos >= 0:
                return buffer[:tag_pos]

        return buffer

    def _clear_streaming_lines(self):
        """Clear the streaming content by moving cursor up and clearing lines"""
        if self.streamed_line_count > 0:
            self.config.debug_print(f"Clearing {self.streamed_line_count} streamed lines")
            for _ in range(self.streamed_line_count):
                print("\033[1A\033[2K", end="")  # Move up and clear line
            print("\r", end="")  # Move to beginning of line
            self.streamed_line_count = 0
        else:
            self.config.debug_print("No streamed lines to clear")

    def _clear_processed_content_from_window(self):
        """Clear processed tag content from token window while preserving new content"""
        if not self.last_detected_tag or not self.token_window:
            return

        # Find the position of the end tag in the combined window content
        combined = "".join(self.token_window)
        end_tag = self.last_detected_tag.value
        end_tag_pos = combined.find(end_tag)

        if end_tag_pos >= 0:
            # Calculate position after the end tag
            after_end_tag_pos = end_tag_pos + len(end_tag)
            remaining_content = combined[after_end_tag_pos:]

            self.config.debug_print(f"Clearing processed content, keeping: '{remaining_content[:50]}...'")

            # Replace token window with just the remaining content after the end tag
            if remaining_content:
                self.token_window = [remaining_content]
            else:
                self.token_window.clear()
        else:
            self.config.debug_print("End tag not found in window, clearing all")
            self.token_window.clear()

    def _reset_state(self):
        """Reset rendering state"""
        self.state = RenderState.STREAMING_TEXT
        self.streamed_line_count = 0

        # Reset buffers
        self.full_buffer = ""
        self.current_buffer = ""

        # Reset tag detection
        self.token_window = []
        self.last_detected_tag = None