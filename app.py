from __future__ import annotations

import os
import re
import traceback
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from flask import Flask, jsonify, render_template, request

from plane_cli.client import PlaneAPIError, PlaneClient
from plane_cli.config import ROOT, Config, ConfigError, load_config, resolve_llm
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

app = Flask(__name__)
app.secret_key = "plane-automation-web"


ENV_KEYS = [
    "PLANE_API_KEY",
    "PLANE_BASE_URL",
    "PLANE_WORKSPACE_SLUG",
    "PLANE_SUPPORT_PROJECT_ID",
    "PLANE_LLM_PROVIDER",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
]

ENV_COMMENTS = {
    "PLANE_API_KEY": "Personal Access Token do Plane (Profile Settings \u2192 Personal Access Tokens)",
    "PLANE_BASE_URL": "Inst\u00e2ncia self-hosted",
    "PLANE_WORKSPACE_SLUG": "Slug do workspace \u2014 s\u00f3 o nome, n\u00e3o a URL.",
    "PLANE_SUPPORT_PROJECT_ID": "UUID do projeto de Suporte (s\u00f3 o UUID, sem /issues/)",
    "PLANE_LLM_PROVIDER": "IA para redigir a demanda t\u00e9cnica. groq (default) ou openai.",
    "GROQ_API_KEY": "Chave da API Groq (se groq \u00e9 o provider)",
    "GROQ_MODEL": "Modelo Groq",
    "OPENAI_API_KEY": "Chave da API OpenAI (se openai \u00e9 o provider)",
    "OPENAI_MODEL": "Modelo OpenAI",
}

DEFAULTS = {
    "PLANE_BASE_URL": "https://plane.promaxima.cloud",
    "PLANE_WORKSPACE_SLUG": "dynamics",
    "PLANE_LLM_PROVIDER": "groq",
    "GROQ_MODEL": "llama-3.3-70b-versatile",
    "OPENAI_MODEL": "gpt-4o-mini",
}


def _find_env_path() -> Path:
    for candidate in (Path.cwd() / ".env", ROOT / ".env", ROOT.parent / ".env"):
        if candidate.is_file():
            return candidate
    return ROOT / ".env"


def _read_env() -> dict[str, str]:
    path = _find_env_path()
    if not path.exists():
        return {k: DEFAULTS.get(k, "") for k in ENV_KEYS}
    current = dotenv_values(path)
    return {k: str(current.get(k, DEFAULTS.get(k, ""))) for k in ENV_KEYS}


def _write_env(data: dict[str, str]) -> None:
    path = _find_env_path()
    lines: list[str] = []
    written: set[str] = set()
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("#") or not stripped:
                lines.append(raw_line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key in ENV_KEYS:
                value = data.get(key, "")
                lines.append(f"{key}={value}")
                written.add(key)
            else:
                lines.append(raw_line)
    for key in ENV_KEYS:
        if key not in written:
            if key in ENV_COMMENTS:
                lines.append(f"# {ENV_COMMENTS[key]}")
            lines.append(f"{key}={data.get(key, DEFAULTS.get(key, ''))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_config(**kwargs: Any) -> Config:
    return load_config(**kwargs)


def get_client(cfg: Config) -> PlaneClient:
    return PlaneClient(cfg.base_url, cfg.api_key, cfg.workspace_slug)


def error_response(message: str, status: int = 400) -> tuple[dict, int]:
    return jsonify({"error": message}), status


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/intake")
def intake_page():
    return render_template("intake.html")


@app.route("/suporte")
def suporte_page():
    return render_template("suporte.html")


@app.route("/tecnica")
def tecnica_page():
    return render_template("tecnica.html")


@app.route("/projetos")
def projetos_page():
    return render_template("projetos.html")


@app.route("/configuracoes")
def settings_page():
    return render_template("configuracoes.html")


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(_read_env())


@app.route("/api/settings", methods=["POST"])
def api_settings_save():
    data = request.get_json(silent=True) or {}
    current = _read_env()
    for key in ENV_KEYS:
        if key in data:
            current[key] = str(data[key]).strip()
    _write_env(current)
    return jsonify({"ok": True, "message": "Configuracoes salvas. Reinicie o servidor para aplicar."})


@app.route("/api/settings/test-plane", methods=["POST"])
def api_test_plane():
    data = request.get_json(silent=True) or {}
    api_key = data.get("PLANE_API_KEY", "").strip()
    base_url = data.get("PLANE_BASE_URL", "").strip().rstrip("/")
    workspace = data.get("PLANE_WORKSPACE_SLUG", "").strip()
    if not api_key or not base_url or not workspace:
        return error_response("Preencha PLANE_API_KEY, PLANE_BASE_URL e PLANE_WORKSPACE_SLUG.")
    try:
        client = PlaneClient(base_url, api_key, workspace)
        user = client.me()
        client.close()
        name = user.get("display_name") or user.get("email") or user.get("id") or "OK"
        return jsonify({"ok": True, "user": name})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/settings/test-llm", methods=["POST"])
def api_test_llm():
    import httpx as _httpx
    data = request.get_json(silent=True) or {}
    provider = data.get("PLANE_LLM_PROVIDER", "groq").strip().lower()
    if provider == "groq":
        api_key = data.get("GROQ_API_KEY", "").strip()
        base_url = "https://api.groq.com/openai/v1"
        model = data.get("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
    else:
        api_key = data.get("OPENAI_API_KEY", "").strip()
        base_url = "https://api.openai.com/v1"
        model = data.get("OPENAI_MODEL", "gpt-4o-mini").strip()
    if not api_key:
        return error_response(f"Chave da API ({provider.upper()}) nao preenchida.")
    try:
        resp = _httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "temperature": 0.1, "messages": [{"role": "user", "content": "Responda apenas: OK"}]},
            timeout=15.0,
        )
        if resp.status_code >= 400:
            return jsonify({"ok": False, "error": f"{resp.status_code}: {resp.text[:300]}"}), 400
        return jsonify({"ok": True, "model": model})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/projects")
def api_projects():
    try:
        cfg = get_config()
        with get_client(cfg) as client:
            projects = client.list_projects()
        return jsonify(projects)
    except (ConfigError, PlaneAPIError) as e:
        return error_response(str(e))


@app.route("/api/labels")
def api_labels():
    project_id = request.args.get("project_id")
    try:
        cfg = get_config(require_support_project=not project_id)
        target = project_id or cfg.support_project_id
        with get_client(cfg) as client:
            labels = client.list_labels(target)
        return jsonify(labels)
    except (ConfigError, PlaneAPIError) as e:
        return error_response(str(e))


@app.route("/api/states")
def api_states():
    project_id = request.args.get("project_id")
    try:
        cfg = get_config(require_support_project=not project_id)
        target = project_id or cfg.support_project_id
        with get_client(cfg) as client:
            states = client.list_states(target)
        return jsonify(states)
    except (ConfigError, PlaneAPIError) as e:
        return error_response(str(e))


@app.route("/api/me")
def api_me():
    try:
        cfg = get_config()
        with get_client(cfg) as client:
            user = client.me()
        return jsonify(user)
    except (ConfigError, PlaneAPIError) as e:
        return error_response(str(e))


@app.route("/api/intake", methods=["POST"])
def api_create_intake():
    data = request.get_json(silent=True) or {}
    description = data.get("description", "").strip()
    if not description:
        return error_response("Descricao e obrigatoria.")

    try:
        cfg = get_config(require_support_project=True)
        llm_settings = resolve_llm(cfg)
    except ConfigError as e:
        return error_response(str(e))

    title = data.get("title") or None
    priority = data.get("priority", "none")
    labels = data.get("labels", [])
    necessidade = data.get("necessidade") or None
    cenario = data.get("cenario") or None
    resultado = data.get("resultado") or None
    solicitante_nome = data.get("solicitante_nome") or None
    organizacao = data.get("organizacao") or None
    canal = data.get("canal") or None

    try:
        with get_client(cfg) as client:
            project = client.get_project(cfg.support_project_id)
            project_labels = client.list_labels(cfg.support_project_id)

            from plane_cli.cli import resolve_label_ids

            label_ids, _ = resolve_label_ids(labels, project_labels) if labels else ([], [])
            waiting_ids, _ = resolve_label_ids(
                ("aguardando interno",), project_labels, strict=False
            )
            for lid in waiting_ids:
                if lid not in label_ids:
                    label_ids.append(lid)

            current_user = client.me()
            responsavel = client.user_display_name(current_user)

            draft = draft_support_demand(
                relato=description,
                titulo=title,
                labels=labels,
                settings=llm_settings,
            )
            if necessidade:
                draft["necessidade"] = necessidade
            if cenario:
                draft["cenario_atual"] = cenario
            if resultado:
                draft["resultado_esperado"] = resultado
            if solicitante_nome:
                draft["solicitante_nome"] = solicitante_nome
            if organizacao:
                draft["organizacao"] = organizacao
            if canal:
                draft["canal"] = canal

            name = sanitize_title(title) or sanitize_title(draft.get("titulo"))
            if not name:
                return error_response("Nao foi possivel definir o titulo.")
            draft["titulo"] = name

            item = client.create_intake(
                cfg.support_project_id,
                name=name,
                description_html=support_demand_html(draft=draft, responsavel=responsavel),
                priority=priority.lower(),
                labels=label_ids or None,
            )
            result = client.summarize(cfg.support_project_id, item, project)
            return jsonify(result)
    except (PlaneAPIError, LlmError) as e:
        return error_response(str(e))


@app.route("/api/suporte", methods=["POST"])
def api_create_suporte():
    data = request.get_json(silent=True) or {}
    description = data.get("description", "").strip()
    if not description:
        return error_response("Descricao e obrigatoria.")

    try:
        cfg = get_config(require_support_project=True)
        llm_settings = resolve_llm(cfg)
    except ConfigError as e:
        return error_response(str(e))

    title = data.get("title") or None
    priority = data.get("priority", "none")
    labels = data.get("labels", [])
    necessidade = data.get("necessidade") or None
    cenario = data.get("cenario") or None
    resultado = data.get("resultado") or None
    solicitante_nome = data.get("solicitante_nome") or None
    organizacao = data.get("organizacao") or None
    canal = data.get("canal") or None

    try:
        with get_client(cfg) as client:
            project = client.get_project(cfg.support_project_id)
            project_labels = client.list_labels(cfg.support_project_id)

            from plane_cli.cli import resolve_label_ids

            label_ids, _ = resolve_label_ids(labels, project_labels) if labels else ([], [])

            current_user = client.me()
            creator_id = str(current_user.get("id") or "")
            responsavel = client.user_display_name(current_user)

            draft = draft_support_demand(
                relato=description,
                titulo=title,
                labels=labels,
                settings=llm_settings,
            )
            if necessidade:
                draft["necessidade"] = necessidade
            if cenario:
                draft["cenario_atual"] = cenario
            if resultado:
                draft["resultado_esperado"] = resultado
            if solicitante_nome:
                draft["solicitante_nome"] = solicitante_nome
            if organizacao:
                draft["organizacao"] = organizacao
            if canal:
                draft["canal"] = canal

            name = sanitize_title(title) or sanitize_title(draft.get("titulo"))
            if not name:
                return error_response("Nao foi possivel definir o titulo.")
            draft["titulo"] = name

            item = client.create_work_item(
                cfg.support_project_id,
                name=name,
                description_html=support_demand_html(draft=draft, responsavel=responsavel),
                priority=priority.lower(),
                labels=label_ids or None,
                created_by=creator_id or None,
                assignees=[creator_id] if creator_id else None,
            )
            result = client.summarize(cfg.support_project_id, item, project)
            return jsonify(result)
    except (PlaneAPIError, LlmError) as e:
        return error_response(str(e))


@app.route("/api/tecnica", methods=["POST"])
def api_create_tecnica():
    data = request.get_json(silent=True) or {}
    from_id = data.get("from_id", "").strip()
    if not from_id:
        return error_response("ID da demanda de suporte e obrigatorio.")

    try:
        cfg = get_config(require_support_project=True)
    except ConfigError as e:
        return error_response(str(e))

    project_id = data.get("project_id") or None
    title = data.get("title") or None
    description = data.get("description") or None
    solucao = data.get("solucao") or None
    priority = data.get("priority") or None
    trabalho = data.get("trabalho") or None
    trabalho_title = data.get("trabalho_title") or None

    try:
        mapping = None if project_id else load_projects_map(cfg.projects_yaml)
    except MappingError as e:
        return error_response(str(e))

    try:
        with get_client(cfg) as client:
            support_project = client.get_project(cfg.support_project_id)
            support_item = client.retrieve_work_item(cfg.support_project_id, from_id)
            support_labels = client.list_labels(cfg.support_project_id)
            label_names = client.label_names(support_item, support_labels)

            try:
                tech_project_id, matched_label = resolve_tech_project(
                    label_names, mapping or {}, override_project_id=project_id
                )
            except MappingError as e:
                return error_response(str(e))

            tech_project = client.get_project(tech_project_id)
            support_title = sanitize_title(str(support_item.get("name") or ""))

            origem_key = client.issue_key(support_item, support_project)
            origem_url = client.work_item_url(cfg.support_project_id, support_item, support_project)
            current_user = client.me()
            creator_id = str(current_user.get("id") or "")
            responsavel = client.user_display_name(current_user)

            try:
                llm_settings = resolve_llm(cfg)
            except ConfigError as e:
                return error_response(str(e))

            facts = extract_support_facts(support_item, origem_key=origem_key, labels=label_names)
            draft = draft_technical_demand(facts, llm_settings)

            if description:
                draft["problema"] = description
            if solucao:
                draft["solucao"] = solucao

            tech_name = sanitize_title(title) or sanitize_title(draft.get("titulo")) or support_title
            if not tech_name:
                return error_response("Nao foi possivel definir o titulo da demanda tecnica.")
            draft["titulo"] = tech_name

            tech_html = technical_demand_html(
                origem_key=origem_key,
                origem_url=origem_url,
                relacao=RELATION_IMPLEMENTS,
                draft=draft,
                responsavel=responsavel,
            )

            tech_priority = (priority or support_item.get("priority") or "none").lower()
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

            result = {
                "support": client.summarize(cfg.support_project_id, support_item, support_project),
                "tecnica": client.summarize(tech_project_id, tech_item, tech_project),
                "label": matched_label,
                "relation": {"type": relation.get("type")},
                "url": client.work_item_url(tech_project_id, tech_item, tech_project),
            }

            try:
                work_draft = draft_work_item(
                    draft,
                    llm_settings,
                    titulo=tech_name,
                    labels=label_names,
                    orientacao=trabalho,
                )
                child_title = (
                    sanitize_title(trabalho_title)
                    or sanitize_title(work_draft.get("titulo"))
                    or f"Implementar: {tech_name}"
                )
                work_draft["titulo"] = child_title
                trabalho_html_body = work_item_html(
                    draft=work_draft,
                    responsavel=responsavel,
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
                result["trabalho"] = client.summarize(tech_project_id, trabalho_item, tech_project)
            except (LlmError, PlaneAPIError) as exc:
                result["trabalho"] = None
                result["error"] = (
                    "Demanda tecnica criada, mas o sub-item de trabalho falhou. "
                    f"Preencha manualmente no Plane. {exc}"
                )

            return jsonify(result)
    except PlaneAPIError as e:
        return error_response(str(e))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
