from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urljoin

import httpx

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
ISSUE_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-(\d+)$")


def _format_api_error(status_code: int, method: str, path: str, body: Any) -> str:
    detail = ""
    if isinstance(body, dict):
        detail = str(body.get("detail") or body.get("error") or "")
    if status_code in (401, 403) and "not valid" in detail.lower():
        return (
            "Token do Plane rejeitado (PLANE_API_KEY inválido, expirado ou revogado).\n"
            "O valor no .env precisa ser o segredo mostrado uma única vez ao criar o token, "
            "não o ID que aparece na lista.\n"
            "No Plane: Profile Settings → Personal Access Tokens → Add personal access token.\n"
            "Copie o valor completo (geralmente começa com plane_api_) para PLANE_API_KEY e rode de novo."
        )
    return f"Plane API {status_code} em {method} {path}: {body}"


class PlaneAPIError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError, AttributeError):
        return bool(UUID_RE.match(str(value or "")))


def parse_issue_key(value: str) -> tuple[str, int] | None:
    raw = value.strip()
    match = ISSUE_KEY_RE.match(raw)
    if match:
        return match.group(1), int(match.group(2))
    if "-" not in raw:
        return None
    identifier, maybe_seq = raw.rsplit("-", 1)
    if identifier and maybe_seq.isdigit():
        return identifier, int(maybe_seq)
    return None


def _results(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return results
    return []


def extract_issue(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PlaneAPIError("Resposta inesperada da API do Plane.", body=data)
    for key in ("issue_detail", "issue"):
        nested = data.get(key)
        if isinstance(nested, dict) and nested.get("id"):
            return nested
    if data.get("id"):
        return data
    raise PlaneAPIError("A API não retornou o work item criado.", body=data)


class PlaneClient:
    def __init__(self, base_url: str, api_key: str, workspace_slug: str):
        self.base_url = base_url.rstrip("/")
        self.workspace_slug = workspace_slug
        self._item_segment = "work-items"
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> PlaneClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _workspace_path(self, suffix: str) -> str:
        return f"/api/v1/workspaces/{self.workspace_slug}/{suffix.lstrip('/')}"

    def _project_path(self, project_id: str, suffix: str = "") -> str:
        base = f"projects/{project_id}/"
        if suffix:
            base += suffix.lstrip("/")
        return self._workspace_path(base)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = self._http.request(method, path, json=json, params=params)
        if response.status_code >= 400:
            body: Any
            try:
                body = response.json()
            except Exception:
                body = response.text
            raise PlaneAPIError(
                _format_api_error(response.status_code, method, path, body),
                status_code=response.status_code,
                body=body,
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self._request("GET", path, params=params)

    def _post(self, path: str, json: dict[str, Any]) -> Any:
        return self._request("POST", path, json=json)

    def _try_item_paths(self, method: str, project_id: str, rest: str, **kwargs: Any) -> Any:
        """Tenta /work-items/ e, em 404, /issues/ (CE antigo)."""
        segments = [self._item_segment]
        if self._item_segment != "issues":
            segments.append("issues")
        last_error: PlaneAPIError | None = None
        for segment in segments:
            path = self._project_path(project_id, f"{segment}/{rest.lstrip('/')}" if rest else f"{segment}/")
            try:
                data = self._request(method, path, **kwargs)
            except PlaneAPIError as exc:
                if exc.status_code == 404:
                    last_error = exc
                    continue
                raise
            self._item_segment = segment
            return data
        if last_error:
            raise last_error
        raise PlaneAPIError("Falha ao chamar a API de work items.")

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"per_page": 100}
            if cursor:
                params["cursor"] = cursor
            data = self._get(path, params=params)
            if isinstance(data, list):
                return data
            items.extend(_results(data))
            if not isinstance(data, dict) or not data.get("next_page_results"):
                break
            cursor = data.get("next_cursor") or None
            if not cursor:
                break
        return items

    def list_projects(self) -> list[dict[str, Any]]:
        return self._paginate(self._workspace_path("projects/"))

    def get_project(self, project_id: str) -> dict[str, Any]:
        data = self._get(self._project_path(project_id))
        if not isinstance(data, dict):
            raise PlaneAPIError("Projeto inválido na resposta da API.", body=data)
        return data

    def list_states(self, project_id: str) -> list[dict[str, Any]]:
        return self._paginate(self._project_path(project_id, "states/"))

    def list_labels(self, project_id: str) -> list[dict[str, Any]]:
        return self._paginate(self._project_path(project_id, "labels/"))

    def me(self) -> dict[str, Any]:
        data = self._get("/api/v1/users/me/")
        if not isinstance(data, dict):
            raise PlaneAPIError("Não foi possível obter o usuário autenticado.", body=data)
        return data

    def user_display_name(self, user: dict[str, Any] | None) -> str:
        if not user:
            return ""
        full = " ".join(
            part for part in (user.get("first_name"), user.get("last_name")) if part
        ).strip()
        return str(
            user.get("display_name")
            or full
            or user.get("email")
            or user.get("id")
            or ""
        )

    def creator_id(self, item: dict[str, Any]) -> str | None:
        for key in ("created_by_detail", "created_by"):
            value = item.get(key)
            if isinstance(value, dict) and value.get("id"):
                return str(value["id"])
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def retrieve_work_item(self, project_id: str, item_ref: str) -> dict[str, Any]:
        item_ref = item_ref.strip()
        if is_uuid(item_ref):
            try:
                data = self._try_item_paths(
                    "GET",
                    project_id,
                    f"{item_ref}/",
                    params={"expand": "labels,state,assignees"},
                )
            except PlaneAPIError as exc:
                if exc.status_code not in (400, 404):
                    raise
                data = self._try_item_paths("GET", project_id, f"{item_ref}/")
            return extract_issue(data)

        parsed = parse_issue_key(item_ref)
        if not parsed:
            raise PlaneAPIError(
                f"Identificador inválido: {item_ref!r}. Use um UUID ou a chave do chamado (ex.: SUP-123)."
            )
        _identifier, sequence_id = parsed
        for item in self._list_work_items(project_id):
            if int(item.get("sequence_id") or 0) == sequence_id:
                return self.retrieve_work_item(project_id, str(item["id"]))
        raise PlaneAPIError(
            f"Work item {item_ref} não encontrado no projeto {project_id}."
        )

    def _list_work_items(self, project_id: str) -> list[dict[str, Any]]:
        try:
            return self._paginate(self._project_path(project_id, f"{self._item_segment}/"))
        except PlaneAPIError as exc:
            if exc.status_code != 404 or self._item_segment == "issues":
                raise
            self._item_segment = "issues"
            return self._paginate(self._project_path(project_id, "issues/"))

    def create_intake(
        self,
        project_id: str,
        *,
        name: str,
        description_html: str,
        priority: str,
    ) -> dict[str, Any]:
        payload = {
            "issue": {
                "name": name,
                "description_html": description_html,
                "priority": priority,
            }
        }
        data = self._post(self._project_path(project_id, "intake-issues/"), payload)
        return extract_issue(data)

    def create_work_item(
        self,
        project_id: str,
        *,
        name: str,
        description_html: str,
        priority: str,
        parent: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
        created_by: str | None = None,
        assignees: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "description_html": description_html,
            "priority": priority,
        }
        if parent:
            payload["parent"] = parent
        if state:
            payload["state"] = state
        if labels:
            payload["labels"] = labels
        if created_by:
            payload["created_by"] = created_by
        if assignees:
            payload["assignees"] = assignees
        try:
            data = self._try_item_paths("POST", project_id, "", json=payload)
        except PlaneAPIError as exc:
            if assignees and exc.status_code in (400, 403):
                payload.pop("assignees", None)
                data = self._try_item_paths("POST", project_id, "", json=payload)
            else:
                raise
        return extract_issue(data)

    def create_relation(
        self,
        project_id: str,
        work_item_id: str,
        related_id: str,
        *,
        relation_type: str = "relates_to",
    ) -> Any:
        payload = {"relation_type": relation_type, "issues": [related_id]}
        try:
            return self._try_item_paths(
                "POST",
                project_id,
                f"{work_item_id}/relations/",
                json=payload,
            )
        except PlaneAPIError as exc:
            if exc.status_code not in (400, 404):
                raise
            alt = {"relation_type": relation_type, "related_list": [related_id]}
            return self._try_item_paths(
                "POST",
                project_id,
                f"{work_item_id}/relations/",
                json=alt,
            )

    def create_link(
        self,
        project_id: str,
        work_item_id: str,
        *,
        title: str,
        url: str,
    ) -> Any:
        payload = {"title": title, "url": url}
        return self._try_item_paths("POST", project_id, f"{work_item_id}/links/", json=payload)

    def relate_or_link(
        self,
        *,
        tech_project_id: str,
        tech_item: dict[str, Any],
        support_project_id: str,
        support_item: dict[str, Any],
        relation_type: str = "implements",
    ) -> dict[str, Any]:
        tech_id = str(tech_item["id"])
        support_id = str(support_item["id"])
        support_url = self.work_item_url(support_project_id, support_item)
        tech_url = self.work_item_url(tech_project_id, tech_item)
        tried: list[str] = []
        last_error: PlaneAPIError | None = None
        for candidate in (relation_type, "relates_to"):
            if candidate in tried:
                continue
            tried.append(candidate)
            try:
                relation = self.create_relation(
                    tech_project_id,
                    tech_id,
                    support_id,
                    relation_type=candidate,
                )
                return {"type": candidate, "data": relation}
            except PlaneAPIError as exc:
                last_error = exc
                if exc.status_code not in (400, 404):
                    break

        links = []
        try:
            links.append(
                self.create_link(
                    tech_project_id,
                    tech_id,
                    title=f"Demanda de origem ({relation_type})",
                    url=support_url,
                )
            )
            links.append(
                self.create_link(
                    support_project_id,
                    support_id,
                    title="Demanda técnica",
                    url=tech_url,
                )
            )
        except PlaneAPIError as link_exc:
            raise PlaneAPIError(
                f"Não foi possível criar a relação {relation_type} nem o link de fallback. "
                f"Relação: {last_error}. Link: {link_exc}"
            ) from link_exc
        return {
            "type": "link_fallback",
            "requested": relation_type,
            "reason": str(last_error) if last_error else "",
            "data": links,
        }

    def issue_key(self, item: dict[str, Any], project: dict[str, Any] | None = None) -> str:
        identifier = None
        if project:
            identifier = project.get("identifier")
        identifier = identifier or item.get("project_detail", {}).get("identifier")
        sequence = item.get("sequence_id")
        if identifier and sequence is not None:
            return f"{identifier}-{sequence}"
        return str(item.get("id") or "")

    def work_item_url(self, project_id: str, item: dict[str, Any], project: dict[str, Any] | None = None) -> str:
        identifier = None
        if project:
            identifier = project.get("identifier")
        identifier = identifier or item.get("project_detail", {}).get("identifier")
        sequence = item.get("sequence_id")
        if identifier and sequence is not None:
            return urljoin(self.base_url + "/", f"{self.workspace_slug}/browse/{identifier}-{sequence}")
        item_id = item.get("id")
        return urljoin(
            self.base_url + "/",
            f"{self.workspace_slug}/projects/{project_id}/issues/{item_id}",
        )

    def label_names(self, item: dict[str, Any], project_labels: list[dict[str, Any]]) -> list[str]:
        labels = item.get("labels") or item.get("label_details") or []
        by_id = {str(label.get("id")): str(label.get("name") or "") for label in project_labels}
        names: list[str] = []
        for label in labels:
            if isinstance(label, dict):
                name = label.get("name")
                if name:
                    names.append(str(name))
                    continue
                label_id = str(label.get("id") or "")
            else:
                label_id = str(label)
            name = by_id.get(label_id)
            if name:
                names.append(name)
        return names

    def summarize(self, project_id: str, item: dict[str, Any], project: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "id": item.get("id"),
            "name": item.get("name"),
            "sequence_id": item.get("sequence_id"),
            "priority": item.get("priority"),
            "project_id": project_id,
            "url": self.work_item_url(project_id, item, project),
        }
