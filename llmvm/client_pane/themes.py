"""Simple theme detection using Rich for terminal color adaptation"""
import os
import subprocess
from typing import Tuple, Dict, Any
from rich.console import Console
from rich.theme import Theme


def detect_terminal_background() -> str:
    """Detect if terminal has light or dark background.

    Returns:
        'light' or 'dark'
    """
    # Check COLORFGBG environment variable (used by many terminals)
    colorfgbg = os.environ.get('COLORFGBG', '')
    if colorfgbg:
        # Format is usually "foreground;background" where background color indicates theme
        parts = colorfgbg.split(';')
        if len(parts) >= 2:
            try:
                bg_color = int(parts[-1])
                # Dark backgrounds typically use colors 0-7, light use 8-15
                return 'dark' if bg_color < 8 else 'light'
            except (ValueError, IndexError):
                pass

    # Check for macOS Terminal.app theme
    if os.environ.get('TERM_PROGRAM') == 'Apple_Terminal':
        try:
            # Use AppleScript to get background color
            script = '''
            tell application "Terminal"
                get background color of current settings of front window
            end tell
            '''
            result = subprocess.run(['osascript', '-e', script],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                # Parse RGB values and calculate luminance
                rgb_str = result.stdout.strip()
                if rgb_str:
                    # Format: "65535, 65535, 65535" (16-bit values)
                    rgb_values = [int(x.strip()) / 65535.0 for x in rgb_str.split(',')]
                    if len(rgb_values) == 3:
                        # Calculate relative luminance
                        r, g, b = rgb_values
                        luminance = 0.299 * r + 0.587 * g + 0.114 * b
                        return 'light' if luminance > 0.5 else 'dark'
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
            pass

    # Check terminal program hints
    term_program = os.environ.get('TERM_PROGRAM', '').lower()
    if 'vscode' in term_program:
        # VS Code usually has dark theme by default
        return 'dark'

    # Default assumption
    return 'dark'


def get_theme_colors(background: str) -> Dict[str, str]:
    """Get color scheme based on background type.

    Args:
        background: 'light' or 'dark'

    Returns:
        Dictionary of color names to Rich color strings
    """
    if background == 'light':
        return {
            'primary': 'blue',
            'secondary': 'cyan',
            'success': 'green',
            'warning': 'yellow',
            'error': 'red',
            'muted': 'bright_black',
            'text': 'black',
            'stream': 'bright_black',  # dim for streaming
            'thinking': 'bright_black',
            'code_bg': 'grey93',
            'markdown_code': 'grey85'
        }
    else:  # dark
        return {
            'primary': 'bright_blue',
            'secondary': 'bright_cyan',
            'success': 'bright_green',
            'warning': 'bright_yellow',
            'error': 'bright_red',
            'muted': 'bright_black',
            'text': 'white',
            'stream': 'bright_black',  # dim for streaming
            'thinking': 'bright_black',
            'code_bg': 'grey19',
            'markdown_code': 'grey23'
        }


def create_rich_theme(background: str = None) -> Theme:
    """Create a Rich theme adapted to terminal background.

    Args:
        background: Override background detection ('light' or 'dark')

    Returns:
        Rich Theme object
    """
    if background is None:
        background = detect_terminal_background()

    colors = get_theme_colors(background)

    return Theme({
        'primary': colors['primary'],
        'secondary': colors['secondary'],
        'success': colors['success'],
        'warning': colors['warning'],
        'error': colors['error'],
        'muted': colors['muted'],
        'stream': colors['stream'],
        'thinking': colors['thinking']
    })


def get_syntax_theme(background: str = None) -> str:
    """Get appropriate syntax highlighting theme for background.

    Args:
        background: Override background detection ('light' or 'dark')

    Returns:
        Theme name for Rich Syntax
    """
    if background is None:
        background = detect_terminal_background()

    return 'github-light' if background == 'light' else 'monokai'