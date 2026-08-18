from __future__ import annotations

import html
from datetime import date
from typing import Any

from plane_cli.html import (
    as_html,
    html_to_plain,
    is_placeholder,
    parse_h2_sections,
    section_html,
)

RELATION_IMPLEMENTS = "implements"


def _h2(title: str) -> str:
    return f"<h2>{html.escape(title)}</h2>"


def _h3(title: str) -> str:
    return f"<h3>{html.escape(title)}</h3>"


def _ul(items: list[str]) -> str:
    lis = "".join(f"<li>{item}</li>" for item in items)
    return f"<ul>{lis}</ul>"


def _li_text(label: str, value: str = "") -> str:
    if value:
        return f"{html.escape(label)} {html.escape(value)}"
    return html.escape(label)


def _placeholder(text: str) -> str:
    return f"<p>{html.escape(text)}</p>"


def _body(value: str | None, fallback: str) -> str:
    rendered = as_html(value)
    return rendered if rendered else _placeholder(fallback)


def _checkboxes(items: list[str]) -> str:
    lis = "".join(f"<li>☐ {html.escape(item)}</li>" for item in items)
    return f"<ul>{lis}</ul>"


def support_demand_html(
    *,
    necessidade: str | None = None,
    data_solicitacao: str | None = None,
    draft: dict[str, Any] | None = None,
    responsavel: str | None = None,
) -> str:
    data = data_solicitacao or date.today().isoformat()
    payload = draft or {}
    impacto = payload.get("impacto") if isinstance(payload.get("impacto"), dict) else {}
    atendimento = payload.get("atendimento") if isinstance(payload.get("atendimento"), dict) else {}
    evidencias = payload.get("evidencias") if isinstance(payload.get("evidencias"), dict) else {}
    necessidade_text = str(payload.get("necessidade") or necessidade or "").strip()
    return "".join(
        [
            _h2("Solicitante"),
            _ul(
                [
                    _li_text("Nome:", str(payload.get("solicitante_nome") or "")),
                    _li_text("Organização/área:", str(payload.get("organizacao") or "")),
                    _li_text("Canal de entrada:", str(payload.get("canal") or "")),
                    _li_text("Data da solicitação:", data),
                ]
            ),
            _h2("Necessidade"),
            _body(
                necessidade_text,
                "Descrever o problema ou resultado esperado na perspectiva do solicitante.",
            ),
            _h2("Cenário atual"),
            _body(
                str(payload.get("cenario_atual") or ""),
                "Descrever o que acontece atualmente.",
            ),
            _h2("Resultado esperado"),
            _body(
                str(payload.get("resultado_esperado") or ""),
                "Descrever o comportamento esperado sem definir prematuramente a solução técnica.",
            ),
            _h2("Impacto"),
            _ul(
                [
                    _li_text("Pessoas ou clientes afetados:", str(impacto.get("pessoas") or "")),
                    _li_text("Processo afetado:", str(impacto.get("processo") or "")),
                    _li_text("Existe contorno:", str(impacto.get("contorno") or "")),
                    _li_text("Frequência:", str(impacto.get("frequencia") or "")),
                    _li_text("Consequência:", str(impacto.get("consequencia") or "")),
                ]
            ),
            _h2("Evidências"),
            _ul(
                [
                    _li_text("Links:", str(evidencias.get("links") or "")),
                    _li_text("Screenshots:", str(evidencias.get("screenshots") or "")),
                    _li_text("Vídeos:", str(evidencias.get("videos") or "")),
                    _li_text("Logs:", str(evidencias.get("logs") or "")),
                    _li_text("Documentos:", str(evidencias.get("documentos") or "")),
                ]
            ),
            _h2("Contexto adicional"),
            _body(
                str(payload.get("contexto_adicional") or ""),
                "Informações necessárias para reprodução, análise ou decisão.",
            ),
            _h2("Atendimento"),
            _ul(
                [
                    _li_text("Responsável pela comunicação:", responsavel or ""),
                    _li_text("SLA:", str(atendimento.get("sla") or "")),
                    _li_text("Prazo solicitado:", str(atendimento.get("prazo") or "")),
                    _li_text("Próxima atualização:"),
                ]
            ),
        ]
    )


def extract_support_facts(
    support_item: dict[str, Any],
    *,
    origem_key: str,
    labels: list[str] | None = None,
) -> dict[str, str]:
    """Extrai fatos em texto para o LLM. Não usar como texto da demanda técnica."""
    html_src = str(support_item.get("description_html") or "")
    sections = parse_h2_sections(html_src)
    stripped = str(support_item.get("description_stripped") or "").strip()
    if not stripped:
        stripped = html_to_plain(html_src)

    def plain_section(*names: str) -> str:
        content = section_html(sections, *names)
        text = html_to_plain(content) if content else ""
        return "" if is_placeholder(text) else text

    facts = {
        "chave": origem_key,
        "titulo": str(support_item.get("name") or "").strip(),
        "prioridade": str(support_item.get("priority") or "none"),
        "labels": ", ".join(labels or []),
        "necessidade": plain_section("necessidade"),
        "cenario_atual": plain_section("cenário atual", "cenario atual"),
        "resultado_esperado": plain_section("resultado esperado"),
        "impacto": plain_section("impacto"),
        "evidencias": plain_section("evidências", "evidencias"),
        "contexto_adicional": plain_section("contexto adicional"),
        "atendimento": plain_section("atendimento"),
        "texto_integral": "" if is_placeholder(stripped) else stripped,
    }
    return {key: value for key, value in facts.items() if value}


def technical_demand_html(
    *,
    origem_key: str,
    origem_url: str | None = None,
    relacao: str = RELATION_IMPLEMENTS,
    draft: dict[str, Any] | None = None,
    responsavel: str | None = None,
) -> str:
    data = draft or {}
    if origem_url:
        origem_item = f'<a href="{html.escape(origem_url, quote=True)}">{html.escape(origem_key)}</a>'
    else:
        origem_item = html.escape(origem_key)

    aceite = data.get("criterios") if isinstance(data.get("criterios"), list) else []
    aceite = [str(item) for item in aceite if str(item).strip()]
    if not aceite:
        aceite = [
            "Comportamento técnico descrito no problema atendido",
            "Testes automatizados criados ou atualizados",
            "Homologação concluída",
            "Ausência de regressão conhecida",
            "Evidências anexadas",
        ]

    incluido = data.get("escopo_incluido") if isinstance(data.get("escopo_incluido"), list) else []
    incluido_items = [html.escape(str(item)) for item in incluido if str(item).strip()]
    nao_incluido = data.get("escopo_nao_incluido") if isinstance(data.get("escopo_nao_incluido"), list) else []
    nao_incluido_items = [html.escape(str(item)) for item in nao_incluido if str(item).strip()]
    if not nao_incluido_items:
        nao_incluido_items = [html.escape(f"Itens não descritos em {origem_key}")]

    return "".join(
        [
            _h2("Demanda de origem"),
            _ul(
                [
                    origem_item,
                    _li_text("Relação:", relacao),
                ]
            ),
            _h2("Problema técnico"),
            _body(data.get("problema"), "Explicar a causa conhecida ou o comportamento que precisa ser alterado."),
            _h2("Solução proposta"),
            _body(data.get("solucao"), "Descrever a abordagem técnica aprovada."),
            _h2("Critérios de aceite"),
            _checkboxes(aceite),
            _h2("Escopo"),
            _h3("Incluído"),
            _ul(incluido_items) if incluido_items else _ul([html.escape(f"Atender a demanda de origem {origem_key}")]),
            _h3("Não incluído"),
            _ul(nao_incluido_items),
            _h2("Dependências e riscos"),
            _ul(
                [
                    _li_text("Dependências:", str(data.get("dependencias") or "a identificar na implementação")),
                    _li_text("Riscos:", str(data.get("riscos") or "a avaliar na implementação")),
                    _li_text("Bloqueios:", str(data.get("bloqueios") or "nenhum informado")),
                    _li_text("Plano de rollback:", str(data.get("rollback") or "reverter o deploy da mudança")),
                ]
            ),
            _h2("Validação"),
            _ul(
                [
                    _li_text("Ambiente:", str(data.get("ambiente") or "homologação, depois produção")),
                    _li_text("Responsável:", responsavel or ""),
                    _li_text("Como testar:", str(data.get("como_testar") or "Validar o comportamento descrito no problema técnico")),
                    _li_text("Dados necessários:", str(data.get("dados_necessarios") or "dados de homologação do fluxo afetado")),
                ]
            ),
            _h2("Evidências da entrega"),
            _ul(
                [
                    _li_text("PR:"),
                    _li_text("Pipeline:"),
                    _li_text("Deploy:"),
                    _li_text("Logs/dashboard:"),
                    _li_text("Homologação:"),
                    _li_text("Validação em produção:"),
                ]
            ),
        ]
    )


def work_item_html(
    *,
    draft: dict[str, Any] | None = None,
    responsavel: str | None = None,
    prioridade: str | None = None,
) -> str:
    data = draft or {}
    tarefas = data.get("tarefas") if isinstance(data.get("tarefas"), list) else []
    tarefa_items = [html.escape(str(item)) for item in tarefas if str(item).strip()]
    if not tarefa_items:
        tarefa_items = [html.escape("Detalhar as alterações de código na implementação.")]

    criterios = data.get("criterios_conclusao") if isinstance(data.get("criterios_conclusao"), list) else []
    criterios = [str(item) for item in criterios if str(item).strip()]
    if not criterios:
        criterios = ["Evidências da execução estão vinculadas ao item técnico."]

    prio = str(data.get("prioridade") or prioridade or "a definir").strip() or "a definir"

    return "".join(
        [
            _h2("Objetivo"),
            _body(
                data.get("objetivo"),
                "Implementar as alterações necessárias descritas na demanda técnica.",
            ),
            _h2("Trabalho"),
            _ul(tarefa_items),
            _h2("Critérios de conclusão"),
            _checkboxes(criterios),
            _h2("Evidências"),
            _ul(
                [
                    _li_text("Commit:"),
                    _li_text("PR:"),
                    _li_text("Execução dos testes:"),
                    _li_text("Pipeline:"),
                    _li_text("Resultado da validação:"),
                ]
            ),
            _h2("Planejamento"),
            _ul(
                [
                    _li_text("Responsável:", responsavel or "a definir"),
                    _li_text("Prioridade:", prio),
                    _li_text("Estimativa:", "a definir"),
                    _li_text("Data de início:", "a definir"),
                    _li_text("Data-alvo:", "a definir"),
                ]
            ),
        ]
    )
