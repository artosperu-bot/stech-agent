from __future__ import annotations

from typing import Any

from stech_agent.agent.memory_policy import working_set_skus_for_result
from stech_agent.agent.runtime import AgentBrainRuntime
from stech_agent.agent.schema import PlannerDecision


_ORIGINAL_EXECUTE = AgentBrainRuntime.execute
_ORIGINAL_EXECUTE_SEO_READ = AgentBrainRuntime._execute_seo_read


def _seo_summary(cls, name: str, sku: str, values: dict[str, Any]):
    title_ok = cls._nonempty(values.get("seo_title"))
    description_ok = cls._nonempty(values.get("seo_description"))
    keywords_ok = cls._nonempty(values.get("seo_keywords"))
    faqs = values.get("seo_faqs") or []

    complete_faqs = 0
    faq_has_content = False
    for faq in faqs:
        if not isinstance(faq, dict):
            continue
        question_has = cls._nonempty(faq.get("question"))
        answer_has = cls._nonempty(faq.get("answer"))
        if question_has or answer_has:
            faq_has_content = True
        if question_has and answer_has:
            complete_faqs += 1

    faq_target = 3
    faq_ok = complete_faqs >= faq_target
    has_any_seo = title_ok or description_ok or keywords_ok or faq_has_content
    complete = title_ok and description_ok and keywords_ok and faq_ok

    checks = [
        f"Título {'✓' if title_ok else '✗'}",
        f"Descripción {'✓' if description_ok else '✗'}",
        f"Keywords {'✓' if keywords_ok else '✗'}",
        f"FAQ {min(complete_faqs, faq_target)}/{faq_target} {'✓' if faq_ok else '✗'}",
    ]
    display_name = name or sku

    if complete:
        status = "SEO_COMPLETE"
        message = f"{display_name} ({sku}): SEO completo. " + " · ".join(checks)
    elif not has_any_seo:
        status = "SEO_EMPTY"
        message = f"{display_name} ({sku}): SEO vacío. " + " · ".join(checks)
    else:
        status = "SEO_INCOMPLETE"
        missing: list[str] = []
        if not title_ok:
            missing.append("título")
        if not description_ok:
            missing.append("descripción")
        if not keywords_ok:
            missing.append("keywords")
        if not faq_ok:
            missing.append(f"FAQ ({complete_faqs}/{faq_target} completas)")
        message = f"{display_name} ({sku}): SEO incompleto (parcial). Falta: {', '.join(missing)}. " + " · ".join(checks)

    return status, message, {
        "title_ok": title_ok,
        "description_ok": description_ok,
        "keywords_ok": keywords_ok,
        "complete_faqs": complete_faqs,
        "faq_target": faq_target,
        "complete": complete,
        "has_any_seo": has_any_seo,
    }


def _verify_seo_skus(self, skus, *, scope_label: str = "Selección") -> dict[str, Any]:
    clean_skus = tuple(dict.fromkeys(str(sku).strip() for sku in skus if str(sku).strip()))
    if not clean_skus:
        return {
            "status": "BLOCKED",
            "complete": 0,
            "incomplete": 0,
            "empty": 0,
            "errors": 0,
            "message": "No hay productos para verificar.",
            "items": [],
            "has_seo_skus": [],
            "complete_skus": [],
            "incomplete_skus": [],
            "empty_skus": [],
            "working_set_skus": [],
        }

    items: list[dict[str, Any]] = []
    complete_skus: list[str] = []
    incomplete_skus: list[str] = []
    empty_skus: list[str] = []
    errors = 0

    for sku in clean_skus:
        result = self.verify_seo_sku(sku)
        status = result.get("status")
        if status == "SEO_COMPLETE":
            complete_skus.append(sku)
        elif status == "SEO_INCOMPLETE":
            incomplete_skus.append(sku)
        elif status == "SEO_EMPTY":
            empty_skus.append(sku)
        else:
            errors += 1
        items.append({
            "sku": sku,
            "status": status,
            "message": result.get("message") or "",
            "seo_checks": result.get("seo_checks") or {},
        })

    has_seo_skus = complete_skus + incomplete_skus
    overall = "PARTIAL" if errors else "SEO_AUDIT"
    message = (
        f"{scope_label}: {len(complete_skus)} completo(s), "
        f"{len(incomplete_skus)} incompleto(s) / {len(incomplete_skus)} parcial(es), "
        f"{len(empty_skus)} sin SEO, {errors} error(es)."
    )
    return {
        "status": overall,
        "complete": len(complete_skus),
        "incomplete": len(incomplete_skus),
        "empty": len(empty_skus),
        "errors": errors,
        "message": message,
        "items": items,
        "has_seo_skus": has_seo_skus,
        "complete_skus": complete_skus,
        "incomplete_skus": incomplete_skus,
        "empty_skus": empty_skus,
        "working_set_skus": has_seo_skus,
    }


def _execute_seo_read(self, planned: dict[str, Any], decision: PlannerDecision) -> dict[str, Any]:
    count = int(planned.get("count") or 0)
    if count <= 0:
        return {
            **planned,
            "executed": False,
            "status": "READ_ONLY",
            "message": "No encontré productos para verificar SEO.",
            "working_set_skus": [],
        }
    if count == 1:
        result = _ORIGINAL_EXECUTE_SEO_READ(self, planned, decision)
        if result.get("status") in {"SEO_COMPLETE", "SEO_INCOMPLETE"}:
            result = {**result, "working_set_skus": list(result.get("resolved_skus") or [])}
        elif result.get("status") == "SEO_EMPTY":
            result = {**result, "working_set_skus": []}
        return result

    examined = list(planned.get("resolved_skus") or [])
    audit = self.verify_seo_skus(examined, scope_label="Auditoría SEO")
    return {
        **planned,
        **audit,
        "dry_run": False,
        "executed": False,
        "examined_skus": examined,
        "resolved_skus": list(audit.get("has_seo_skus") or []),
    }


def _execute(self, command: str, *, session_id: int | None = None) -> dict[str, Any]:
    result = _ORIGINAL_EXECUTE(self, command, session_id=session_id)
    safe_skus = working_set_skus_for_result(result)
    if safe_skus is None:
        if result.get("resolved_skus"):
            result = {**result, "candidate_skus": list(result.get("resolved_skus") or []), "resolved_skus": []}
        return result
    if "working_set_skus" in result:
        return {**result, "resolved_skus": list(safe_skus)}
    return result


def install_runtime_behavior() -> None:
    if getattr(AgentBrainRuntime, "_stech_runtime_behavior_v2", False):
        return
    AgentBrainRuntime._seo_summary = classmethod(_seo_summary)
    AgentBrainRuntime.verify_seo_skus = _verify_seo_skus
    AgentBrainRuntime._execute_seo_read = _execute_seo_read
    AgentBrainRuntime.execute = _execute
    AgentBrainRuntime._stech_runtime_behavior_v2 = True
