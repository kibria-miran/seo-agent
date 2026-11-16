"""Template JSON-LD generation (section 8.5).

Only fields present in ``profiles/site.json`` are filled. The generator never
invents a business name, address, telephone number, rating, review, award,
lender partnership or price. Validation is ``json.loads`` plus an explicit
required-keys check, not a claim of schema.org conformance.

The compliance gate still runs on any user-visible strings before a draft is
written (D-6).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from src.models import SiteProfile

SCHEMA_CONTEXT = "https://schema.org"

_REQUIRED_KEYS: dict[str, tuple[str, ...]] = {
    "FinancialService": ("url",),
    "LocalBusiness": ("url",),
    "FAQPage": ("mainEntity",),
    "BreadcrumbList": ("itemListElement",),
}

_FORBIDDEN_INVENTED_KEYS = frozenset(
    {
        "aggregateRating",
        "review",
        "reviews",
        "ratingValue",
        "reviewCount",
        "priceRange",
        "telephone",
        "address",
        "award",
        "awards",
    }
)


class SchemaError(ValueError):
    """Raised when generated JSON-LD is not structurally valid."""


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def financial_service(profile: SiteProfile, *, kind: str = "FinancialService") -> dict[str, Any]:
    schema: dict[str, Any] = {
        "@context": SCHEMA_CONTEXT,
        "@type": kind,
        "url": profile.base_url,
    }
    if profile.cities:
        schema["areaServed"] = [
            {"@type": "City", "name": city} for city in profile.cities
        ]
    if profile.fca_firm_ref:
        schema["identifier"] = {
            "@type": "PropertyValue",
            "propertyID": "FCA firm reference",
            "value": profile.fca_firm_ref,
        }
    return schema


def faq_page(faqs: Sequence[Mapping[str, Any] | tuple[str, str]]) -> dict[str, Any]:
    if not faqs:
        raise SchemaError("FAQPage needs at least one question")
    entities: list[dict[str, Any]] = []
    for item in faqs:
        if isinstance(item, Mapping):
            question = _clean(item.get("question") or item.get("q"))
            answer = _clean(item.get("answer") or item.get("a"))
        else:
            try:
                question, answer = item
            except (TypeError, ValueError) as exc:
                raise SchemaError(f"FAQ item must be (question, answer): {item!r}") from exc
            question, answer = _clean(question), _clean(answer)
        if not question or not answer:
            raise SchemaError("FAQ entries need a non-empty question and answer")
        entities.append(
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": answer},
            }
        )
    return {"@context": SCHEMA_CONTEXT, "@type": "FAQPage", "mainEntity": entities}


def _absolute(profile: SiteProfile, path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        raise SchemaError(f"breadcrumb path must start with '/': {path!r}")
    return profile.base_url + path


def breadcrumb_list(
    profile: SiteProfile,
    crumbs: Iterable[Mapping[str, Any] | tuple[str, str]],
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    for position, item in enumerate(crumbs, start=1):
        if isinstance(item, Mapping):
            path = _clean(item.get("path") or item.get("url"))
            name = _clean(item.get("name"))
        else:
            try:
                path, name = item
            except (TypeError, ValueError) as exc:
                raise SchemaError(f"breadcrumb item must be (path, name): {item!r}") from exc
            path, name = _clean(path), _clean(name)
        if not path or not name:
            raise SchemaError("breadcrumb entries need a path and a name")
        elements.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": name,
                "item": _absolute(profile, path),
            }
        )
    if not elements:
        raise SchemaError("BreadcrumbList needs at least one item")
    return {
        "@context": SCHEMA_CONTEXT,
        "@type": "BreadcrumbList",
        "itemListElement": elements,
    }


def validate_schema(value: Any) -> dict[str, Any]:
    """Ensure the object is serialisable JSON-LD with required keys."""

    try:
        round_tripped = json.loads(json.dumps(value, sort_keys=True, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise SchemaError(f"schema is not JSON-serialisable: {exc}") from exc
    if not isinstance(round_tripped, dict):
        raise SchemaError("schema must be a JSON object")
    if round_tripped.get("@context") != SCHEMA_CONTEXT:
        raise SchemaError(f"schema @context must be {SCHEMA_CONTEXT!r}")
    schema_type = round_tripped.get("@type")
    if not isinstance(schema_type, str) or not schema_type:
        raise SchemaError("schema @type is missing")
    for key in _REQUIRED_KEYS.get(schema_type, ()):
        if not round_tripped.get(key):
            raise SchemaError(f"{schema_type} schema is missing {key!r}")
    forbidden = _FORBIDDEN_INVENTED_KEYS & set(round_tripped)
    if forbidden:
        raise SchemaError(
            "schema contains fields this generator must not invent: "
            + ", ".join(sorted(forbidden))
        )
    return round_tripped


def generate(
    profile: SiteProfile,
    kind: str = "FinancialService",
    *,
    faqs: Sequence[Mapping[str, Any] | tuple[str, str]] | None = None,
    crumbs: Iterable[Mapping[str, Any] | tuple[str, str]] | None = None,
) -> dict[str, Any]:
    normalised = (kind or "").strip()
    if normalised in {"FinancialService", "LocalBusiness"}:
        schema = financial_service(profile, kind=normalised)
    elif normalised == "FAQPage":
        schema = faq_page(faqs or [])
    elif normalised == "BreadcrumbList":
        schema = breadcrumb_list(profile, crumbs or [])
    else:
        raise ValueError(
            "unsupported schema kind: "
            f"{kind!r} (expected FinancialService, LocalBusiness, FAQPage or BreadcrumbList)"
        )
    return validate_schema(schema)


def to_json(value: Mapping[str, Any]) -> str:
    """Stable JSON for writing into a draft or report."""

    return json.dumps(validate_schema(value), sort_keys=True, indent=2, ensure_ascii=False)


def schema_types() -> tuple[str, ...]:
    return ("FinancialService", "LocalBusiness", "FAQPage", "BreadcrumbList")


__all__ = [
    "SchemaError",
    "breadcrumb_list",
    "faq_page",
    "financial_service",
    "generate",
    "schema_types",
    "to_json",
    "validate_schema",
]
