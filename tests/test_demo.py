"""Testes da página /demo e dos arquivos estáticos (sem navegador)."""
import hashlib
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
LOGO = Path(__file__).resolve().parent.parent / "app" / "static" / "logo-fit.png"


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_demo_page_is_served_as_html(client):
    response = client.get("/demo")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert '<html lang="pt-BR">' in html
    assert "/static/demo.css" in html and "/static/demo.js" in html


def test_demo_has_required_controls(client):
    html = client.get("/demo").text
    for element_id in ("file", "preview", "conf-range", "conf-number", "zone-json", "analyze", "annotated", "json-out"):
        assert f'id="{element_id}"' in html
    assert 'accept="image/jpeg,image/png"' in html
    assert 'for="file"' in html and 'for="zone-json"' in html  # rótulos associados aos campos


def test_demo_sets_restrictive_csp_and_no_cache(client):
    response = client.get("/demo")
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert "http" not in csp  # nenhuma origem externa permitida
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path,media", [("/static/demo.css", "text/css"), ("/static/demo.js", "javascript"),
                                        ("/static/logo-fit.png", "image/png")])
def test_static_files_are_served(client, path, media):
    response = client.get(path)
    assert response.status_code == 200
    assert media in response.headers["content-type"]
    assert len(response.content) > 100


def test_missing_static_file_is_404(client):
    assert client.get("/static/nao-existe.js").status_code == 404


def test_static_does_not_escape_directory(client):
    # tentativa de percorrer diretórios: o Starlette recusa (404), nunca devolve app/main.py
    for path in ("/static/../main.py", "/static/%2e%2e/main.py", "/static/..%2fmain.py"):
        response = client.get(path)
        assert response.status_code in (400, 404)
        assert "FastAPI" not in response.text


def test_demo_is_not_in_openapi_schema(client):
    assert "/demo" not in client.get("/openapi.json").json()["paths"]


def test_existing_endpoints_unchanged_by_static_mount(client):
    assert client.get("/health").json()["status"] == "ok"
    assert len(client.get("/zone").json()["polygon"]) >= 3
    assert client.get("/docs").status_code == 200


def test_demo_assets_have_no_external_references():
    """Funciona offline: nenhum recurso remoto (CDN, fonte, script) nos arquivos da demonstração."""
    for name in ("demo.html", "demo.css", "demo.js"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"""(?:src|href)=["']https?://""", text), name
        assert "@import" not in text and "//cdn" not in text and "fonts.googleapis" not in text, name
        assert not re.search(r"url\(\s*['\"]?https?:", text), name


def test_demo_js_does_not_persist_images():
    js = (STATIC / "demo.js").read_text(encoding="utf-8")
    for forbidden in ("localStorage", "sessionStorage", "indexedDB", "innerHTML"):
        assert forbidden not in js


def test_demo_calls_only_contract_endpoints():
    js = (STATIC / "demo.js").read_text(encoding="utf-8")
    called = set(re.findall(r'fetch\("(/[a-z/]+)"', js))
    assert called == {"/detect", "/detect/image", "/health", "/zone"}


def test_logo_is_unmodified_png():
    data = LOGO.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    # SHA-256 do logo fornecido para a candidatura. Assim o repositório continua
    # autocontido no GitHub/CI e ainda detecta recorte, recompressão ou recoloração.
    assert hashlib.sha256(data).hexdigest() == "e5ff80ed8b8f7ab6010202061bb4626ef42adf2b9b7d2b5ebd0ae4a5a77d87f0"
