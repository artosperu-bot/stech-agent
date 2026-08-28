from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping

from dotenv import load_dotenv

DEFAULT_OPENAI_MODEL = "gpt-5-mini-2025-08-07"


@dataclass(frozen=True, slots=True)
class PlannerSettings:
    api_key: str
    model: str = DEFAULT_OPENAI_MODEL

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        load_dotenv_file: bool = True,
    ) -> "PlannerSettings":
        if env is None:
            if load_dotenv_file:
                load_dotenv()
            env = os.environ
        api_key = str(env.get("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY en el entorno o .env")
        model = str(env.get("OPENAI_MODEL") or DEFAULT_OPENAI_MODEL).strip()
        return cls(api_key=api_key, model=model or DEFAULT_OPENAI_MODEL)
