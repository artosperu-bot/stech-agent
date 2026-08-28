from __future__ import annotations

import json
from typing import Any, Mapping

from stech_agent.agent.config import PlannerSettings
from stech_agent.agent.schema import PLANNER_JSON_SCHEMA, PlannerDecision
from stech_agent.domain.scopes import SECTION_FIELDS


PLANNER_INSTRUCTIONS = """Eres el cerebro de planificación de STECH Product Agent.
Tu único trabajo es interpretar la orden del usuario y devolver un plan estructurado.
NO navegas por internet, NO investigas productos y NO ejecutas herramientas.
La investigación, cuando se necesite, la hará después un proceso local con Edge/ChatGPT.
S-TECH será operado después por herramientas Python/Playwright determinísticas.

Reglas de objetivos:
- Para órdenes de lectura como dime/muestra/revisa/verifica, usa action=READ y mode=READ.
- Si el usuario da un SKU, colócalo en target.skus.
- Si identifica un producto por nombre, conserva ese nombre en target.name. NO pidas el SKU solo porque no fue escrito: el catálogo local resolverá el nombre a SKU.
- Si dice de esos/estos/los anteriores/el anterior/el mismo producto/ese producto/ese mismo, usa target.use_working_set=true.
- target.allow_multiple_name_matches=true SOLO si el usuario autoriza explícitamente aplicar la acción a todos los productos que tengan ese mismo nombre.
- target.all_products=true SOLO si el usuario dice explícitamente todos los productos, todo el catálogo o equivalente. Nunca lo infieras por ausencia de filtros.

Reglas de lectura SEO:
- Si pide verificar/revisar si el SEO está completo, usa action=READ, section=seo, mode=READ, values vacío y fields=[seo_title, seo_description, seo_keywords, seo_faq].
- No inventes contenido SEO cuando la orden es solo verificar.

Reglas de mutación:
- Para UPDATE_FIELDS identifica section, fields y el valor exacto solicitado.
- Cada valor explícito debe ir en values como {field, value}. Ejemplo conceptual: stock a 2 => values contiene field=stock, value=2.
- No inventes un valor que el usuario no haya indicado. Si falta un valor necesario, pide aclaración.
- Los campos de values deben coincidir con los campos que la orden autoriza.
- Si pide solo un campo, autoriza únicamente ese campo en fields.
- Para completar SEO faltante usa action=GENERATE_SEO, section=seo y mode=FILL_MISSING. En generación de contenido, values puede estar vacío porque el contenido se obtiene en un paso posterior.
- Campos SEO: seo_title, seo_description, seo_keywords, seo_faq.
- Para toda la sección SEO usa los cuatro campos SEO.

Reglas generales:
- Si pide investigar, marca research_required=true, pero no inventes el resultado de investigación.
- Nunca uses DELETE ni inventes acciones fuera del schema.
- No marques clarification_required solo porque falta SKU si target.name contiene un nombre utilizable.
- Si una mutación sigue siendo realmente ambigua o insegura después de representar nombre/filtros/valores, clarification_required=true y formula una sola pregunta clara.
- explanation debe ser breve y describir lo que entendiste, sin exponer razonamiento interno.
"""


class OpenAIPlanner:
    def __init__(self, settings: PlannerSettings, *, client: Any | None = None):
        self.settings = settings
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=settings.api_key)
        self.client = client

    def plan(self, command: str, context: Mapping[str, Any] | None = None) -> PlannerDecision:
        command = str(command).strip()
        if not command:
            raise ValueError("Orden vacía")
        payload = {
            "command": command,
            "context": dict(context or {}),
            "sections": {name: sorted(fields) for name, fields in SECTION_FIELDS.items()},
        }
        response = self.client.responses.create(
            model=self.settings.model,
            instructions=PLANNER_INSTRUCTIONS,
            input=json.dumps(payload, ensure_ascii=False),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "stech_planner_decision",
                    "strict": True,
                    "schema": PLANNER_JSON_SCHEMA,
                }
            },
            store=False,
        )
        raw = str(response.output_text or "").strip()
        if not raw:
            raise RuntimeError("El planner no devolvió contenido")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("El planner devolvió JSON inválido") from exc
        return PlannerDecision.from_dict(parsed)
