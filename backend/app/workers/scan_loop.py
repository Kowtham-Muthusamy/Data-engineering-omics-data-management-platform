"""Background thread that triggers the folder sequencer on a configurable interval."""
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from app.database import session_scope
from app.services import sequencer, settings_service
from app.services.activity import log_event
from app.utils.common import utcnow


class ScanLoop:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.next_scan_at: Optional[datetime] = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="folder-sequencer", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        last_scan = time.monotonic() - 10**6   # scan promptly after startup
        while not self._stop.wait(1.0):
            try:
                with session_scope() as s:
                    enabled = settings_service.get_bool(s, "auto_scan_enabled")
                    interval = max(1, int(settings_service.get_setting(s, "scan_interval_seconds")))
                if not enabled:
                    self.next_scan_at = None
                    continue
                due_in = interval - (time.monotonic() - last_scan)
                self.next_scan_at = utcnow() + timedelta(seconds=max(0.0, due_in))
                if due_in > 0:
                    continue
                last_scan = time.monotonic()
                sequencer.scan("auto")
            except sequencer.ScanBusy:
                pass
            except Exception as e:  # never let the loop die
                log_event(None, "sequencer", f"auto scan error: {type(e).__name__}: {e}", level="ERROR")


scan_loop = ScanLoop()
