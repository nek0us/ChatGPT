"""Conservative account-capability extraction from authenticated responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_PLAN_KEYS = {
    "plan",
    "plan_name",
    "account_plan",
    "subscription",
    "subscription_plan",
    "subscription_level",
    "tier",
    "entitlement",
    "entitlement_name",
    "product",
    "product_name",
}
_KNOWN_PLANS = {"free", "go", "plus", "pro"}


@dataclass(frozen=True)
class AccountPlan:
    """A plan observation that never treats a local configuration as evidence."""

    value: str = "unknown"
    source: str = "unavailable"
    evidence: tuple[str, ...] = ()


def _normalized_plan(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = "".join(character for character in value.lower() if character.isalnum())
    for plan in _KNOWN_PLANS:
        if compact in {plan, f"chatgpt{plan}", f"openai{plan}"}:
            return plan
    return None


def discover_account_plan(payload: Any, source: str) -> AccountPlan:
    """Extract one unambiguous account plan from a provider response.

    Only explicit plan-like field names count as evidence. Model labels and broad
    free-form text are intentionally ignored because a catalog can contain tiers
    the current account does not own.
    """

    found: list[tuple[str, str]] = []

    def visit(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_name = str(key).lower().replace("-", "_").replace(" ", "_")
                child_path = f"{path}.{key}" if path else str(key)
                if key_name in _PLAN_KEYS:
                    plan = _normalized_plan(child)
                    if plan:
                        found.append((plan, child_path))
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(payload)
    plans = {plan for plan, _ in found}
    if len(plans) != 1:
        return AccountPlan(
            source=source if found else "unavailable",
            evidence=tuple(path for _, path in found),
        )
    return AccountPlan(
        value=plans.pop(),
        source=source,
        evidence=tuple(path for _, path in found),
    )


def infer_plan_from_model_categories(levels: Any, source: str) -> AccountPlan:
    """Infer a plan only when every observed model category agrees on one tier."""
    if not isinstance(levels, list):
        return AccountPlan()
    plans = {_normalized_plan(level) for level in levels}
    plans.discard(None)
    if len(plans) != 1:
        return AccountPlan(source=source if plans else "unavailable")
    return AccountPlan(
        value=plans.pop(),
        source=source,
        evidence=tuple(str(level) for level in levels if _normalized_plan(level)),
    )


def supports_paid_models(plan: Any, legacy_gptplus: bool) -> bool:
    """Use observed plan evidence without treating Go as the old Plus superset."""
    normalized = _normalized_plan(plan)
    if normalized == "free":
        return False
    if normalized in {"plus", "pro"}:
        return True
    return legacy_gptplus
