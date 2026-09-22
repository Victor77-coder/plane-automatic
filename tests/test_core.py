import httpx

from plane_cli.client import (
    PlaneAPIError,
    PlaneClient,
    deduplicate_project_items,
    description_excerpt,
    identifier_lookup_keys,
    identifiers_compatible,
    normalize_search_text,
    parse_issue_key,
    plain_text,
    work_item_matches,
)
from plane_cli.html import as_html
from plane_cli.llm import sanitize_title
from plane_cli.mapping import MappingError, resolve_tech_project


def test_as_html_escapes_tags() -> None:
    rendered = as_html('alerta <script>alert(1)</script> fim')
    assert rendered is not None
    assert "<script>" not in rendered
    assert "alert(1)" in rendered


def test_as_html_plain() -> None:
    rendered = as_html("Linha um.\n\nLinha dois.")
    assert rendered == "<p>Linha um.</p><p>Linha dois.</p>"


def test_sanitize_title_strips_cliente() -> None:
    assert sanitize_title("[CLIENTE] Timeout no CPE") == "Timeout no CPE"


def test_parse_issue_key() -> None:
    assert parse_issue_key("SUPORTE-442") == ("SUPORTE", 442)
    assert parse_issue_key("SUP-442") == ("SUP", 442)


def test_identifier_lookup_keys() -> None:
    assert identifier_lookup_keys("SUP", "SUPORTE", 442) == ["SUPORTE-442", "SUP-442"]
    assert identifier_lookup_keys("SUPORTE", "SUPORTE", 1) == ["SUPORTE-1"]


def test_identifiers_compatible() -> None:
    assert identifiers_compatible("SUPORTE", "SUPORTE")
    assert identifiers_compatible("SUP", "SUPORTE")
    assert identifiers_compatible("suporte", "SUP")
    assert not identifiers_compatible("FOO", "SUPORTE")
    assert not identifiers_compatible("S", "SUPORTE")


def test_plain_text_and_search_normalization() -> None:
    assert plain_text("<p>Cotação &amp; preços</p>") == "Cotação & preços"
    assert normalize_search_text("COTAÇÃO") == "cotacao"


def test_work_item_matches_title_or_description_part() -> None:
    item = {
        "name": "Falha na importação",
        "description_html": "<p>O cliente recebeu timeout ao enviar a cotação.</p>",
    }
    assert work_item_matches(item, "falha na importa")
    assert work_item_matches(item, "TIMEOUT ao enviar")
    assert work_item_matches(item, "cotacao")
    assert not work_item_matches(item, "relatorio financeiro")


def test_description_excerpt_removes_html_and_limits_text() -> None:
    item = {"description_html": f"<p>{'a' * 230}</p>"}
    excerpt = description_excerpt(item, limit=20)
    assert excerpt == ("a" * 19) + "…"
    assert "<p>" not in excerpt


def test_deduplicate_project_items() -> None:
    first = {"id": "item-1", "name": "Primeira"}
    duplicate = {"id": "item-1", "name": "Duplicada"}
    entries = deduplicate_project_items(
        [("project-a", first), ("project-a", duplicate), ("project-b", duplicate)]
    )
    assert entries == [("project-a", first), ("project-b", duplicate)]


def test_search_work_items_uses_text_filter(monkeypatch) -> None:
    client = PlaneClient("https://plane.example", "token", "workspace")
    items = [
        {"id": "1", "name": "Timeout na cotação", "description_html": "<p>Erro</p>"},
        {"id": "2", "name": "Outro assunto", "description_html": "<p>Detalhes</p>"},
    ]
    monkeypatch.setattr(client, "_get", lambda *args, **kwargs: {"results": items})
    try:
        assert client.search_work_items("project", "cotacao") == [items[0]]
    finally:
        client.close()


def test_search_work_items_hydrates_description_results(monkeypatch) -> None:
    client = PlaneClient("https://plane.example", "token", "workspace")
    summary = {"id": "1", "name": "Erro de processamento"}
    complete = {**summary, "description_html": "<p>Falha ao importar cotação parcial.</p>"}
    monkeypatch.setattr(client, "_get", lambda *args, **kwargs: {"issues": [summary]})
    monkeypatch.setattr(
        client, "retrieve_work_item", lambda project_id, item_id: complete
    )
    try:
        assert client.search_work_items("project", "cotacao parcial") == [complete]
    finally:
        client.close()


def test_search_work_items_falls_back_when_api_returns_no_matches(monkeypatch) -> None:
    client = PlaneClient("https://plane.example", "token", "workspace")
    target = {
        "id": "target",
        "name": "Melhoria na pesquisa",
        "description_html": "<p>Utilizar o respectivo ID, quando disponível.</p>",
    }
    listed = [
        {"id": str(index), "name": "Outro", "description_html": "<p>Sem relação</p>"}
        for index in range(101)
    ] + [target]
    monkeypatch.setattr(client, "_get", lambda *args, **kwargs: {"issues": []})
    monkeypatch.setattr(client, "_list_work_items", lambda project_id: listed)
    try:
        assert client.search_work_items(
            "project", "respectivo ID, quando disponível.", limit=1
        ) == [target]
    finally:
        client.close()


def test_search_work_items_falls_back_to_project_list(monkeypatch) -> None:
    client = PlaneClient("https://plane.example", "token", "workspace")
    item = {"id": "1", "name": "Erro", "description_html": "<p>Falha parcial</p>"}

    def unavailable(*args, **kwargs):
        raise PlaneAPIError("indisponivel", status_code=404)

    monkeypatch.setattr(client, "_get", unavailable)
    monkeypatch.setattr(client, "_list_work_items", lambda project_id: [item])
    try:
        assert client.search_work_items("project", "parcial") == [item]
    finally:
        client.close()


def test_request_converts_httpx_timeout_to_plane_error(monkeypatch) -> None:
    client = PlaneClient("https://plane.example", "token", "workspace")

    def timeout(*args, **kwargs):
        request = httpx.Request("GET", "https://plane.example/api")
        raise httpx.ReadTimeout("demorou", request=request)

    monkeypatch.setattr(client._http, "request", timeout)
    try:
        try:
            client._get("/api", timeout=1.0)
        except PlaneAPIError as exc:
            assert exc.status_code == 504
            assert "Tempo limite excedido" in str(exc)
        else:
            raise AssertionError("esperava PlaneAPIError")
    finally:
        client.close()


def test_resolve_tech_project() -> None:
    mapping = {"produto:cotacoesgov": "b89eb400-7613-4205-92df-6afe8390523f"}
    project_id, label = resolve_tech_project(
        ["produto:cotacoesgov"],
        mapping,
    )
    assert project_id == "b89eb400-7613-4205-92df-6afe8390523f"
    assert label == "produto:cotacoesgov"


def test_resolve_tech_project_missing() -> None:
    try:
        resolve_tech_project(["produto:plane"], {"produto:cotacoesgov": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"})
    except MappingError:
        return
    raise AssertionError("esperava MappingError")
