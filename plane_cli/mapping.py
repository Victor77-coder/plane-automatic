from __future__ import annotations

from pathlib import Path

import yaml

from plane_cli.config import UUID_RE, normalize_project_id


class MappingError(RuntimeError):
    pass


def load_projects_map(path: Path) -> dict[str, str]:
    if not path.exists():
        raise MappingError(
            f"Arquivo {path} não encontrado. Copie projects.yaml.example para projects.yaml "
            "e preencha os UUIDs (`python -m plane_cli projects`)."
        )
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise MappingError(f"{path} deve ser um mapa label → UUID do projeto.")

    mapping: dict[str, str] = {}
    for key, value in data.items():
        name = str(key).strip().lower()
        project_id = normalize_project_id(str(value))
        if not name or not UUID_RE.fullmatch(project_id):
            continue
        mapping[name] = project_id
    if not mapping:
        raise MappingError(
            f"{path} não tem nenhum mapeamento válido. Substitua os placeholders pelos UUIDs reais."
        )
    return mapping


def resolve_tech_project(
    label_names: list[str],
    mapping: dict[str, str],
    *,
    override_project_id: str | None = None,
) -> tuple[str, str | None]:
    """Retorna (project_id, label_usada)."""
    if override_project_id:
        return override_project_id.strip(), None

    matches: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for name in label_names:
        key = name.strip().lower()
        project_id = mapping.get(key)
        if not project_id or project_id in seen_ids:
            continue
        seen_ids.add(project_id)
        matches.append((name, project_id))

    if not matches:
        found = ", ".join(label_names) if label_names else "(nenhuma)"
        known = ", ".join(sorted(mapping))
        raise MappingError(
            "Nenhuma label da demanda de suporte bate com projects.yaml.\n"
            f"Labels na demanda: {found}\n"
            f"Labels mapeadas: {known}\n"
            "Passe --project-id para forçar o destino."
        )
    if len(matches) > 1:
        detail = ", ".join(f"{name} → {pid}" for name, pid in matches)
        raise MappingError(
            "A demanda de suporte tem mais de uma label mapeada para projetos diferentes.\n"
            f"{detail}\n"
            "Passe --project-id para escolher o destino."
        )
    name, project_id = matches[0]
    return project_id, name
