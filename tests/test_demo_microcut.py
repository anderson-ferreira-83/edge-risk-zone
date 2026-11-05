"""Microcorte da /demo: selo de frescor do resultado e bloqueio de Analisar durante o desenho."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
JS = (STATIC / "demo.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client():
    main.app.state.settings = main.get_settings()
    return TestClient(main.app)


def _block(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node não está instalado")
def test_pure_logic_passes_under_node_test():
    result = subprocess.run(["node", "--test", str(ROOT / "tests" / "demo_logic.test.mjs")],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (result.stdout[-1500:] + result.stderr[-500:])


def test_html_has_the_freshness_seal_and_the_block_reason(client):
    html = client.get("/demo").text
    seal = re.search(r'<p id="freshness"[^>]*>', html).group(0)
    assert 'role="status"' in seal and 'aria-live="polite"' in seal and "hidden" in seal   # escondido até a 1ª análise
    assert 'id="freshness-icon"' in html and 'aria-hidden="true"' in html and 'id="freshness-text"' in html
    reason = re.search(r'<p id="analyze-reason"[^>]*>', html).group(0)
    assert 'role="status"' in reason and 'aria-live="polite"' in reason and "hidden" in reason
    assert 'aria-describedby="analyze-reason"' in re.search(r'<button[^>]*id="analyze"[^>]*>', html).group(0)
    assert " style=" not in html                                                         # a CSP bloqueia estilo inline


def test_analyze_captures_the_key_before_waiting_and_stores_it_only_on_success():
    body = _block(JS, "async function analyze()", "el.analyze.addEventListener")
    capture, fetch, render = body.index("const key = analysisKey("), body.index('fetch("/detect"'), body.index("renderResult(")
    store, catch = body.index("state.lastAnalyzedKey = key"), body.index("} catch")
    assert capture < fetch < render < store < catch          # captura antes de esperar; grava só depois de renderizar, no ramo de sucesso
    assert body.count("lastAnalyzedKey = ") == 1             # nenhum outro lugar marca "atualizado"
    assert "refreshFreshness();" in body[catch:]             # e o selo é reavaliado ao final, ocorrendo erro ou não


def test_any_new_file_invalidates_the_previous_result():
    handler = _block(JS, 'el.file.addEventListener("change"', "el.range.addEventListener")
    assert "state.fileToken += 1" in handler


def test_input_card_resyncs_button_and_seal_after_every_control_handler():
    assert '["input", "change", "click"].forEach((type) => entrada.addEventListener(type, syncUi))' in JS
    assert "function syncUi() { refreshButtons(); refreshFreshness(); }" in JS


def test_microcut_keeps_the_api_contract_and_the_number_of_requests():
    assert JS.count('fetch("/detect"') == 1 and JS.count('fetch("/detect/image"') == 1   # continua 2 chamadas por análise
    assert set(re.findall(r'fetch\("(/[a-z/]+)"', JS)) == {"/detect", "/detect/image", "/health", "/zone"}


def test_seal_states_have_icon_and_text_not_only_color(client):
    css = client.get("/static/pages.css").text
    assert '.freshness[data-state="fresh"]' in css and '.freshness[data-state="stale"]' in css
    assert "grayscale" in css                                   # o PNG antigo esmaece, o texto não perde contraste
    assert '"Atualizado: ' in JS and '"Desatualizado: ' in JS    # texto explícito nos dois estados
