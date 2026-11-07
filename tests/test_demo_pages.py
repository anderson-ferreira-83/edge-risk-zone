# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Testes das páginas de documentação da demonstração: /demo/ajuda (alunos) e /demo/pipeline (Parte 1)."""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
PAGES = {"/demo/ajuda": "ajuda.html", "/demo/pipeline": "pipeline.html"}


@pytest.fixture(scope="module")
def client():
    # Sem `with`: o lifespan não roda e o modelo ONNX não é carregado. As páginas são estáticas, então
    # estes testes ficam rápidos e não dependem de onnxruntime (nem de uma CPU livre).
    main.app.state.settings = main.get_settings()  # o lifespan faria isto; o middleware de limite de corpo lê daqui
    return TestClient(main.app)


@pytest.mark.parametrize("path", PAGES)
def test_pages_are_served_with_restrictive_csp(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<html lang="pt-BR">' in response.text
    csp = response.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "http" not in csp
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("path", PAGES)
def test_pages_are_not_in_openapi_schema(client, path):
    assert path not in client.get("/openapi.json").json()["paths"]


def test_demo_links_to_all_pages(client):
    html = client.get("/demo").text
    for target in ("/demo", "/demo/ajuda", "/demo/pipeline", "/docs#/"):
        assert f'href="{target}"' in html
    assert "/static/pages.css" in html


@pytest.mark.parametrize("path", PAGES)
def test_pages_link_back_to_demo_and_to_each_other(client, path):
    html = client.get(path).text
    for target in ("/demo", "/demo/ajuda", "/demo/pipeline", "/docs#/"):
        assert f'href="{target}"' in html, (path, target)


def test_swagger_description_links_back_to_the_three_pages(client):
    description = client.get("/openapi.json").json()["info"]["description"]
    for target in ("/demo", "/demo/ajuda", "/demo/pipeline"):
        assert f"]({target})" in description


@pytest.mark.parametrize("path", PAGES)
def test_every_internal_link_resolves(client, path):
    html = client.get(path).text
    links = set(re.findall(r'(?:href|src)="(/[^"#]*)"', html))
    assert links
    registered = {route.path for route in main.app.routes}
    for link in links:
        if link == "/health":  # precisa do modelo carregado: aqui basta a rota existir
            assert link in registered
        else:
            assert client.get(link).status_code == 200, f"{path} -> {link}"


@pytest.mark.parametrize("name", ["ajuda.html", "pipeline.html", "pages.css"])
def test_new_assets_are_offline_and_csp_safe(name):
    text = (STATIC / name).read_text(encoding="utf-8")
    assert not re.search(r"""(?:src|href)=["']https?://""", text)
    assert "@import" not in text and "fonts.googleapis" not in text
    assert not re.search(r"url\(\s*['\"]?https?:", text)
    if name.endswith(".html"):  # a CSP bloqueia script e estilo inline: não pode haver nenhum
        assert "<script" not in text
        assert not re.search(r"\sstyle=", text)
        assert not re.search(r"\son[a-z]+=", text)


def test_student_guide_uses_the_real_button_labels(client):
    """O guia só vale se citar os nomes que a pessoa vê na tela."""
    demo, guide = client.get("/demo").text, client.get("/demo/ajuda").text
    for label in ("Imagem (JPEG ou PNG)", "Analisar", "Borda esquerda", "Margem amarela",
                  "Opção avançada: editar o polígono em JSON", "Restaurar zona padrão",
                  "Revelar diagnóstico e contagens", "Revelar tabela, tempos e JSON",
                  "Revelar comparação nesta sessão"):
        assert label in demo, f"rótulo ausente da /demo: {label}"
        assert label in guide, f"rótulo ausente do guia: {label}"


def test_student_guide_covers_the_lesson_essentials(client):
    guide = client.get("/demo/ajuda").text
    for term in ("limiar", "ponto do pé", "VERMELHO", "AMARELO", "VERDE", "falso negativo", "alarme", "pelo menos 3",
                 "não é um sistema de segurança certificado", "samples/"):
        assert term in guide, term


def test_pipeline_page_maps_every_part1_requirement(client):
    page = client.get("/demo/pipeline").text
    for requirement in ("Escolher um projeto da matriz", "Definir o modelo pré-treinado", "Justificar a escolha",
                        "Pipeline completo em Python", "Containerizar com Docker", "Imagem ARM64 via buildx",
                        "Adaptações para a Raspberry Pi 5", "curso de IA Aplicada presencial"):
        assert requirement in page, requirement
    for evidence in ("YOLOX-Tiny", "ONNX Runtime", "NMS", "POST /detect", "POST /detect/image", "buildx",
                     "docker-compose.yml", "verify_arch.py"):
        assert evidence in page, evidence


def test_pipeline_page_does_not_overclaim_arm64(client):
    """A honestidade sobre o que não foi provado faz parte do conteúdo."""
    page = client.get("/demo/pipeline").text
    assert "Execução da imagem arm64 na Raspberry Pi 5" in page and "Não verificada" in page
    assert "Execução da imagem arm64 emulada" in page  # o que foi provado (emulação) é dito sem estender à placa
    assert "Desempenho real na Raspberry Pi 5" in page and "Não medido" in page


# ---------------------------------------------------------------------------------------------
# Testes estruturais: provam a ligação entre requisito, situação e evidência (não só a presença
# de palavras na página).
# ---------------------------------------------------------------------------------------------
from html.parser import HTMLParser  # noqa: E402

REPO = STATIC.parent.parent


class _Tables(HTMLParser):
    """Extrai cada <table> como {legenda: [linha, ...]}; cada célula guarda texto, marcas .pill e <code>."""

    def __init__(self):
        super().__init__()
        self.tables, self._cap, self._rows, self._cell, self._in_caption = {}, None, None, None, False
        self._code = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._rows, self._cap = [], ""
        elif tag == "caption":
            self._in_caption = True
        elif tag == "tr" and self._rows is not None:
            self._rows.append([])
        elif tag in ("td", "th") and self._rows:
            self._cell = {"text": "", "pills": [], "codes": [], "header": tag == "th"}
            self._rows[-1].append(self._cell)
        elif tag == "span" and self._cell is not None and "pill" in (a.get("class") or "").split():
            self._cell["pills"].append([c for c in a["class"].split() if c != "pill"][0])
        elif tag == "code" and self._cell is not None:
            self._code = ""

    def handle_endtag(self, tag):
        if tag == "caption":
            self._in_caption = False
        elif tag == "code" and self._code is not None:
            self._cell["codes"].append(self._code.strip())
            self._code = None
        elif tag in ("td", "th"):
            self._cell = None
        elif tag == "table":
            self.tables[self._cap.strip()] = [r for r in self._rows if r and not r[0]["header"]]
            self._rows = None

    def handle_data(self, data):
        if self._in_caption:
            self._cap += data
        if self._cell is not None:
            self._cell["text"] += data
        if self._code is not None:
            self._code += data


def _tables(client, path):
    parser = _Tables()
    parser.feed(client.get(path).text)
    return parser.tables


REQUIREMENTS = "Instruções da Parte 1 e a evidência de cada uma"
STATE = "Estado das evidências"


EXPECTED_REQUIREMENTS = {
    "Escolher um projeto da matriz": ("ok", {"README.md"}),
    "Definir o modelo pré-treinado": ("ok", {"models/README.md"}),
    "Justificar a escolha (latência e precisão)": ("partial", {"README.md"}),
    "Pipeline completo em Python": ("ok", {"app/detector.py", "app/risk.py", "app/geometry.py", "tests/"}),
    "Containerizar com Docker e expor endpoints HTTP": ("ok", {"Dockerfile", "docker-compose.yml"}),
    "Imagem ARM64 via buildx": ("partial", {"scripts/build_multiarch.sh", "scripts/verify_arch.py", "docs/evidence/"}),
    "Adaptações para a Raspberry Pi 5": ("partial", {"README.md"}),
    "Considerar o projeto parte de um curso de IA Aplicada presencial": ("ok", set()),
}
ICON = {"ok": "✓", "partial": "▲", "pending": "✖"}


def test_each_requirement_has_the_expected_status_and_exact_evidence(client):
    """Trocar a evidência de uma linha, ou escrever "Pendente" com a classe "ok", precisa falhar."""
    rows = _tables(client, "/demo/pipeline")[REQUIREMENTS]
    found = {r[0]["text"].strip(): (r[2]["pills"][0], r[2]["text"].strip(), set(r[3]["codes"]), r[3]["text"])
             for r in rows}
    assert set(found) == set(EXPECTED_REQUIREMENTS)
    for name, (status, label, evidence, where_text) in found.items():
        want_status, want_evidence = EXPECTED_REQUIREMENTS[name]
        assert status == want_status, f"{name}: situação {status}, esperada {want_status}"
        assert label.startswith(ICON[status]), f"{name}: o texto '{label}' contradiz a classe '{status}'"
        assert evidence == want_evidence, f"{name}: evidências {evidence}, esperadas {want_evidence}"
        if not want_evidence:
            assert "Parte 2" in where_text


def test_requirements_table_has_eight_rows_each_with_one_status_and_evidence(client):
    rows = _tables(client, "/demo/pipeline")[REQUIREMENTS]
    assert len(rows) == 8
    for requirement, what, status, where in rows:
        assert len(status["pills"]) == 1 and status["pills"][0] in {"ok", "partial", "pending"}, requirement["text"]
        assert what["text"].strip() and (where["codes"] or "/demo" in where["text"] or "Parte 2" in where["text"]), requirement["text"]


def test_every_file_cited_as_evidence_exists_in_the_repository(client):
    rows = _tables(client, "/demo/pipeline")[REQUIREMENTS]
    cited = [code for _, _, _, where in rows for code in where["codes"]]
    assert len(cited) >= 9
    for path in cited:
        assert (REPO / path).exists(), f"a página cita {path}, que não existe no repositório"


def _status_by_requirement(client):
    return {r[0]["text"].strip(): (r[2]["pills"][0], r[2]["text"].strip())
            for r in _tables(client, "/demo/pipeline")[REQUIREMENTS]}


def test_unproven_items_are_never_marked_as_fully_done(client):
    status = _status_by_requirement(client)
    assert status["Imagem ARM64 via buildx"][0] == "partial"
    assert "execução na placa não verificada" in status["Imagem ARM64 via buildx"][1]
    assert status["Adaptações para a Raspberry Pi 5"][0] == "partial"
    assert status["Justificar a escolha (latência e precisão)"][0] == "partial"
    for verified in ("Pipeline completo em Python", "Containerizar com Docker e expor endpoints HTTP"):
        assert status[verified][0] == "ok", verified


def test_state_table_keeps_pi_execution_and_performance_as_not_proven(client):
    rows = {r[0]["text"].strip(): r[1]["pills"][0] for r in _tables(client, "/demo/pipeline")[STATE]}
    assert rows["Execução da imagem arm64 na Raspberry Pi 5"] == "pending"
    assert rows["Execução da imagem arm64 emulada (QEMU, em x86_64)"] == "ok"
    assert rows["Desempenho real na Raspberry Pi 5"] == "pending"
    assert rows["Qualidade da detecção com câmera real em uma planta"] == "pending"
    assert rows["Binários da imagem arm64 são AArch64"] == "ok"
    for row in _tables(client, "/demo/pipeline")[STATE]:
        status, label = row[1]["pills"][0], row[1]["text"].strip()
        assert label.startswith(ICON[status]), f"{row[0]['text'].strip()}: '{label}' contradiz a classe '{status}'"


def test_timeline_follows_the_real_order_of_the_work(client):
    html = client.get("/demo/pipeline").text
    titles = re.findall(r'class="tl-title">([^<]+)<', html)
    assert titles[0] == "Escolha do projeto"
    order = [titles.index(t) for t in ("Docker (amd64)", "Build arm64 com buildx", "Medição e documentação",
                                       "Material do curso", "Revisão independente e correções",
                                       "Simulação para os alunos")]
    assert order == sorted(order), titles  # o curso vem antes da revisão; a simulação, por último
    assert titles[-1] == "Simulação para os alunos"


@pytest.mark.parametrize("path", PAGES)
def test_pages_have_one_h1_one_main_and_a_working_skip_link(client, path):
    html = client.get(path).text
    assert len(re.findall(r"<h1\b", html)) == 1
    assert len(re.findall(r"<main\b", html)) == 1
    target = re.search(r'class="skip-link" href="#([^"]+)"', html).group(1)
    assert f'id="{target}"' in html
    assert 'aria-label="Páginas da demonstração"' in html and 'aria-current="page"' in html


def test_scrolling_tables_are_keyboard_reachable_and_labelled(client):
    for path in PAGES:
        html = client.get(path).text
        regions = re.findall(r'<div class="table-wrap"[^>]*>', html)
        assert regions
        for tag in regions:
            assert 'role="region"' in tag and 'tabindex="0"' in tag and 'aria-label="' in tag


def test_decorative_css_arrows_are_hidden_from_screen_readers():
    css = (STATIC / "pages.css").read_text(encoding="utf-8")
    assert css.count('content: "→" / ""') == 1 and css.count('content: "↓" / ""') == 1


def _block(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


def test_guide_zone_section_matches_slider_only_behavior(client):
    """Guarda de sincronia: o preview não recebe cliques e os sliders reescrevem polygon + margin."""
    js = (STATIC / "demo.js").read_text(encoding="utf-8")
    guide, demo = client.get("/demo/ajuda").text, client.get("/demo").text
    preview = _block(js, "function drawPreview()", "function syncZoneControls")
    assert "ctx.arc(" not in preview and "fillText(" not in preview
    parse = _block(js, "function parseZoneText", "function zoneToText")

    # o preview não recebe cliques; não existe modo de desenho nem cursor de desenho
    assert 'el.preview.addEventListener("click"' not in js and "drawToggle" not in js and "drawUndo" not in js
    assert 'id="draw-toggle"' not in demo and 'id="draw-undo"' not in demo
    assert "O preview não recebe cliques" in guide and "O preview não recebe cliques" in demo
    # a faixa amarela (margem) só aparece no PNG anotado, não no preview de entrada
    assert "margin" not in preview and "faixa amarela" in guide
    # mínimo de 3 vértices
    assert "polygon.length < 3" in parse and "<strong>pelo menos 3</strong>" in guide
    # Analisar depende apenas de imagem e estado ocupado
    refresh = _block(js, "function refreshButtons()", "/* --- Selo de frescor")
    assert "el.analyze.disabled = !hasImage || state.busy" in refresh and "drawing" not in refresh
    # o selo de frescor existe e o guia o descreve
    assert 'id="freshness"' in demo and "Atualizado" in guide and "Desatualizado" in guide
    # o ajuste rápido preserva a API: só reescreve o mesmo JSON de polygon + margin
    sliders = _block(js, "function applyRectangleControls", "function loadImage")
    assert "zoneFromRectPercent" in sliders and "setZone(zone)" in sliders
    assert "Ajuste rápido da zona retangular" in guide and "alteram somente a geometria enviada à API" in guide
    # a resposta pedagógica vem depois da imagem e começa escondida em <details>
    assert demo.index('id="annotated"') < demo.index('id="diagnosis-details"')
    assert "registre sua hipótese" in guide and "se fecham automaticamente" in guide


@pytest.mark.parametrize("path", PAGES)
def test_status_glyphs_are_decorative_for_screen_readers(client, path):
    """O texto (Feito, Verificado, VERMELHO...) já diz o estado; o glifo não deve ser lido de novo."""
    html = client.get(path).text
    glyphs = re.findall(r'<span class="(?:pill [a-z]+|tag)"[^>]*>(.{0,30})', html)
    assert glyphs
    for start in glyphs:
        assert start.startswith('<span aria-hidden="true">'), start


def test_pages_declare_an_empty_favicon(client):
    """Sem isso o navegador pede /favicon.ico, recebe 404 e deixa um erro no console durante a demonstração."""
    for path in ("/demo", *PAGES):
        assert '<link rel="icon" href="data:,">' in client.get(path).text, path
