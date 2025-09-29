"""Rich Live renderer with proper section-by-section streaming and rendering"""
import sys
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, List, Any, Union
from enum import Enum
from dataclasses import dataclass

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.live import Live
from rich.panel import Panel


class SectionType(Enum):
    TEXT = "text"
    CODE = "code"
    RESULT = "result"


class SectionState(Enum):
    STREAMING = "streaming"
    RENDERED = "rendered"


@dataclass
class Section:
    """A section that can be streamed and then rendered"""
    type: SectionType
    state: SectionState
    content: str = ""

    def to_renderable(self):
        """Convert section to Rich renderable based on its type and state"""
        if self.state == SectionState.STREAMING:
            # Show streaming content as dim text
            return Text(self.content, style="dim")
        else:
            # Show rendered content based on type
            if self.type == SectionType.TEXT:
                if self.content.strip():
                    # Use no style to inherit terminal default colors
                    return Text(self.content.strip())
                else:
                    return Text("")
            elif self.type == SectionType.CODE:
                if self.content.strip():
                    syntax = Syntax(
                        self.content.strip(),
                        "python",
                        background_color="default",
                        word_wrap=True,
                        padding=0,
                    )
                    return Panel(syntax, title="Code", title_align="left", border_style="blue")
                else:
                    return Text("")
            elif self.type == SectionType.RESULT:
                if self.content.strip():
                    # Use no style to inherit terminal default colors
                    result_text = Text(self.content.strip())
                    return Panel(result_text, title="Result", title_align="left", border_style="green")
                else:
                    return Text("")


class RichLiveRenderer:
    """Renderer using Rich Live with proper section-by-section streaming and rendering"""

    def __init__(self, config):
        self.config = config

        # Use Rich console with force terminal colors for better compatibility
        self.console = Console(
            width=120,
            force_terminal=True,
            color_system="auto"
        )

        # Live display state
        self.live_display = None
        self.sections: List[Section] = []

        # Parser state for detecting tags
        self.token_buffer = ""
        self.in_helpers = False
        self.in_helpers_result = False

        # Throttle display updates
        self.update_counter = 0
        self.update_frequency = 5  # Update every 5 characters

    def start_response(self):
        """Start a new response with Live display"""
        self.sections = []
        self.token_buffer = ""
        self.in_helpers = False
        self.in_helpers_result = False

        # Start with a text section
        self.sections.append(Section(SectionType.TEXT, SectionState.STREAMING))

        # Create Live display
        self.live_display = Live(
            self._build_display(),
            refresh_per_second=10,  # Reasonable refresh rate to avoid flickering
            console=self.console,
            transient=False
        )
        self.live_display.__enter__()

        if self.config.show_timestamps:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.console.print(f"[{timestamp}] ", style="dim", end="")

    def render_text(self, text: str):
        """Process incoming text token by token"""
        if not self.live_display:
            self.start_response()

        # Add text to token buffer for tag detection
        self.token_buffer += text

        # Check for tag boundaries
        self._process_tags()

        # Add text to current section
        if self.sections:
            self.sections[-1].content += text

        # Throttle display updates to reduce flickering
        self.update_counter += 1
        if self.update_counter >= self.update_frequency:
            self._update_display()
            self.update_counter = 0

    def _process_tags(self):
        """Process accumulated tokens to detect and handle tags"""
        processed_any = False

        # Check for helpers tags - only if we find the complete tag
        if "<helpers>" in self.token_buffer and not self.in_helpers:
            self.in_helpers = True
            self._complete_current_section()
            self.sections.append(Section(SectionType.CODE, SectionState.STREAMING))
            # Remove the processed tag from buffer
            self.token_buffer = self.token_buffer.replace("<helpers>", "", 1)
            processed_any = True
            # Debug output
            if hasattr(self.config, 'debug_print'):
                self.config.debug_print("Started code section")

        if "</helpers>" in self.token_buffer and self.in_helpers:
            self.in_helpers = False
            self._complete_current_section()
            self.sections.append(Section(SectionType.TEXT, SectionState.STREAMING))
            # Remove the processed tag from buffer
            self.token_buffer = self.token_buffer.replace("</helpers>", "", 1)
            processed_any = True
            # Debug output
            if hasattr(self.config, 'debug_print'):
                self.config.debug_print("Completed code section, started text section")

        # Check for helpers_result tags
        if "<helpers_result>" in self.token_buffer and not self.in_helpers_result:
            self.in_helpers_result = True
            self._complete_current_section()
            self.sections.append(Section(SectionType.RESULT, SectionState.STREAMING))
            # Remove the processed tag from buffer
            self.token_buffer = self.token_buffer.replace("<helpers_result>", "", 1)
            processed_any = True
            # Debug output
            if hasattr(self.config, 'debug_print'):
                self.config.debug_print("Started result section")

        if "</helpers_result>" in self.token_buffer and self.in_helpers_result:
            self.in_helpers_result = False
            self._complete_current_section()
            self.sections.append(Section(SectionType.TEXT, SectionState.STREAMING))
            # Remove the processed tag from buffer
            self.token_buffer = self.token_buffer.replace("</helpers_result>", "", 1)
            processed_any = True
            # Debug output
            if hasattr(self.config, 'debug_print'):
                self.config.debug_print("Completed result section, started text section")

        # Only clear buffer if we didn't process any tags (to avoid losing partial tags)
        if not processed_any and len(self.token_buffer) > 100:
            self.token_buffer = self.token_buffer[-50:]

    def _complete_current_section(self):
        """Complete the current section by cleaning it up and marking as rendered"""
        if not self.sections:
            return

        current = self.sections[-1]

        # Clean up content by removing tags
        current.content = self._clean_content(current.content)

        # Mark as rendered
        current.state = SectionState.RENDERED

        # Debug output
        if hasattr(self.config, 'debug_print'):
            self.config.debug_print(f"Completed section type={current.type.value}, content_length={len(current.content)}")

        # Force display update when completing a section
        self._update_display()
        self.update_counter = 0

    def _clean_content(self, content: str) -> str:
        """Remove tags from content"""
        clean = content

        # Remove all tags
        tags_to_remove = [
            "<helpers>", "</helpers>",
            "<helpers_result>", "</helpers_result>",
            "</complete>"
        ]

        for tag in tags_to_remove:
            clean = clean.replace(tag, "")

        return clean.strip()

    def _build_display(self) -> Union[Text, Group]:
        """Build the display from all sections"""
        if not self.sections:
            return Text("")

        renderables = []
        for section in self.sections:
            # Only render sections with content
            if section.content.strip():
                renderable = section.to_renderable()
                if renderable:
                    renderables.append(renderable)

        if len(renderables) == 0:
            return Text("")
        elif len(renderables) == 1:
            return renderables[0]
        else:
            return Group(*renderables)

    def _update_display(self):
        """Update the live display with current sections"""
        if self.live_display:
            try:
                display = self._build_display()
                self.live_display.update(display)
            except Exception as e:
                # Fallback to simple text display
                self.config.debug_print(f"Display update error: {e}")
                self.live_display.update(Text("Rendering...", style="dim"))

    def render_code(self, code: str, language: Optional[str] = None):
        """Handle explicit code blocks (from chunk.type == 'code')"""
        if not self.live_display:
            self.start_response()

        # Add code as a dedicated rendered section (bypass streaming)
        if code.strip():
            syntax = Syntax(
                code.strip(),
                language or "python",
                background_color="default",
                word_wrap=True,
                padding=0,
            )
            # Create a custom section that renders directly to a panel
            code_section = Section(SectionType.CODE, SectionState.RENDERED, code.strip())
            self.sections.append(code_section)
        self._update_display()

    def render_image(self, image_data: bytes):
        """Open image in external viewer and add note"""
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

            # Use system viewer
            if sys.platform == "darwin":
                subprocess.run(["open", temp_path])
            elif sys.platform.startswith("linux"):
                subprocess.run(["xdg-open", temp_path])
            elif sys.platform == "win32":
                subprocess.run(["start", "", temp_path], shell=True)

            # Add image note as text
            self.render_text(f"\n[Image opened: {temp_path}]\n")

        except Exception as e:
            self.render_error(str(e))

    def render_error(self, error: str):
        """Render error message"""
        self.console.print(f"\n[Error: {error}]\n", style="bold red")

    def render_command_output(self, message: str):
        """Render slash command output"""
        self.console.print(Markdown(message))

    def finish_response(self):
        """Finish response and clean up"""
        if not self.live_display:
            return

        try:
            # Complete any remaining streaming section
            if self.sections and self.sections[-1].state == SectionState.STREAMING:
                self._complete_current_section()

            # Final update
            self._update_display()

            # Exit live context
            self.live_display.__exit__(None, None, None)
            self.live_display = None

            # Add newline for separation
            self.console.print()

        except Exception as e:
            self.config.debug_print(f"Error in finish_response: {e}")
            if self.live_display:
                self.live_display.__exit__(None, None, None)
                self.live_display = None

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
        if self.live_display:
            self.live_display.__exit__(None, None, None)
            self.live_display = None