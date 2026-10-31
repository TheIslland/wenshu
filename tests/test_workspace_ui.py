"""Workspace UI smoke tests: markup, local assets, contract wiring.

No browser is launched; assertions cover the Jinja page and the shipped static
files so a broken script tag / missing module / CDN leak fails CI.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

PANELS = (
    "overview",
    "writing",
    "library",
    "search",
    "style",
    "polish",
    "paragraphs",
    "methods",
    "direction",
    "workflow",
    "delivery",
)

MODULES = (
    "workspace",
    "library",
    "search",
    "style",
    "polish",
    "paragraphs",
    "methods",
    "direction",
    "workflow",
    "delivery",
)

REQUIRED_IDS = (
    "workspace-status",
    "llm-status",
    "save-status",
    "document-list",
    "editor",
    "word-count",
    "conflict-banner",
    "snapshot-list",
    "paragraph-cards",
    "ref-table",
    "ref-search",
    "import-dialog",
    "import-file",
    "pdf-input",
    "zotero-import",
    "search-form",
    "source-chips",
    "source-errors",
    "search-results",
    "style-input",
    "style-report",
    "analyze-document",
    "polish-input",
    "polish-result",
    "paragraph-input",
    "paragraph-result",
    "method-matrix",
    "method-trend",
    "extract-methods",
    "direction-topic",
    "direction-cards",
    "workflow-template",
    "kanban",
    "gate-status",
    "delivery-gate",
    "export-markdown",
    "export-docx",
    "export-bibtex",
    "export-ris",
    "export-style",
    "export-status",
    "citation-style",
    "citation-preview",
    "citation-text",
    "citation-warnings",
    "citation-verify",
    "citation-counts",
    "citation-checks",
    "style-baseline-input",
    "style-baseline-build",
    "style-baseline-clear",
    "style-baseline-status",
    "style-baseline-summary",
)

LOCAL_HOSTS = {"testserver", "127.0.0.1", "localhost", "::1"}
RESOURCE_URL = re.compile(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)


def _project_html(client, project) -> str:
    response = client.get(f"/p/{project['id']}")
    assert response.status_code == 200, response.text
    return response.text


def test_workspace_panels_and_ids(client, project):
    html = _project_html(client, project)
    assert f'data-project-id="{project["id"]}"' in html
    for panel in PANELS:
        assert f'data-panel="{panel}"' in html, f"missing panel {panel}"
    assert html.count('data-tab="') == len(PANELS)
    for element_id in REQUIRED_IDS:
        assert f'id="{element_id}"' in html, f"missing #{element_id}"


def test_workspace_assets_are_local(client, project):
    html = _project_html(client, project)
    assert "/static/css/app.css" in html
    for module in MODULES:
        assert f"/static/js/{module}.js" in html, f"missing script {module}.js"
    for url in RESOURCE_URL.findall(html):
        if url.startswith(("http://", "https://")):
            host = urlparse(url).hostname
            assert host in LOCAL_HOSTS, f"remote resource: {url}"
    lowered = html.lower()
    assert "cdn." not in lowered
    assert "fonts.googleapis" not in lowered
    assert "unpkg.com" not in lowered
    assert 'rel="preconnect"' not in lowered


def test_static_workspace_files(client):
    for module in MODULES:
        response = client.get(f"/static/js/{module}.js")
        assert response.status_code == 200, module
        assert "window.Wenshu" in response.text, module
    app_css = client.get("/static/css/app.css")
    assert app_css.status_code == 200
    css = app_css.text
    assert "@import" not in css
    assert "url(http" not in css
    assert "fonts.googleapis" not in css


def test_scripts_route_requests_through_api_helper(client):
    for module in MODULES:
        body = client.get(f"/static/js/{module}.js").text
        assert "fetch(" not in body, f"{module}.js should use window.api"
        assert "XMLHttpRequest" not in body


def test_writing_autosave_conflict_and_snapshot_wiring(client):
    body = client.get("/static/js/workspace.js").text
    assert "1500" in body  # 1.5s autosave debounce
    assert "409" in body
    assert "/api/documents/" in body
    assert "snapshots" in body
    assert "conflict-banner" in body
    assert "applyRevision" in body


def test_style_and_rewrite_diff_ui_wiring(client):
    style = client.get("/static/js/style.js").text
    for marker in (
        "/api/style/analyze",
        "/api/style/fix",
        "/api/style/rewrite",
        "evidence-preview",
        "style-fix-result",
        "style-rewrite-result",
        "findings",
    ):
        assert marker in style, marker
    polish = client.get("/static/js/polish.js").text
    paragraphs = client.get("/static/js/paragraphs.js").text
    assert "/api/polish" in polish
    assert "gaps" in client.get("/static/js/workspace.js").text
    assert "/api/paragraphs/transform" in paragraphs
    assert "max_delta" in paragraphs


def test_library_search_methods_direction_workflow_wiring(client):
    library = client.get("/static/js/library.js").text
    assert "/api/refs/import" in library
    assert "/api/refs/import/file" in library
    assert "/attach" in library
    assert "/api/zotero/status" in library
    assert "/api/zotero/import" in library

    search = client.get("/static/js/search.js").text
    assert "/api/search" in search
    assert "kind: \"hits\"" in search
    assert "source-errors" in search

    methods = client.get("/static/js/methods.js").text
    assert "/api/methods/matrix" in methods
    assert "/api/methods/extract" in methods
    assert "/api/methods/rows/" in methods
    assert "trend-svg" in methods

    direction = client.get("/static/js/direction.js").text
    assert "/api/direction/explore" in direction
    assert "evidence_refs" in direction

    workflow = client.get("/static/js/workflow.js").text
    assert "/api/tasks" in workflow
    assert "/api/workflow/template" in workflow
    assert "/api/workflow/gate" in workflow
    assert "kanban" in workflow


def test_workspace_error_and_empty_state_markers(client, project):
    html = _project_html(client, project)
    assert "模块未就绪" not in html  # runtime-only copy
    workspace = client.get("/static/js/workspace.js").text
    assert "模块未就绪" in workspace
    assert "还没有配置 LLM" in workspace
    assert "去设置" in workspace
    assert "empty error-state" in workspace
    assert "showError" in workspace


def test_delivery_export_citation_and_gate_wiring(client, project):
    delivery = client.get("/static/js/delivery.js").text
    for marker in (
        "/api/export/",
        "/api/citations/format",
        "/api/citations/verify",
        "/api/citations/checks",
        "/api/workflow/gate",
        "api.download",
        "window.confirm",
        "gbt7714",
    ):
        assert marker in delivery, marker
    html = _project_html(client, project)
    assert 'value="apa"' in html
    assert 'data-panel="delivery"' in html


def test_style_baseline_wiring(client):
    style = client.get("/static/js/style.js").text
    assert "/api/style/baseline" in style
    assert "baseline: baseline || undefined" in style
    assert "style-baseline-input" in style
    assert "style-baseline-summary" in style


def test_document_title_can_be_renamed(client, project):
    html = _project_html(client, project)
    tag = re.search(r'<input id="document-title"[^>]*>', html)
    assert tag is not None
    assert "readonly" not in tag.group(0)
    workspace = client.get("/static/js/workspace.js").text
    assert "renameDocument" in workspace
    assert 'api.patch("/api/documents/' in workspace
    assert "文档标题已保存" in workspace
