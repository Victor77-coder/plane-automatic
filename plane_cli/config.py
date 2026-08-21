from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _find_env_path() -> Path | None:
    for candidate in (Path.cwd() / ".env", ROOT / ".env", ROOT.parent / ".env"):
        if candidate.is_file():
            return candidate
    return None


class ConfigError(RuntimeError):
    pass


def normalize_workspace_slug(value: str) -> str:
    raw = value.strip().rstrip("/")
    if not raw:
        return ""
    if "://" in raw or raw.startswith("/") or "/" in raw:
        parsed = urlparse(raw if "://" in raw else f"https://placeholder.local/{raw.lstrip('/')}")
        parts = [p for p in parsed.path.split("/") if p and p.lower() != "projects"]
        if parts:
            return parts[0]
        return raw
    return raw


def normalize_project_id(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    match = UUID_RE.search(raw)
    return match.group(0) if match else raw.rstrip("/")


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    workspace_slug: str
    support_project_id: str
    projects_yaml: Path
    llm_provider: str
    groq_api_key: str
    groq_model: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    api_key: str
    model: str
    base_url: str


def projects_yaml_path() -> Path:
    cwd = Path.cwd() / "projects.yaml"
    if cwd.exists():
        return cwd
    return ROOT / "projects.yaml"


def load_config(*, require_support_project: bool = False) -> Config:
    env_path = _find_env_path()
    raw: dict[str, str | None] = {}
    if env_path:
        raw = dotenv_values(env_path)

    def _get(key: str, default: str = "") -> str:
        return str(raw.get(key, default) or default).strip()

    api_key = _get("PLANE_API_KEY")
    workspace = normalize_workspace_slug(_get("PLANE_WORKSPACE_SLUG"))
    if not api_key:
        raise ConfigError(
            "PLANE_API_KEY não definido. Copie .env.example para .env e preencha o token."
        )
    if not workspace:
        raise ConfigError(
            "PLANE_WORKSPACE_SLUG não definido. É o slug da URL "
            "(https://plane.promaxima.cloud/<slug>/projects/)."
        )

    support_project_id = normalize_project_id(_get("PLANE_SUPPORT_PROJECT_ID"))
    if require_support_project and not support_project_id:
        raise ConfigError(
            "PLANE_SUPPORT_PROJECT_ID não definido. Rode `python -m plane_cli projects` "
            "e grave o UUID do projeto de Suporte no .env."
        )

    return Config(
        base_url=_get("PLANE_BASE_URL", "https://plane.promaxima.cloud").rstrip("/"),
        api_key=api_key,
        workspace_slug=workspace,
        support_project_id=support_project_id,
        projects_yaml=projects_yaml_path(),
        llm_provider=_get("PLANE_LLM_PROVIDER", "groq").lower() or "groq",
        groq_api_key=_get("GROQ_API_KEY"),
        groq_model=_get("GROQ_MODEL", "llama-3.3-70b-versatile")
        or "llama-3.3-70b-versatile",
        openai_api_key=_get("OPENAI_API_KEY"),
        openai_model=_get("OPENAI_MODEL", "gpt-4o-mini") or "gpt-4o-mini",
        openai_base_url=_get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        or "https://api.openai.com/v1",
    )


def resolve_llm(cfg: Config) -> LlmSettings:
    provider = cfg.llm_provider if cfg.llm_provider in {"groq", "openai"} else "groq"
    if provider == "groq":
        if cfg.groq_api_key:
            return LlmSettings(
                provider="groq",
                api_key=cfg.groq_api_key,
                model=cfg.groq_model,
                base_url="https://api.groq.com/openai/v1",
            )
        if cfg.openai_api_key:
            return LlmSettings(
                provider="openai",
                api_key=cfg.openai_api_key,
                model=cfg.openai_model,
                base_url=cfg.openai_base_url,
            )
        raise ConfigError(
            "Nenhuma chave de LLM. Defina GROQ_API_KEY (recomendado) ou OPENAI_API_KEY no .env. "
            "O CLI redige o template por IA e não cola o texto cru."
        )
    if not cfg.openai_api_key:
        raise ConfigError("PLANE_LLM_PROVIDER=openai exige OPENAI_API_KEY no .env.")
    return LlmSettings(
        provider="openai",
        api_key=cfg.openai_api_key,
        model=cfg.openai_model,
        base_url=cfg.openai_base_url,
    )
