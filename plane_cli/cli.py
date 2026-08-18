from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from plane_cli.client import PlaneAPIError, PlaneClient
from plane_cli.config import Config, ConfigError, load_config, resolve_llm
from plane_cli.llm import LlmError, draft_technical_demand, draft_work_item, sanitize_title
from plane_cli.mapping import MappingError, load_projects_map, resolve_tech_project
from plane_cli.templates import (
    RELATION_IMPLEMENTS,
    extract_support_facts,
    support_demand_html,
    technical_demand_html,
    work_item_html,
)

PRIORITIES = ["urgent", "high", "medium", "low", "none"]


class Abort(click.ClickException):
    def show(self, file: Any | None = None) -> None:
        click.echo(self.message, err=True)


def emit(data: Any) -> None:
    click.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def text_from_options(value: str | None, file: str | None) -> str | None:
    if file:
        return Path(file).read_text(encoding="utf-8")
    return value


def load_or_abort(*, require_support_project: bool = False) -> Config:
    try:
        return load_config(require_support_project=require_support_project)
    except ConfigError as exc:
        raise Abort(str(exc)) from exc


def client_from(cfg: Config) -> PlaneClient:
    return PlaneClient(cfg.base_url, cfg.api_key, cfg.workspace_slug)


@click.group()
def cli() -> None:
    """Abre Intake de suporte e demandas técnicas no Plane."""


@cli.command("projects")
def projects_cmd() -> None:
    """Lista projetos do workspace (id, identifier, name)."""
    cfg = load_or_abort()
    try:
        with client_from(cfg) as client:
            rows = client.list_projects()
    except PlaneAPIError as exc:
        raise Abort(str(exc)) from exc
    if not rows:
        click.echo("Nenhum projeto encontrado.", err=True)
        return
    click.echo("id\tidentifier\tname")
    for project in sorted(rows, key=lambda p: str(p.get("name") or "")):
        click.echo(
            f"{project.get('id')}\t{project.get('identifier')}\t{project.get('name')}"
        )


@cli.command("labels")
@click.option("--project-id", default=None, help="UUID do projeto (default: projeto de suporte).")
def labels_cmd(project_id: str | None) -> None:
    """Lista labels do projeto (default: suporte)."""
    cfg = load_or_abort(require_support_project=not project_id)
    target = project_id or cfg.support_project_id
    try:
        with client_from(cfg) as client:
            rows = client.list_labels(target)
    except PlaneAPIError as exc:
        raise Abort(str(exc)) from exc
    if not rows:
        click.echo("Nenhuma label encontrada.", err=True)
        return
    click.echo("id\tname")
    for label in sorted(rows, key=lambda item: str(item.get("name") or "")):
        click.echo(f"{label.get('id')}\t{label.get('name')}")


@cli.command("states")
@click.option("--project-id", default=None, help="UUID do projeto (default: projeto de suporte).")
def states_cmd(project_id: str | None) -> None:
    """Lista estados do workflow do projeto."""
    cfg = load_or_abort(require_support_project=not project_id)
    target = project_id or cfg.support_project_id
    try:
        with client_from(cfg) as client:
            rows = client.list_states(target)
    except PlaneAPIError as exc:
        raise Abort(str(exc)) from exc
    if not rows:
        click.echo("Nenhum estado encontrado.", err=True)
        return
    click.echo("id\tgroup\tname")
    for state in sorted(rows, key=lambda item: (item.get("sequence") or 0, str(item.get("name") or ""))):
        click.echo(f"{state.get('id')}\t{state.get('group')}\t{state.get('name')}")


@cli.group("intake")
def intake_group() -> None:
    """Intake no projeto de suporte (quando ainda não há demanda)."""


@intake_group.command("create")
@click.option("--title", required=True, help="Título do Intake.")
@click.option("--description", default=None, help="Texto da seção Necessidade.")
@click.option("--description-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--priority", type=click.Choice(PRIORITIES, case_sensitive=False), default="none")
def intake_create(
    title: str,
    description: str | None,
    description_file: str | None,
    priority: str,
) -> None:
    """Cria um Intake no projeto de suporte com o template da demanda de suporte."""
    cfg = load_or_abort(require_support_project=True)
    body = text_from_options(description, description_file)
    try:
        with client_from(cfg) as client:
            project = client.get_project(cfg.support_project_id)
            item = client.create_intake(
                cfg.support_project_id,
                name=title,
                description_html=support_demand_html(necessidade=body),
                priority=priority.lower(),
            )
            emit(client.summarize(cfg.support_project_id, item, project))
    except PlaneAPIError as exc:
        raise Abort(str(exc)) from exc


@cli.group("tecnica")
def tecnica_group() -> None:
    """Demanda técnica a partir de uma demanda de suporte."""


@tecnica_group.command("create")
@click.option("--from", "from_id", required=True, help="UUID ou chave da demanda de suporte (ex.: SUPORTE-123).")
@click.option("--project-id", default=None, help="Força o projeto técnico (ignora o mapa de labels).")
@click.option("--title", default=None, help="Sobrescreve o título gerado pela IA para a demanda técnica.")
@click.option("--description", default=None, help="Preenche a seção Problema técnico.")
@click.option("--description-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--solucao", default=None, help="Preenche a seção Solução proposta.")
@click.option("--solucao-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--priority", type=click.Choice(PRIORITIES, case_sensitive=False), default=None)
@click.option("--trabalho", default=None, help="Orientação extra para a IA do sub-item Trabalho.")
@click.option("--trabalho-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--trabalho-title", default=None, help="Sobrescreve o título gerado pela IA para o sub-item Trabalho.")
def tecnica_create(
    from_id: str,
    project_id: str | None,
    title: str | None,
    description: str | None,
    description_file: str | None,
    solucao: str | None,
    solucao_file: str | None,
    priority: str | None,
    trabalho: str | None,
    trabalho_file: str | None,
    trabalho_title: str | None,
) -> None:
    """Cria a demanda técnica (template), a relação implements e o sub-item de trabalho."""
    cfg = load_or_abort(require_support_project=True)
    override_description = text_from_options(description, description_file)
    solucao_text = text_from_options(solucao, solucao_file)
    trabalho_text = text_from_options(trabalho, trabalho_file)

    try:
        mapping = None if project_id else load_projects_map(cfg.projects_yaml)
    except MappingError as exc:
        raise Abort(str(exc)) from exc

    client = client_from(cfg)
    try:
        support_project = client.get_project(cfg.support_project_id)
        support_item = client.retrieve_work_item(cfg.support_project_id, from_id)
        support_labels = client.list_labels(cfg.support_project_id)
        label_names = client.label_names(support_item, support_labels)

        try:
            tech_project_id, matched_label = resolve_tech_project(
                label_names,
                mapping or {},
                override_project_id=project_id,
            )
        except MappingError as exc:
            raise Abort(str(exc)) from exc

        tech_project = client.get_project(tech_project_id)
        support_title = sanitize_title(str(support_item.get("name") or ""))

        origem_key = client.issue_key(support_item, support_project)
        origem_url = client.work_item_url(cfg.support_project_id, support_item, support_project)
        current_user = client.me()
        creator_id = str(current_user.get("id") or "")
        responsavel_nome = client.user_display_name(current_user)

        try:
            llm_settings = resolve_llm(cfg)
        except ConfigError as exc:
            raise Abort(str(exc)) from exc

        facts = extract_support_facts(
            support_item,
            origem_key=origem_key,
            labels=label_names,
        )
        click.echo(f"Redigindo demanda técnica com {llm_settings.provider}...", err=True)
        try:
            draft = draft_technical_demand(facts, llm_settings)
        except LlmError as exc:
            raise Abort(str(exc)) from exc

        if override_description:
            draft["problema"] = override_description
        if solucao_text:
            draft["solucao"] = solucao_text

        tech_name = sanitize_title(title) or sanitize_title(draft.get("titulo")) or support_title
        if not tech_name:
            raise Abort("Não foi possível definir o título da demanda técnica.")
        draft["titulo"] = tech_name

        tech_html = technical_demand_html(
            origem_key=origem_key,
            origem_url=origem_url,
            relacao=RELATION_IMPLEMENTS,
            draft=draft,
            responsavel=responsavel_nome,
        )

        tech_priority = (priority or support_item.get("priority") or "none").lower()
        if tech_priority not in PRIORITIES:
            tech_priority = "none"

        assignees = [creator_id] if creator_id else None
        tech_item = client.create_work_item(
            tech_project_id,
            name=tech_name,
            description_html=tech_html,
            priority=tech_priority,
            created_by=creator_id or None,
            assignees=assignees,
        )

        relation = client.relate_or_link(
            tech_project_id=tech_project_id,
            tech_item=tech_item,
            support_project_id=cfg.support_project_id,
            support_item=support_item,
            relation_type=RELATION_IMPLEMENTS,
        )

        payload = {
            "support": client.summarize(cfg.support_project_id, support_item, support_project),
            "tecnica": client.summarize(tech_project_id, tech_item, tech_project),
            "label": matched_label,
            "relation": {"type": relation.get("type")},
            "url": client.work_item_url(tech_project_id, tech_item, tech_project),
        }

        click.echo(f"Redigindo sub-item Trabalho com {llm_settings.provider}...", err=True)
        try:
            work_draft = draft_work_item(
                draft,
                llm_settings,
                titulo=tech_name,
                labels=label_names,
                orientacao=trabalho_text,
            )
            child_title = (
                sanitize_title(trabalho_title)
                or sanitize_title(work_draft.get("titulo"))
                or f"Implementar: {tech_name}"
            )
            work_draft["titulo"] = child_title
            trabalho_html_body = work_item_html(
                draft=work_draft,
                responsavel=responsavel_nome,
                prioridade=work_draft.get("prioridade") or tech_priority,
            )
            trabalho_item = client.create_work_item(
                tech_project_id,
                name=child_title,
                description_html=trabalho_html_body,
                priority=tech_priority,
                parent=str(tech_item["id"]),
                created_by=creator_id or None,
                assignees=assignees,
            )
        except (LlmError, PlaneAPIError) as exc:
            payload["trabalho"] = None
            payload["error"] = (
                "Demanda técnica criada, mas o sub-item de trabalho falhou. "
                f"Preencha manualmente no Plane. {exc}"
            )
            emit(payload)
            raise Abort(payload["error"]) from exc

        payload["trabalho"] = client.summarize(tech_project_id, trabalho_item, tech_project)
        emit(payload)
    except PlaneAPIError as exc:
        raise Abort(str(exc)) from exc
    finally:
        client.close()


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
