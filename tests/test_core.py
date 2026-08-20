from plane_cli.client import identifier_lookup_keys, identifiers_compatible, parse_issue_key
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
