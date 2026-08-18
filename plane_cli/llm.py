from __future__ import annotations

import json
import re
from typing import Any

import httpx

from plane_cli.config import LlmSettings

SYSTEM_PROMPT = """Você é um engenheiro de software sênior redigindo uma demanda técnica no Plane.

Recebe fatos de uma demanda de SUPORTE (perspectiva do solicitante) e escreve a demanda TÉCNICA (perspectiva de engenharia).

Regras:
- Escreva em português, tom técnico, objetivo.
- NÃO copie frases, parágrafos ou títulos da demanda de suporte. Reformule e interprete.
- NÃO invente PRs, pipelines, deploys, logs ou evidências de entrega.
- NÃO deixe seções vazias: se faltar informação, declare a hipótese técnica e o que precisa ser confirmado.
- titulo: título curto da demanda técnica (até ~90 caracteres), baseado no título do suporte, em linguagem de engenharia. NÃO copie o título do suporte. NÃO use [CLIENTE], [cliente] nem o nome do cliente no título.
- problema: causa ou comportamento a alterar no sistema (não o relato do usuário).
- solucao: abordagem técnica proposta (componentes, fluxo, restrições), não o "resultado esperado" do solicitante.
- criterios: critérios testáveis de aceite (além dos padrão de QA).
- escopo_incluido / escopo_nao_incluido: listas curtas do que entra e do que fica de fora.
- dependencias, riscos, bloqueios, rollback: texto curto.
- ambiente, como_testar, dados_necessarios: como validar tecnicamente.

Responda SOMENTE um JSON válido, sem markdown, com as chaves:
titulo, problema, solucao, criterios (array de strings), escopo_incluido (array), escopo_nao_incluido (array),
dependencias, riscos, bloqueios, rollback, ambiente, como_testar, dados_necessarios.
"""


class LlmError(RuntimeError):
    pass


def sanitize_title(value: str | None) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\[cliente\]", "", text, flags=re.I)
    text = re.sub(r"\s{2,}", " ", text).strip(" \t-–—|")
    return text


def _parse_json_payload(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.I)
    if fenced:
        text = fenced.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise LlmError(f"A IA não retornou JSON válido: {exc}") from exc
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise LlmError("A IA retornou JSON que não é um objeto.")
    return data


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def normalize_draft(data: dict[str, Any]) -> dict[str, Any]:
    required_qa = [
        "Testes automatizados criados ou atualizados",
        "Homologação concluída",
        "Ausência de regressão conhecida",
        "Evidências anexadas",
    ]
    criterios = _as_list(data.get("criterios"))
    existing_lower = {item.lower() for item in criterios}
    for item in required_qa:
        if item.lower() not in existing_lower:
            criterios.append(item)
    return {
        "titulo": sanitize_title(data.get("titulo")),
        "problema": str(data.get("problema") or "").strip(),
        "solucao": str(data.get("solucao") or "").strip(),
        "criterios": criterios,
        "escopo_incluido": _as_list(data.get("escopo_incluido")),
        "escopo_nao_incluido": _as_list(data.get("escopo_nao_incluido")),
        "dependencias": str(data.get("dependencias") or "").strip(),
        "riscos": str(data.get("riscos") or "").strip(),
        "bloqueios": str(data.get("bloqueios") or "").strip(),
        "rollback": str(data.get("rollback") or "").strip(),
        "ambiente": str(data.get("ambiente") or "").strip(),
        "como_testar": str(data.get("como_testar") or "").strip(),
        "dados_necessarios": str(data.get("dados_necessarios") or "").strip(),
    }


WORK_SYSTEM_PROMPT = """Você é um engenheiro de software sênior quebrando uma demanda TÉCNICA em um sub-item de Trabalho executável no Plane.

Recebe o rascunho da demanda técnica (perspectiva de engenharia) e escreve o PLANO DE IMPLEMENTAÇÃO (o que fazer no código).

Regras:
- Escreva em português, tom de execução, objetivo.
- NÃO copie frases, parágrafos ou títulos da demanda técnica. Transforme em tarefas.
- NÃO invente commits, PRs, pipelines, deploys ou resultados de validação.
- titulo: título curto do sub-item de implementação, baseado no título técnico, em geral com verbo (Implementar, Ajustar, Corrigir). NÃO repita o título técnico. NÃO use [CLIENTE].
- objetivo: o que a implementação deve permitir no sistema (resultado da mudança, não o problema).
- tarefas: lista concreta de trabalho (arquivos, funções, views, testes, fluxos) quando o contexto permitir.
- criterios_conclusao: condições verificáveis de que o trabalho terminou.
- prioridade: urgent, high, medium, low ou none; se não souber, omita.

Responda SOMENTE um JSON válido, sem markdown, com as chaves:
titulo, objetivo, tarefas (array de strings), criterios_conclusao (array de strings), prioridade (string opcional).
"""


def normalize_work_draft(data: dict[str, Any]) -> dict[str, Any]:
    criterios = _as_list(data.get("criterios_conclusao") or data.get("criterios"))
    required = ["Evidências da execução estão vinculadas ao item técnico."]
    existing_lower = {item.lower() for item in criterios}
    for item in required:
        if item.lower() not in existing_lower:
            criterios.append(item)
    prioridade = str(data.get("prioridade") or "").strip().lower()
    if prioridade not in {"urgent", "high", "medium", "low", "none"}:
        prioridade = ""
    return {
        "titulo": sanitize_title(data.get("titulo")),
        "objetivo": str(data.get("objetivo") or "").strip(),
        "tarefas": _as_list(data.get("tarefas")),
        "criterios_conclusao": criterios,
        "prioridade": prioridade,
    }


def _chat_json(settings: LlmSettings, system_prompt: str, user_content: str) -> dict[str, Any]:
    body = {
        "model": settings.model,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }
    url = f"{settings.base_url.rstrip('/')}/chat/completions"
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=60.0,
        )
    except httpx.HTTPError as exc:
        raise LlmError(f"Falha ao chamar {settings.provider}: {exc}") from exc

    if response.status_code >= 400:
        raise LlmError(
            f"LLM {settings.provider} {response.status_code}: {response.text[:500]}"
        )
    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError(f"Resposta inesperada do LLM: {payload}") from exc
    if not isinstance(content, str) or not content.strip():
        raise LlmError("O LLM retornou conteúdo vazio.")
    return _parse_json_payload(content)


def draft_technical_demand(facts: dict[str, str], settings: LlmSettings) -> dict[str, Any]:
    user_payload = json.dumps(facts, ensure_ascii=False, indent=2)
    return normalize_draft(
        _chat_json(
            settings,
            SYSTEM_PROMPT,
            "Fatos da demanda de suporte (use só como insumo; não copie):\n" + user_payload,
        )
    )


def draft_work_item(
    tech_draft: dict[str, Any],
    settings: LlmSettings,
    *,
    titulo: str = "",
    labels: list[str] | None = None,
    orientacao: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "titulo_tecnico": titulo,
        "labels": labels or [],
        "demanda_tecnica": {
            "problema": tech_draft.get("problema"),
            "solucao": tech_draft.get("solucao"),
            "criterios": tech_draft.get("criterios"),
            "escopo_incluido": tech_draft.get("escopo_incluido"),
            "escopo_nao_incluido": tech_draft.get("escopo_nao_incluido"),
            "como_testar": tech_draft.get("como_testar"),
            "dependencias": tech_draft.get("dependencias"),
            "riscos": tech_draft.get("riscos"),
        },
    }
    if orientacao and orientacao.strip():
        payload["orientacao_do_autor"] = orientacao.strip()
    return normalize_work_draft(
        _chat_json(
            settings,
            WORK_SYSTEM_PROMPT,
            "Rascunho da demanda técnica (use só como insumo; não copie):\n"
            + json.dumps(payload, ensure_ascii=False, indent=2),
        )
    )
