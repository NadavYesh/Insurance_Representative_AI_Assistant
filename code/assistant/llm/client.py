"""The LLM behind the two text workers. Kept behind a small interface so tests use a fake."""

from __future__ import annotations

import os
from typing import Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)

API_KEY_VAR = "OPEN_AI_API_KEY"


class LLMError(RuntimeError):
    """The model gave no usable output."""


class LLM(Protocol):
    def parse(self, instructions: str, text: str, schema: type[M]) -> M:
        """Fills in `schema` from `text` (structured output)."""
        ...

    def write(self, instructions: str, text: str) -> str:
        """Free text output."""
        ...


class OpenAILLM:
    # The rep is live on the phone (Ronit's requirement #4): fail fast rather than hang.
    def __init__(self, model: str, api_key: str | None = None, timeout: float = 15.0) -> None:
        api_key = api_key or os.environ.get(API_KEY_VAR)
        if not api_key:
            raise LLMError(f"Set {API_KEY_VAR} in code/.env")
        self._client = OpenAI(api_key=api_key, timeout=timeout, max_retries=1)
        self._model = model

    def parse(self, instructions: str, text: str, schema: type[M]) -> M:
        response = self._client.responses.parse(
            model=self._model, instructions=instructions, input=text, text_format=schema
        )
        if response.output_parsed is None:
            raise LLMError("The model returned no structured output")
        return response.output_parsed

    def write(self, instructions: str, text: str) -> str:
        response = self._client.responses.create(model=self._model, instructions=instructions, input=text)
        if not response.output_text.strip():
            raise LLMError("The model returned an empty answer")
        return response.output_text
