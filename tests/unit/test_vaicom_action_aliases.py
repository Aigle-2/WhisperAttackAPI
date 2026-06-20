"""Tests for the local VAICOM keywords.html action-alias adapter."""

from __future__ import annotations

from vaivox.infrastructure.vocabulary.vaicom_action_aliases import (
    VaicomActionAliasCatalog,
    parse_action_aliases,
)


def _html(alias: str = "Request Engine Start") -> str:
    return f"""
    <table><tbody>
      <tr><td class="action">Action Request Engine Start</td>
          <td class="group">Dynamic Commands</td>
          <td class="aliases"><span class="alias-item">Engine Start</span>
          <span class="alias-item">{alias}</span></td></tr>
      <tr><td class="action">Action DREAM 7</td><td class="group">Dynamic Commands</td>
          <td class="aliases"><span class="alias-item">Request I F R Dream Seven</span></td></tr>
    </tbody></table>
    """


def test_parser_maps_exact_actions_to_ordered_aliases() -> None:
    aliases = parse_action_aliases(_html())

    assert aliases["action request engine start"] == (
        "Engine Start",
        "Request Engine Start",
    )
    assert aliases["action dream 7"] == ("Request I F R Dream Seven",)


def test_catalog_discovers_and_reloads_keywords_html(tmp_path) -> None:
    export = tmp_path / "Export"
    export.mkdir()
    path = export / "keywords.html"
    path.write_text(_html(), encoding="utf-8")
    catalog = VaicomActionAliasCatalog(discover=lambda: tmp_path)

    assert "Request Engine Start" in catalog.load()["action request engine start"]

    path.write_text(_html("Request To Start Engines"), encoding="utf-8")

    assert "Request To Start Engines" in catalog.load()["action request engine start"]


def test_catalog_degrades_to_empty_when_export_is_missing(tmp_path) -> None:
    catalog = VaicomActionAliasCatalog(discover=lambda: tmp_path)

    assert catalog.load() == {}
