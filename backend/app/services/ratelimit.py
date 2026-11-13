"""In-memory sliding-window rate limiter (single process, like the rest of this simulation)."""
import threading
import time
from collections import deque
from typing import Optional

MAX_KEYS = 10_000


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple, deque] = {}
        self._lock = threading.Lock()

    def check(self, key: tuple, limit: int, window: float, now: Optional[float] = None) -> tuple[bool, int, int]:
        """Returns (allowed, remaining, retry_after_seconds). A rejected call is not counted."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return False, 0, max(1, int(q[0] + window - now) + 1)
            q.append(now)
            if len(self._hits) > MAX_KEYS:
                self._prune(now, window)
            return True, limit - len(q), 0

    def _prune(self, now: float, window: float) -> None:
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window]:
            del self._hits[k]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def classify(method: str, path: str) -> str:
    """read | write | download - each bucket has its own limit."""
    if path.startswith("/api/downstream/") and (path.endswith("/fetch") or "/download/" in path):
        return "download"
    return "read" if method in ("GET", "HEAD") else "write"
