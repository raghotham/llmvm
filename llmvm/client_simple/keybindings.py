"""Keyboard shortcut handling for simple client"""
from typing import TYPE_CHECKING

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

if TYPE_CHECKING:
    from .client import SimpleClient


class KeyHandler:
    """Handles keyboard shortcuts for the simple client"""

    def __init__(self, client: 'SimpleClient'):
        self.client = client

    def handle_escape(self, event):
        """ESC to interrupt streaming"""
        if self.client.server.is_streaming:
            self.client.server.interrupt()
            self.client.renderer.show_interrupted()
            event.app.invalidate()

    def handle_ctrl_d(self, event):
        """Ctrl-D to delete char or exit"""
        buffer = event.app.current_buffer

        if buffer.text:
            # Text in prompt - delete character at cursor (forward delete)
            if buffer.cursor_position < len(buffer.text):
                buffer.delete()
        else:
            # Empty prompt - exit immediately
            self.client.request_exit()
            event.app.exit()



def create_keybindings(handler: KeyHandler) -> KeyBindings:
    """Create key bindings for the client"""
    kb = KeyBindings()

    # ESC to interrupt
    @kb.add(Keys.Escape)
    def _(event):
        handler.handle_escape(event)

    # Ctrl-D for delete/exit
    @kb.add(Keys.ControlD)
    def _(event):
        handler.handle_ctrl_d(event)

    # Ctrl-C should just continue (not exit)
    @kb.add(Keys.ControlC)
    def _(event):
        # Clear current line and show hint
        handler.client.renderer.clear_line()
        handler.client.renderer.show_interrupt_hint()
        event.app.invalidate()

    return kb