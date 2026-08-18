from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import click

from plane_cli.client import PlaneAPIError, PlaneClient
from plane_cli.config import Config, ConfigError, LlmSettings, load_config, resolve_llm
from plane_cli.llm import (
    LlmError,
    draft_support_demand,
    draft_technical_demand,
    draft_work_item,
    sanitize_title,
)
from plane_cli.mapping import MappingError, load_projects_map, resolve_tech_project
from plane_cli.templates import (
    RELATION_IMPLEMENTS,
    extract_support_facts,
    support_demand_html,
    technical_demand_html,
    work_item_html,
)

PRIORITIES = ["urgent", "high", "medium", "low", "none"]
INTAKE_WAITING_LABEL = "aguardando interno"


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


def llm_or_abort(cfg: Config) -> LlmSettings:
    try:
        return resolve_llm(cfg)
    except ConfigError as exc:
        raise Abort(str(exc)) from exc


def require_relato(description: str | None, description_file: str | None) -> str:
    relato = text_from_options(description, description_file)
    if not (relato or "").strip():
        raise Abort("Informe --description ou --description-file com o relato da demanda.")
    return relato.strip()


def draft_support_from_relato(
    *,
    relato: str,
    title: str | None,
    labels: tuple[str, ...] | list[str],
    necessidade: str | None,
    cenario: str | None,
    resultado: str | None,
    solicitante_nome: str | None,
    organizacao: str | None,
    canal: str | None,
    llm_settings: LlmSettings,
) -> dict[str, Any]:
    click.echo(f"Redigindo demanda de suporte com {llm_settings.provider}...", err=True)
    try:
        draft = draft_support_demand(
            relato=relato,
            titulo=title,
            labels=list(labels),
            settings=llm_settings,
        )
    except LlmError as exc:
        raise Abort(str(exc)) from exc
    if necessidade:
        draft["necessidade"] = necessidade.strip()
    if cenario:
        draft["cenario_atual"] = cenario.strip()
    if resultado:
        draft["resultado_esperado"] = resultado.strip()
    if solicitante_nome:
        draft["solicitante_nome"] = solicitante_nome.strip()
    if organizacao:
        draft["organizacao"] = organizacao.strip()
    if canal:
        draft["canal"] = canal.strip()
    name = sanitize_title(title) or sanitize_title(draft.get("titulo"))
    if not name:
        raise Abort("Não foi possível definir o título da demanda de suporte.")
    draft["titulo"] = name
    return draft


@click.group()
def cli() -> None:
    """Abre demandas de suporte e técnicas no Plane a partir do terminal."""


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
    """Intake no projeto de suporte (desenvolvedor, quando não há demanda)."""


@intake_group.command("create")
@click.option("--title", default=None, help="Sobrescreve o título gerado pela IA.")
@click.option("--description", default=None, help="Relato livre usado como insumo da IA.")
@click.option("--description-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--priority", type=click.Choice(PRIORITIES, case_sensitive=False), default="none")
@click.option(
    "--label",
    "labels",
    multiple=True,
    help="Nome ou UUID da label (repetível). Use produto:<sistema>.",
)
@click.option("--necessidade", default=None, help="Sobrescreve a seção Necessidade depois da IA.")
@click.option("--cenario", default=None, help="Sobrescreve a seção Cenário atual depois da IA.")
@click.option("--resultado", default=None, help="Sobrescreve a seção Resultado esperado depois da IA.")
@click.option("--solicitante-nome", default=None, help="Sobrescreve o nome do solicitante.")
@click.option("--organizacao", default=None, help="Sobrescreve organização/área.")
@click.option("--canal", default=None, help="Sobrescreve o canal de entrada.")
def intake_create(
    title: str | None,
    description: str | None,
    description_file: str | None,
    priority: str,
    labels: tuple[str, ...],
    necessidade: str | None,
    cenario: str | None,
    resultado: str | None,
    solicitante_nome: str | None,
    organizacao: str | None,
    canal: str | None,
) -> None:
    """Cria um Intake no projeto de suporte com o mesmo template da demanda de suporte."""
    cfg = load_or_abort(require_support_project=True)
    relato = require_relato(description, description_file)
    llm_settings = llm_or_abort(cfg)
    try:
        with client_from(cfg) as client:
            project = client.get_project(cfg.support_project_id)
            project_labels = client.list_labels(cfg.support_project_id)
            label_ids, label_names = resolve_label_ids(labels, project_labels)
            waiting_ids, _waiting_names = resolve_label_ids(
                (INTAKE_WAITING_LABEL,),
                project_labels,
                strict=False,
            )
            if not waiting_ids:
                click.echo(
                    f"Aviso: label '{INTAKE_WAITING_LABEL}' não encontrada no projeto "
                    "SUPORTE. Crie-a no Plane. O Intake será aberto sem a label.",
                    err=True,
                )
            for label_id in waiting_ids:
                if label_id not in label_ids:
                    label_ids.append(label_id)
            if not any(name.lower().startswith("produto:") for name in label_names):
                click.echo(
                    "Aviso: nenhuma label produto:... — a demanda técnica depois depende disso.",
                    err=True,
                )
            current_user = client.me()
            responsavel_nome = client.user_display_name(current_user)
            draft = draft_support_from_relato(
                relato=relato,
                title=title,
                labels=labels,
                necessidade=necessidade,
                cenario=cenario,
                resultado=resultado,
                solicitante_nome=solicitante_nome,
                organizacao=organizacao,
                canal=canal,
                llm_settings=llm_settings,
            )
            item = client.create_intake(
                cfg.support_project_id,
                name=str(draft["titulo"]),
                description_html=support_demand_html(
                    draft=draft,
                    responsavel=responsavel_nome,
                ),
                priority=priority.lower(),
                labels=label_ids or None,
            )
            emit(client.summarize(cfg.support_project_id, item, project))
    except PlaneAPIError as exc:
        raise Abort(str(exc)) from exc


def resolve_label_ids(
    requested: tuple[str, ...],
    project_labels: list[dict[str, Any]],
    *,
    strict: bool = True,
) -> tuple[list[str], list[str]]:
    by_name = {
        str(label.get("name") or "").strip().lower(): label for label in project_labels
    }
    by_id = {str(label.get("id") or ""): label for label in project_labels if label.get("id")}
    ids: list[str] = []
    names: list[str] = []
    missing: list[str] = []
    for raw in requested:
        key = raw.strip()
        if not key:
            continue
        match = by_id.get(key) or by_name.get(key.lower())
        if not match:
            missing.append(raw)
            continue
        label_id = str(match.get("id") or "")
        if label_id and label_id not in ids:
            ids.append(label_id)
            names.append(str(match.get("name") or key))
    if missing and strict:
        available = ", ".join(
            sorted(str(label.get("name") or "") for label in project_labels if label.get("name"))
        )
        raise Abort(
            "Label(s) não encontrada(s): "
            + ", ".join(missing)
            + (f". Disponíveis: {available}" if available else ".")
        )
    return ids, names


@cli.group("suporte")
def suporte_group() -> None:
    """Demanda de suporte no board SUPORTE (já com template)."""


@suporte_group.command("create")
@click.option("--title", default=None, help="Sobrescreve o título gerado pela IA.")
@click.option("--description", default=None, help="Relato livre usado como insumo da IA.")
@click.option("--description-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--priority", type=click.Choice(PRIORITIES, case_sensitive=False), default="none")
@click.option(
    "--label",
    "labels",
    multiple=True,
    help="Nome ou UUID da label (repetível). Use produto:<sistema>.",
)
@click.option("--necessidade", default=None, help="Sobrescreve a seção Necessidade depois da IA.")
@click.option("--cenario", default=None, help="Sobrescreve a seção Cenário atual depois da IA.")
@click.option("--resultado", default=None, help="Sobrescreve a seção Resultado esperado depois da IA.")
@click.option("--solicitante-nome", default=None, help="Sobrescreve o nome do solicitante.")
@click.option("--organizacao", default=None, help="Sobrescreve organização/área.")
@click.option("--canal", default=None, help="Sobrescreve o canal de entrada.")
def suporte_create(
    title: str | None,
    description: str | None,
    description_file: str | None,
    priority: str,
    labels: tuple[str, ...],
    necessidade: str | None,
    cenario: str | None,
    resultado: str | None,
    solicitante_nome: str | None,
    organizacao: str | None,
    canal: str | None,
) -> None:
    """Cria um work item no board de suporte com o template preenchido pela IA."""
    cfg = load_or_abort(require_support_project=True)
    relato = require_relato(description, description_file)
    llm_settings = llm_or_abort(cfg)

    client = client_from(cfg)
    try:
        project = client.get_project(cfg.support_project_id)
        project_labels = client.list_labels(cfg.support_project_id)
        label_ids, label_names = resolve_label_ids(labels, project_labels)
        if not any(name.lower().startswith("produto:") for name in label_names):
            click.echo(
                "Aviso: nenhuma label produto:... — a demanda técnica depois depende disso.",
                err=True,
            )

        current_user = client.me()
        creator_id = str(current_user.get("id") or "")
        responsavel_nome = client.user_display_name(current_user)
        draft = draft_support_from_relato(
            relato=relato,
            title=title,
            labels=labels,
            necessidade=necessidade,
            cenario=cenario,
            resultado=resultado,
            solicitante_nome=solicitante_nome,
            organizacao=organizacao,
            canal=canal,
            llm_settings=llm_settings,
        )

        item = client.create_work_item(
            cfg.support_project_id,
            name=str(draft["titulo"]),
            description_html=support_demand_html(
                draft=draft,
                responsavel=responsavel_nome,
            ),
            priority=priority.lower(),
            labels=label_ids or None,
            created_by=creator_id or None,
            assignees=[creator_id] if creator_id else None,
        )
        emit(client.summarize(cfg.support_project_id, item, project))
    except PlaneAPIError as exc:
        raise Abort(str(exc)) from exc
    finally:
        client.close()


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
