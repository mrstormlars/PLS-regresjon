"""Guards that every DOM id referenced from frontend/app.js exists in
frontend/index.html, so a redesign of the HTML shell can never silently
orphan a JS event listener or Plotly.newPlot target."""

import re
from pathlib import Path

FRONTEND = Path(__file__).parent.parent / "frontend"

_ID_REFERENCE_PATTERN = re.compile(
    r'(?:el|document\.getElementById|Plotly\.newPlot)\(\s*"([^"]+)"'
)
_ID_DEFINITION_PATTERN = re.compile(r'id="([^"]+)"')


def referenced_ids(app_js: str) -> set[str]:
    return set(_ID_REFERENCE_PATTERN.findall(app_js))


def defined_ids(html: str, app_js: str = "") -> set[str]:
    # Some rows (e.g. the simulation table's Y row) are built via innerHTML
    # in app.js itself rather than present in index.html, so both sources
    # count as "defined".
    return set(_ID_DEFINITION_PATTERN.findall(html)) | set(
        _ID_DEFINITION_PATTERN.findall(app_js)
    )


def missing_ids(app_js: str, html: str) -> set[str]:
    """Ids referenced from app.js that have no matching id="..." in html
    or in an app.js innerHTML template."""
    return referenced_ids(app_js) - defined_ids(html, app_js)


def test_all_referenced_ids_exist_in_index_html():
    app_js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    assert missing_ids(app_js, html) == set()


def test_extractor_finds_at_least_30_ids():
    app_js = (FRONTEND / "app.js").read_text(encoding="utf-8")
    assert len(referenced_ids(app_js)) >= 30


def test_missing_ids_detects_a_synthetic_gap():
    app_js = 'el("known-id"); el("orphaned-id");'
    html = '<div id="known-id"></div>'
    assert missing_ids(app_js, html) == {"orphaned-id"}
