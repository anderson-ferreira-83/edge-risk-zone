# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Microcorte da /demo: selo de frescor, sliders e revelação pedagógica do resultado."""
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


def test_html_has_the_freshness_seal_and_no_click_drawing(client):
    html = client.get("/demo").text
    seal = re.search(r'<p id="freshness"[^>]*>', html).group(0)
    assert 'role="status"' in seal and 'aria-live="polite"' in seal and "hidden" in seal   # escondido até a 1ª análise
    assert 'id="freshness-icon"' in html and 'aria-hidden="true"' in html and 'id="freshness-text"' in html
    assert 'id="analyze-reason"' not in html and 'aria-describedby="analyze-reason"' not in html
    assert 'id="draw-toggle"' not in html and 'id="draw-undo"' not in html
    assert 'id="preview"' in html and 'O preview não recebe cliques.' in html
    assert " style=" not in html                                                         # a CSP bloqueia estilo inline
    assert html.index('id="annotated"') < html.index('id="freshness"')                  # primeiro observa, depois revela
    for details_id in ("diagnosis-details", "technical-details", "history-wrap"):
        assert " open" not in re.search(rf'<details id="{details_id}"[^>]*>', html).group(0)


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


def test_file_is_captured_for_request_and_history_when_selection_changes_during_analysis():
    body = _block(JS, "async function analyze()", "el.analyze.addEventListener")
    capture = body.index("const analyzedFile = state.file")
    fetch = body.index('fetch("/detect"')
    assert capture < fetch
    assert 'f.append("file", analyzedFile, analyzedFile.name)' in body
    assert "renderResult(conf, data, blob, analyzedFile.name)" in body

    render = _block(JS, "function renderResult(", "/* --- Inicialização ---")
    assert "function renderResult(conf, data, blob, analyzedFileName)" in render
    assert '" (" + analyzedFileName + ")"' in render
    assert "state.file.name" not in render
    assert "el.diagnosisDetails.open = false" in render and "el.technicalDetails.open = false" in render
    assert "el.historyWrap.open = false" in render


def test_input_card_resyncs_button_and_seal_after_every_control_handler():
    assert '["input", "change", "click"].forEach((type) => entrada.addEventListener(type, syncUi))' in JS
    assert "function syncUi() { refreshButtons(); refreshFreshness(); }" in JS


def test_display_scale_never_enters_the_analysis_key_or_requests():
    scale = _block(JS, "function setImageScale", "function showError")
    assert "dataset.imageScale" in scale and "state." not in scale
    assert "analysisKey" not in scale and "drawPreview" not in scale and "fetch(" not in scale


def test_microcut_keeps_the_api_contract_and_the_number_of_requests():
    assert JS.count('fetch("/detect"') == 1 and JS.count('fetch("/detect/image"') == 1   # continua 2 chamadas por análise
    assert set(re.findall(r'fetch\("(/[a-z/]+)"', JS)) == {"/detect", "/detect/image", "/health", "/zone"}


def test_seal_states_have_icon_and_text_not_only_color(client):
    css = client.get("/static/pages.css").text
    assert '.freshness[data-state="fresh"]' in css and '.freshness[data-state="stale"]' in css
    assert "grayscale" in css                                   # o PNG antigo esmaece, o texto não perde contraste
    assert '"Atualizado: ' in JS and '"Desatualizado: ' in JS    # texto explícito nos dois estados
