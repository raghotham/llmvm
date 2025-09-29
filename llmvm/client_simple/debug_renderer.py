"""Debug renderer that shows streaming without live updates for testing"""
import sys
import subprocess
import tempfile
from datetime import datetime
from typing import Optional, List
from enum import Enum
from dataclasses import dataclass

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
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
        state_marker = "[STREAMING]" if self.state == SectionState.STREAMING else "[RENDERED]"

        if self.type == SectionType.TEXT:
            if self.content.strip():
                return Text(f"{state_marker} TEXT: {self.content.strip()}")
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
                return Panel(syntax, title=f"Code {state_marker}", title_align="left", border_style="blue")
            else:
                return Text("")
        elif self.type == SectionType.RESULT:
            if self.content.strip():
                result_text = Text(self.content.strip())
                return Panel(result_text, title=f"Result {state_marker}", title_align="left", border_style="green")
            else:
                return Text("")


class DebugRenderer:
    """Debug renderer that shows all states without live updates"""

    def __init__(self, config):
        self.config = config
        self.console = Console(width=120)
        self.sections: List[Section] = []

        # Parser state for detecting tags
        self.token_buffer = ""
        self.in_helpers = False
        self.in_helpers_result = False

    def start_response(self):
        """Start a new response"""
        self.sections = []
        self.token_buffer = ""
        self.in_helpers = False
        self.in_helpers_result = False

        # Start with a text section
        self.sections.append(Section(SectionType.TEXT, SectionState.STREAMING))

        if self.config.show_timestamps:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.console.print(f"[{timestamp}] ", style="dim", end="")

    def render_text(self, text: str):
        """Process incoming text token by token"""
        # Add text to token buffer for tag detection
        self.token_buffer += text

        # Check for tag boundaries
        self._process_tags()

        # Add text to current section
        if self.sections:
            self.sections[-1].content += text

        # Show streaming content in real-time
        if self.sections and self.sections[-1].state == SectionState.STREAMING:
            section = self.sections[-1]
            self.console.print(f"📝 [{section.type.value.upper()} STREAMING] {text}", end="", style="dim")

    def _process_tags(self):
        """Process accumulated tokens to detect and handle tags"""
        # Check for helpers tags
        if "<helpers>" in self.token_buffer and not self.in_helpers:
            self.in_helpers = True
            self._complete_current_section()
            self.sections.append(Section(SectionType.CODE, SectionState.STREAMING))
            self.console.print("🔵 STARTED CODE SECTION")

        if "</helpers>" in self.token_buffer and self.in_helpers:
            self.in_helpers = False
            self._complete_current_section()
            self.sections.append(Section(SectionType.TEXT, SectionState.STREAMING))
            self.console.print("🔵 COMPLETED CODE SECTION")

        # Check for helpers_result tags
        if "<helpers_result>" in self.token_buffer and not self.in_helpers_result:
            self.in_helpers_result = True
            self._complete_current_section()
            self.sections.append(Section(SectionType.RESULT, SectionState.STREAMING))
            self.console.print("🟢 STARTED RESULT SECTION")

        if "</helpers_result>" in self.token_buffer and self.in_helpers_result:
            self.in_helpers_result = False
            self._complete_current_section()
            self.sections.append(Section(SectionType.TEXT, SectionState.STREAMING))
            self.console.print("🟢 COMPLETED RESULT SECTION")

        # Clear processed tokens
        if len(self.token_buffer) > 100:
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

        # Show completion
        self.console.print(f"\n✅ COMPLETED {current.type.value.upper()} SECTION")

        # Show the completed section immediately
        if current.content.strip():
            renderable = current.to_renderable()
            if renderable:
                self.console.print(renderable)

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

    def render_code(self, code: str, language: Optional[str] = None):
        """Handle explicit code blocks"""
        if code.strip():
            syntax = Syntax(
                code.strip(),
                language or "python",
                background_color="default",
                word_wrap=True,
                padding=0,
            )
            self.console.print(Panel(syntax, title="Direct Code", title_align="left", border_style="blue"))

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

            self.console.print(f"📷 [Image opened: {temp_path}]")

        except Exception as e:
            self.render_error(str(e))

    def render_error(self, error: str):
        """Render error message"""
        self.console.print(f"❌ [Error: {error}]", style="bold red")

    def render_command_output(self, message: str):
        """Render slash command output"""
        self.console.print(Markdown(message))

    def finish_response(self):
        """Finish response and clean up"""
        # Complete any remaining streaming section
        if self.sections and self.sections[-1].state == SectionState.STREAMING:
            self._complete_current_section()

        self.console.print("\n" + "="*80 + " RESPONSE COMPLETE " + "="*80)
        self.console.print(f"📊 Total sections: {len(self.sections)}")
        for i, section in enumerate(self.sections):
            self.console.print(f"  Section {i}: {section.type.value} ({section.state.value}) - {len(section.content)} chars")
        self.console.print("="*179 + "\n")

    def show_welcome(self):
        """Show welcome message"""
        self.console.print("🔧 LLMVM Debug Client", style="bold blue")
        self.console.print("─" * 40)

    def show_goodbye(self):
        """Show exit message"""
        self.console.print("\n👋 Goodbye!")

    def show_interrupt_hint(self):
        """Show hint after Ctrl-C"""
        self.console.print("\n(Use Ctrl-D or type 'exit' to quit)", style="dim")

    def show_interrupted(self):
        """Show message when stream interrupted"""
        self.console.print("\n⚡ [Interrupted]", style="yellow")