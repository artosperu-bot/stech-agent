from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class PromptDefinition:
    prompt_id: str
    version: str
    sha256: str
    text: str


class PromptRegistry:
    _RESOURCES = {
        "SEO_PRODUCTO_STECH_V1": ("1", "seo_producto_stech_v1.txt"),
    }

    @classmethod
    def get(cls, prompt_id: str) -> PromptDefinition:
        try:
            version, filename = cls._RESOURCES[prompt_id]
        except KeyError as exc:
            raise KeyError(f"Prompt no registrado: {prompt_id}") from exc
        text = files("stech_agent.prompts").joinpath(filename).read_text(encoding="utf-8")
        return PromptDefinition(
            prompt_id=prompt_id,
            version=version,
            sha256=sha256(text.encode("utf-8")).hexdigest(),
            text=text,
        )
