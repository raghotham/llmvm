"""Simple LLMVM client for basic interaction with server"""

from .client import SimpleClient
from .config import Config

__version__ = "1.0.0"
__all__ = ['SimpleClient', 'Config']