"""Model-call usage and failure tracking independent of provider response format."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from datetime import timezone as _tz
from typing import Any, TypeVar

from .utils import estimate_tokens

T = TypeVar("T")


@dataclass(slots=True)
class UsageRecord:
    run_id: str
    thread_id: str
    stage: str
    model: str
    prompt_version: str
    started_at: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    token_source: str
    retry_count: int
    status: str
    error_code: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class UsageMiddleware:
    """Wrap calls and persist usage through an injected recorder callback."""

    def __init__(self, recorder: Callable[[dict[str, Any]], None] | None = None):
        self.recorder = recorder
        self.records: list[UsageRecord] = []

    def track(
        self,
        fn: Callable[[], T],
        *,
        thread_id: str,
        stage: str,
        model: str,
        prompt_version: str,
        input_text: str,
        retry_count: int = 0,
    ) -> T:
        started_at = datetime.now(_tz.utc).isoformat(timespec="milliseconds")
        start = time.perf_counter()
        status = "SUCCESS"
        error_code = ""
        output_text = ""
        try:
            result = fn()
            output_text = result if isinstance(result, str) else str(result)
            return result
        except Exception as exc:
            status = "ERROR"
            error_code = type(exc).__name__
            raise
        finally:
            record = UsageRecord(
                run_id=str(uuid.uuid4()),
                thread_id=thread_id,
                stage=stage,
                model=model,
                prompt_version=prompt_version,
                started_at=started_at,
                latency_ms=round((time.perf_counter() - start) * 1000),
                input_tokens=estimate_tokens(input_text),
                output_tokens=estimate_tokens(output_text) if output_text else 0,
                token_source="estimated",
                retry_count=retry_count,
                status=status,
                error_code=error_code,
            )
            self.records.append(record)
            if self.recorder:
                self.recorder(record.as_dict())
