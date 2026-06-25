"""Load catalogue.json. A stale catalogue must degrade a model to unknown, never block it."""

import json
from functools import lru_cache
from pathlib import Path

from deskfleet.models.schema import ModelSpec, ParamSpec

CATALOGUE_PATH = Path(__file__).parent / "catalogue.json"


@lru_cache(maxsize=1)
def _catalogue() -> dict:
    return json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def default_params() -> list[ParamSpec]:
    return [ParamSpec.model_validate(p) for p in _catalogue()["_default_params"]]


@lru_cache(maxsize=1)
def _by_id() -> dict[str, ModelSpec]:
    specs = {}
    for entry in _catalogue()["models"]:
        spec = ModelSpec.model_validate(entry)
        if not spec.params:
            spec = spec.model_copy(update={"params": default_params()})
        specs[spec.id] = spec
    return specs


def get_model_spec(model_id: str) -> ModelSpec | None:
    return _by_id().get(model_id)


def catalogue_models(provider_id: str | None = None) -> list[ModelSpec]:
    specs = _by_id().values()
    if provider_id is None:
        return list(specs)
    return [s for s in specs if s.provider_id == provider_id]


def unknown_model(model_id: str, provider_id: str) -> ModelSpec:
    """A model the provider offers but the catalogue has never heard of. Still selectable."""
    return ModelSpec(
        id=model_id,
        provider_id=provider_id,
        params=default_params(),
        metadata_available=False,
    )


def reload() -> None:
    _catalogue.cache_clear()
    default_params.cache_clear()
    _by_id.cache_clear()
