"""In-process event bus for job progress and Agent claim streams (SSE)."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from collections import defaultdict


class EventBus:
    """Thread-safe fan-out of JobEvent payloads to per-job subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[queue.Queue]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, job_id: str) -> queue.Queue:
        with self._lock:
            subscriber: queue.Queue = queue.Queue(maxsize=500)
            self._subscribers[job_id].append(subscriber)
            return subscriber

    def unsubscribe(self, job_id: str, subscriber: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers[job_id].remove(subscriber)
            except ValueError:
                pass
            if not self._subscribers[job_id]:
                self._subscribers.pop(job_id, None)

    def publish(self, job_id: str, event: dict[str, object]) -> None:
        payload = json.dumps(event, ensure_ascii=False)
        with self._lock:
            for subscriber in list(self._subscribers.get(job_id, [])):
                try:
                    subscriber.put_nowait(payload)
                except queue.Full:
                    subscriber.get_nowait()  # drop oldest rather than block

    async def stream(self, job_id: str):
        """Async generator of SSE-formatted events for one job."""
        subscriber = self.subscribe(job_id)
        try:
            while True:
                try:
                    payload = subscriber.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.15)
                    continue
                yield f"data: {payload}\n\n"
        finally:
            self.unsubscribe(job_id, subscriber)


bus = EventBus()
