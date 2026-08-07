"""OpenAI-compatible structured model client with one bounded JSON repair."""

from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ValidationError

from .config import Settings
from .middleware import UsageMiddleware
from .prompts import PROMPT_VERSION

ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredModel(Protocol):
    def invoke_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[ModelT],
        stage: str,
        thread_id: str,
        allow_repair: bool = True,
        temperature: float | None = None,
    ) -> ModelT: ...


_JSON_INVALID_ESCAPE_RE = re.compile(r"\\(?![\"\\/bfnrtu])")


def _repair_invalid_escapes(text: str) -> str:
    """Double lone backslashes that JSON does not allow ("\beta" -> "\\beta").

    Models frequently emit LaTeX (\beta) or shell paths with bare backslashes
    inside JSON strings; json.loads rejects them. Only backslashes NOT
    followed by a legal JSON escape are repaired, so \\n, \\t, \\uXXXX and
    \\\\ survive untouched. (fix 2026-08-04: translation batches failed with
    JSONDecodeError "Invalid \\escape" — half the front-page translation.)
    """
    return _JSON_INVALID_ESCAPE_RE.sub(r"\\\\", text)


def extract_json(text: str) -> object:
    """Extract one JSON value while rejecting surrounding natural-language claims."""

    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        # tolerant pass: repair invalid escapes (LaTeX/shell backslashes)
        repaired = _repair_invalid_escapes(stripped)
        if repaired != stripped:
            return json.loads(repaired)
        raise


class OpenAICompatibleModel:
    def __init__(self, settings: Settings, middleware: UsageMiddleware | None = None):
        self.settings = settings
        self.middleware = middleware or UsageMiddleware()
        api_key = settings.openai_api_key or "paperlens-local"
        extra_body: dict[str, object] = {}
        if settings.paperlens_disable_thinking:
            # Reasoning models (e.g. DeepSeek v4) otherwise burn the whole token
            # budget on hidden reasoning and time out before emitting content.
            extra_body["thinking"] = {"type": "disabled"}
        self.chat = ChatOpenAI(
            model=settings.paperlens_model,
            api_key=api_key,
            base_url=settings.openai_base_url,
            temperature=settings.paperlens_temperature,
            max_tokens=settings.paperlens_max_output_tokens,
            timeout=180,
            max_retries=0,
            extra_body=extra_body,
        )

    def _raw(
        self,
        system: str,
        user: str,
        *,
        stage: str,
        thread_id: str,
        retry_count: int,
        temperature: float | None = None,
    ) -> str:
        def call() -> str:
            kwargs = {"temperature": temperature} if temperature is not None else {}
            response = self.chat.invoke(
                [SystemMessage(content=system), HumanMessage(content=user)], **kwargs
            )
            if isinstance(response.content, str):
                return response.content
            return "".join(str(item) for item in response.content)

        return self.middleware.track(
            call,
            thread_id=thread_id,
            stage=stage,
            model=self.settings.paperlens_model,
            prompt_version=PROMPT_VERSION,
            input_text=system + "\n" + user,
            retry_count=retry_count,
        )

    def invoke_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[ModelT],
        stage: str,
        thread_id: str,
        allow_repair: bool = True,
        temperature: float | None = None,
    ) -> ModelT:
        raw = self._raw(
            system,
            user,
            stage=stage,
            thread_id=thread_id,
            retry_count=0,
            temperature=temperature,
        )
        try:
            return schema.model_validate(extract_json(raw))
        except (json.JSONDecodeError, ValidationError) as first_error:
            if not allow_repair:
                raise
            repair_system = (
                "You repair JSON syntax/schema only. Do not add facts. Output JSON only. "
                "The target JSON Schema follows:\n"
                + json.dumps(schema.model_json_schema(), ensure_ascii=False)
            )
            repair_user = f"Invalid output:\n{raw}\n\nValidation error:\n{first_error}"
            repaired = self._raw(
                repair_system,
                repair_user,
                stage=f"{stage}_schema_repair",
                thread_id=thread_id,
                retry_count=1,
                temperature=temperature,
            )
            return schema.model_validate(extract_json(repaired))


class StaticJSONModel:
    """Deterministic model double used in offline tests and failure demonstrations."""

    def __init__(self, responses: list[object]):
        self.responses = list(responses)
        self.calls: list[dict[str, str]] = []

    def invoke_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[ModelT],
        stage: str,
        thread_id: str,
        allow_repair: bool = True,
        temperature: float | None = None,
    ) -> ModelT:
        self.calls.append({"system": system, "user": user, "stage": stage, "thread_id": thread_id})
        if not self.responses:
            raise RuntimeError("StaticJSONModel has no response left")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)
