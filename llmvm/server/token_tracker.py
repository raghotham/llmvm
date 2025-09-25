"""Token usage tracking for LLMVM server sessions"""
import threading
from typing import Dict, Optional
from dataclasses import dataclass, field
import time


@dataclass
class SessionUsage:
    """Track token usage for a single session"""
    session_id: int
    total_tokens: int = 0
    request_count: int = 0
    start_time: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    def add_tokens(self, tokens: int):
        """Add tokens to this session's usage"""
        self.total_tokens += tokens
        self.request_count += 1
        self.last_activity = time.time()


class TokenTracker:
    """Global token usage tracker for all sessions"""

    def __init__(self):
        self._sessions: Dict[int, SessionUsage] = {}
        self._lock = threading.Lock()
        self._global_tokens = 0
        self._global_requests = 0

    def track_usage(self, session_id: int, tokens: int):
        """Track token usage for a session"""
        if tokens <= 0:
            return

        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionUsage(session_id=session_id)

            self._sessions[session_id].add_tokens(tokens)
            self._global_tokens += tokens
            self._global_requests += 1

    def get_session_usage(self, session_id: int) -> Optional[SessionUsage]:
        """Get usage for a specific session"""
        with self._lock:
            return self._sessions.get(session_id)

    def get_global_usage(self) -> Dict:
        """Get global usage statistics"""
        with self._lock:
            return {
                "total_tokens": self._global_tokens,
                "total_requests": self._global_requests,
                "active_sessions": len(self._sessions),
                "sessions": {
                    session_id: {
                        "total_tokens": session.total_tokens,
                        "request_count": session.request_count,
                        "start_time": session.start_time,
                        "last_activity": session.last_activity
                    }
                    for session_id, session in self._sessions.items()
                }
            }

    def cleanup_old_sessions(self, max_age_seconds: int = 3600):
        """Remove sessions older than max_age_seconds"""
        current_time = time.time()
        with self._lock:
            to_remove = [
                session_id for session_id, session in self._sessions.items()
                if current_time - session.last_activity > max_age_seconds
            ]
            for session_id in to_remove:
                del self._sessions[session_id]


# Global token tracker instance
_token_tracker = TokenTracker()


def get_token_tracker() -> TokenTracker:
    """Get the global token tracker instance"""
    return _token_tracker