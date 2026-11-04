"""Where a Hermes model route sits in AGOS's model picker, both ways: a Hermes
provider name read from a profile -> the picker's provider id and way in, and a
picker choice -> the fallback chain as Hermes keeps it (Hermes's provider slug).
Settings → Models (helper models, fallback chain) and the Co-Founder's
`set_fallback` read and write through here.

Must not: read or write a Hermes config (actions/hermes_fallback.py and
actions/hermes_helper_models.py do), or know about HTTP.
"""

from __future__ import annotations

from typing import Any, Literal

from agos_core.engine.models import AGOS_ID, hermes_slug, slug_mode

__all__ = ["Mode", "fallback_chain", "helper_route", "picker_place"]

Mode = Literal["cli", "api"]


def picker_place(
    provider: str, base_url: str, keyed: bool = False
) -> tuple[str | None, Mode | None]:
    """Where a Hermes provider name sits in AGOS's model picker (catalog id + way in)."""
    agos = AGOS_ID.get(provider.lower())
    if agos is not None:
        return agos, slug_mode(provider.lower(), keyed=keyed)
    if provider and not base_url:
        return provider, "api"  # Hermes's other providers: listed by their own name
    return None, None


def helper_route(task: dict[str, Any]) -> dict[str, Any]:
    """Where a helper task's calls go: `main` when Hermes uses the main model (its
    `auto`), else the provider + model and their place in the picker."""
    values = {f["name"]: f["value"] for f in task["fields"]}

    def text(name: str) -> str:
        value = values.get(name)
        return value.strip() if isinstance(value, str) else ""

    provider, model, base_url = text("provider"), text("model"), text("base_url")
    main = provider.lower() in ("", "auto") and model.lower() in ("", "auto") and not base_url
    auto = provider.lower() in ("", "auto")  # with a model: the main provider, that model
    agos, mode = (None, None) if auto else picker_place(provider, base_url)
    return {
        "main": main,
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "catalog_provider": agos,
        "mode": mode,
    }


def fallback_chain(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """The chain as Hermes keeps it: AGOS's provider + mode as Hermes's slug."""
    return [
        {
            "provider": hermes_slug(str(e["provider"]), str(e["mode"]))
            if e.get("mode")
            else str(e.get("provider") or ""),
            "model": str(e.get("model") or ""),
            "base_url": str(e.get("base_url") or ""),
        }
        for e in entries
    ]
