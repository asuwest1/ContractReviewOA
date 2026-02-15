import os
import threading
import time

from contract_review.service import RequestContext


class ReminderScheduler:
    def __init__(self, service):
        self.service = service
        self.interval_s = int(os.environ.get("REMINDER_INTERVAL_SECONDS", "0"))
        self.system_user = os.environ.get("SYSTEM_USER", "system.scheduler")
        self._thread = None
        self._stop = threading.Event()

    @property
    def enabled(self) -> bool:
        return self.interval_s > 0

    def start(self):
        if not self.enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self):
        ctx = RequestContext(user=self.system_user, roles={"Admin"})
        while not self._stop.wait(self.interval_s):
            try:
                self.service.run_aging_reminders(ctx)
            except Exception:
                # Keep scheduler alive; failures can be audited/logged externally.
                pass
