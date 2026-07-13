from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ModelRoute:
    name: str
    provider: str
    temperature: float
    requires_network: bool = False
    requires_human_final_approval: bool = False
    fallback_routes: tuple[str, ...] = ()
    timeout_seconds: float = 45.0
    max_retries: int = 2


@dataclass(frozen=True)
class ResolvedModelRoute:
    name: str
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float
    requires_network: bool
    requires_human_final_approval: bool
    timeout_seconds: float
    max_retries: int
    configured: bool
    configuration_errors: tuple[str, ...] = ()


class ModelRouter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @classmethod
    def from_json_file(cls, path: str | Path) -> "ModelRouter":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def route(self, task_route: str) -> ModelRoute:
        data = self.config["routes"][task_route]
        return ModelRoute(
            name=task_route,
            provider=data["provider"],
            temperature=float(data.get("temperature", 0.0)),
            requires_network=bool(data.get("requires_network", False)),
            requires_human_final_approval=bool(data.get("requires_human_final_approval", False)),
            fallback_routes=tuple(str(item) for item in data.get("fallback_routes", [])),
            timeout_seconds=float(data.get("timeout_seconds", 45.0)),
            max_retries=int(data.get("max_retries", 2)),
        )

    def resolve(
        self,
        task_route: str,
        environ: Mapping[str, str] | None = None,
    ) -> ResolvedModelRoute:
        env = environ if environ is not None else os.environ
        route = self.route(task_route)
        provider = self.config.get("providers", {}).get(route.provider, {})
        if not isinstance(provider, dict):
            provider = {}

        base_url = _env_value(env, provider.get("endpoint_env"))
        api_key = _env_value(env, provider.get("api_key_env"))
        model = _model_value(provider, env)
        api_key_required = bool(provider.get("api_key_required", route.requires_network))
        errors: list[str] = []
        if not base_url:
            errors.append("endpoint_not_configured")
        if not model:
            errors.append("model_not_configured")
        if api_key_required and not api_key:
            errors.append("api_key_not_configured")

        timeout_override = _positive_float(
            env.get("MARKETING_MACHINE_MODEL_TIMEOUT_SECONDS", env.get("MARKETING_AI_TIMEOUT_SECONDS")),
            route.timeout_seconds,
        )
        retries_override = _non_negative_int(
            env.get("MARKETING_MACHINE_MODEL_RETRIES", env.get("MARKETING_AI_MAX_RETRIES")),
            route.max_retries,
        )
        return ResolvedModelRoute(
            name=route.name,
            provider=route.provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=route.temperature,
            requires_network=route.requires_network,
            requires_human_final_approval=route.requires_human_final_approval,
            timeout_seconds=timeout_override,
            max_retries=retries_override,
            configured=not errors,
            configuration_errors=tuple(errors),
        )

    def resolve_chain(
        self,
        task_route: str,
        environ: Mapping[str, str] | None = None,
    ) -> list[ResolvedModelRoute]:
        route = self.route(task_route)
        names = [route.name, *route.fallback_routes]
        seen: set[str] = set()
        resolved: list[ResolvedModelRoute] = []
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            resolved.append(self.resolve(name, environ=environ))
        return resolved


def _model_value(provider: dict[str, Any], environ: Mapping[str, str]) -> str:
    for key in ("model_env", "fallback_model_env"):
        value = _env_value(environ, provider.get(key))
        if value:
            return value
    configured = str(provider.get("model", "")).strip()
    if configured and configured != "configured-by-env":
        return configured
    return ""


def _env_value(environ: Mapping[str, str], name: Any) -> str:
    if not isinstance(name, str) or not name:
        return ""
    return str(environ.get(name, "")).strip()


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default
