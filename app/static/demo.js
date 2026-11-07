// SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
// SPDX-License-Identifier: MIT
/* Edge Risk Zone: página de demonstração local.
   Sem framework, sem CDN e sem armazenamento: a imagem fica só em memória (URLs de objeto são revogadas)
   e o histórico da sessão guarda apenas texto, na memória da página. */
"use strict";

const LEVELS = {
  green: { label: "VERDE", icon: "✓" },
  yellow: { label: "AMARELO", icon: "▲" },
  red: { label: "VERMELHO", icon: "✖" },
};
const FALLBACK_ZONE = { polygon: [[0.3, 0.45], [0.98, 0.45], [0.98, 0.98], [0.3, 0.98]], margin: 0.06 };

/* ---------- Funções puras (testáveis sem navegador) ---------- */

/** Formata um número com vírgula decimal (pt-BR), com 2 casas. */
function formatConf(value) {
  return Number(value).toFixed(2).replace(".", ",");
}

/** Converte "0,35" ou "0.35" em número; devolve NaN se inválido. */
function parseConf(raw) {
  return Number(String(raw).trim().replace(",", "."));
}

/** Valida o texto do JSON da zona. Devolve { zone } ou { error } (sem lançar exceção). */
function parseZoneText(text) {
  if (!text || !text.trim()) return { error: "Informe a zona em JSON, por exemplo o formato de GET /zone." };
  let data;
  try { data = JSON.parse(text); } catch (e) { return { error: "JSON inválido: " + e.message }; }
  if (data === null || typeof data !== "object" || Array.isArray(data)) return { error: "A zona deve ser um objeto JSON com \"polygon\" e, opcionalmente, \"margin\"." };
  if (!Array.isArray(data.polygon) || data.polygon.length < 3) return { error: "\"polygon\" precisa de pelo menos 3 vértices [x, y]." };
  for (const p of data.polygon) {
    if (!Array.isArray(p) || p.length !== 2 || !p.every((v) => typeof v === "number" && Number.isFinite(v))) {
      return { error: "Cada vértice deve ser um par numérico [x, y]." };
    }
    if (p.some((v) => v < 0 || v > 1)) return { error: "As coordenadas dos vértices devem estar entre 0 e 1." };
  }
  if (data.margin !== undefined && (typeof data.margin !== "number" || !(data.margin >= 0 && data.margin <= 0.5))) {
    return { error: "\"margin\" deve ser um número entre 0 e 0,5." };
  }
  return { zone: data };
}

/** Serializa a zona de forma legível: um vértice por linha. */
function zoneToText(zone) {
  const pts = zone.polygon.map((p) => "    [" + p[0] + ", " + p[1] + "]").join(",\n");
  const margin = zone.margin === undefined ? "" : ",\n  \"margin\": " + zone.margin;
  return "{\n  \"polygon\": [\n" + pts + "\n  ]" + margin + "\n}";
}

/** Traduz um erro HTTP do serviço em mensagem clara em português. */
function httpErrorMessage(status, detail) {
  const text = typeof detail === "string" ? detail : (Array.isArray(detail) ? detail.map((d) => d.msg || JSON.stringify(d)).join("; ") : "");
  const base = {
    400: "Arquivo recusado: vazio ou não é uma imagem válida (envie JPEG ou PNG).",
    413: "Arquivo ou resolução acima do limite aceito pelo serviço.",
    422: "Parâmetros recusados pelo serviço (zona ou limiar inválidos).",
  }[status] || "O serviço respondeu com erro HTTP " + status + ".";
  return text ? base + " Detalhe do serviço: " + text : base;
}

/** Resumo em texto de uma resposta de /detect, para o histórico e para o texto alternativo. */
function summarize(conf, data) {
  const n = data.summary.persons_total;
  return "limiar " + formatConf(conf) + ": " + n + (n === 1 ? " pessoa" : " pessoas") + ", risco " + LEVELS[data.risk_level].label;
}

/** Constrói uma zona retangular a partir de percentuais inteiros (0 a 100); null se a ordem for inválida. */
function zoneFromRectPercent(left, top, right, bottom, margin) {
  const values = [left, top, right, bottom, margin].map(Number);
  if (!values.every(Number.isFinite)) return null;
  [left, top, right, bottom, margin] = values;
  if (left < 0 || top < 0 || right > 100 || bottom > 100 || margin < 0 || margin > 50 || left >= right || top >= bottom) return null;
  const norm = (value) => Math.round(value * 10) / 1000;
  return { polygon: [[norm(left), norm(top)], [norm(right), norm(top)], [norm(right), norm(bottom)], [norm(left), norm(bottom)]],
           margin: norm(margin) };
}

/** Devolve o retângulo envolvente da zona em percentuais e informa se o polígono já era esse retângulo. */
function rectPercentFromZone(zone) {
  if (!zone || !Array.isArray(zone.polygon) || zone.polygon.length < 3) return null;
  const xs = zone.polygon.map((p) => p[0]);
  const ys = zone.polygon.map((p) => p[1]);
  if (![...xs, ...ys].every((v) => Number.isFinite(v))) return null;
  const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
  const corners = [[left, top], [right, top], [right, bottom], [left, bottom]];
  const same = (a, b) => Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;
  const isRectangle = zone.polygon.length === 4 && corners.every((corner) => zone.polygon.some((point) => same(point, corner)));
  const pct = (value) => Math.round(value * 100);
  return { left: pct(left), top: pct(top), right: pct(right), bottom: pct(bottom),
           margin: pct(zone.margin === undefined ? FALLBACK_ZONE.margin : zone.margin), isRectangle };
}

/** Forma canônica da zona (sem espaços nem campos extras); se o JSON for inválido, o texto compactado. */
function canonicalZone(text) {
  const parsed = parseZoneText(text);
  if (parsed.zone) return JSON.stringify({ polygon: parsed.zone.polygon, margin: parsed.zone.margin === undefined ? null : parsed.zone.margin });
  return "invalida:" + String(text).replace(/\s+/g, " ").trim();
}

/** Chave do que uma análise usa: arquivo (por um contador), limiar e zona. Se mudar, o resultado está desatualizado. */
function analysisKey(fileToken, conf, zoneText) {
  return JSON.stringify([fileToken, Number.isFinite(conf) ? Number(conf.toFixed(4)) : null, canonicalZone(zoneText)]);
}

/** "none" antes da primeira análise; "fresh" se a última análise usou exatamente os parâmetros atuais; senão "stale". */
function freshnessOf(currentKey, lastAnalyzedKey) {
  if (lastAnalyzedKey === null || lastAnalyzedKey === undefined) return "none";
  return currentKey === lastAnalyzedKey ? "fresh" : "stale";
}

if (typeof module !== "undefined") {
  module.exports = { formatConf, parseConf, parseZoneText, zoneToText, httpErrorMessage, summarize,
                     zoneFromRectPercent, rectPercentFromZone, canonicalZone, analysisKey, freshnessOf };
}

/* ---------- Interface (somente no navegador) ---------- */
if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const el = {
    file: $("file"), preview: $("preview"), previewEmpty: $("preview-empty"),
    range: $("conf-range"), number: $("conf-number"), confText: $("conf-text"),
    zoneJson: $("zone-json"), zoneError: $("zone-error"), zoneReset: $("zone-reset"),
    zoneLeft: $("zone-left"), zoneRight: $("zone-right"), zoneTop: $("zone-top"), zoneBottom: $("zone-bottom"),
    zoneMargin: $("zone-margin"), zoneLeftOut: $("zone-left-out"), zoneRightOut: $("zone-right-out"),
    zoneTopOut: $("zone-top-out"), zoneBottomOut: $("zone-bottom-out"), zoneMarginOut: $("zone-margin-out"),
    zoneSliderNote: $("zone-slider-note"),
    analyze: $("analyze"), status: $("status"), error: $("error"),
    serviceStatus: $("service-status"), resultSection: $("resultado"),
    resultEmpty: $("result-empty"), result: $("result"),
    banner: $("risk-banner"), riskIcon: $("risk-icon"), riskLabel: $("risk-label"), riskMessage: $("risk-message"),
    nTotal: $("n-total"), nGreen: $("n-green"), nYellow: $("n-yellow"), nRed: $("n-red"),
    annotated: $("annotated"), personsBody: $("persons-body"), personsNone: $("persons-none"),
    timings: $("timings"), jsonOut: $("json-out"), historyWrap: $("history-wrap"), history: $("history"),
    freshness: $("freshness"), freshnessIcon: $("freshness-icon"), freshnessText: $("freshness-text"),
    diagnosisDetails: $("diagnosis-details"), technicalDetails: $("technical-details"), revealState: $("reveal-state"),
  };
  const state = { file: null, imageUrl: null, image: null, defaultZone: null, annotatedUrl: null, busy: false,
                  fileToken: 0, lastAnalyzedKey: null };

  function currentConf() { return parseConf(el.number.value); }

  function setConf(value) {
    const v = Number(value);
    el.range.value = String(v);
    el.number.value = String(v);
    el.confText.textContent = formatConf(v);
    document.querySelectorAll("[data-conf]").forEach((b) => b.setAttribute("aria-pressed", String(Math.abs(Number(b.dataset.conf) - v) < 1e-9)));
  }

  /** Ajusta somente a escala CSS compartilhada do preview e do PNG; não altera imagem, zona ou inferência. */
  function setImageScale(value) {
    const scale = Number(value);
    if (![50, 75, 100].includes(scale)) return;
    document.documentElement.dataset.imageScale = String(scale);
    document.querySelectorAll("button[data-image-scale]").forEach((button) => {
      button.setAttribute("aria-pressed", String(Number(button.dataset.imageScale) === scale));
    });
  }

  function showError(message) {
    el.error.textContent = message;
    el.error.hidden = !message;
  }

  function refreshButtons() {
    const hasImage = !!state.file;
    el.analyze.disabled = !hasImage || state.busy;
  }

  /* --- Selo de frescor do resultado --- */
  function currentKey() { return analysisKey(state.fileToken, currentConf(), el.zoneJson.value); }

  /** Atualiza o selo: compara a chave de agora com a da última análise e mostra "Atualizado" ou "Desatualizado". */
  function refreshFreshness() {
    const f = freshnessOf(currentKey(), state.lastAnalyzedKey);
    el.result.dataset.freshness = f;
    el.freshness.dataset.state = f;
    el.freshness.hidden = f === "none";
    el.freshnessIcon.textContent = f === "fresh" ? "✓" : f === "stale" ? "▲" : "";
    el.freshnessText.textContent = f === "fresh"
      ? "Atualizado: este resultado corresponde à imagem, à zona e ao limiar atuais."
      : f === "stale" ? "Desatualizado: a imagem, a zona ou o limiar mudaram desde esta análise. Clique em Analisar." : "";
    el.revealState.textContent = f === "fresh"
      ? "· resultado atual"
      : f === "stale" ? "· desatualizado — analise novamente" : "";
  }

  /* --- Zona e pré-visualização --- */
  function readZone() {
    const parsed = parseZoneText(el.zoneJson.value);
    el.zoneJson.setAttribute("aria-invalid", parsed.error ? "true" : "false");
    el.zoneError.textContent = parsed.error || "";
    return parsed;
  }

  /** Redesenha a pré-visualização: imagem original e área da zona, sem alças ou vértices clicáveis.
      Os vértices normalizados (0 a 1) viram pixels do canvas; a espessura acompanha a largura da imagem. */
  function drawPreview() {
    const img = state.image;
    if (!img) return;
    const c = el.preview;
    c.width = img.naturalWidth;
    c.height = img.naturalHeight;
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const parsed = parseZoneText(el.zoneJson.value);
    if (!parsed.zone) return;
    const pts = parsed.zone.polygon.map((p) => [p[0] * c.width, p[1] * c.height]);
    const scale = Math.max(1, c.width / 640);
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
    ctx.closePath();
    ctx.fillStyle = "rgba(210, 40, 40, 0.35)";
    ctx.fill();
    ctx.lineWidth = 3 * scale;
    ctx.strokeStyle = "#d22828";
    ctx.stroke();
    c.setAttribute("aria-label", "Pré-visualização da imagem enviada, com a zona de risco desenhada como uma área de contorno vermelho");
  }

  function syncZoneControls(zone) {
    const rect = rectPercentFromZone(zone);
    if (!rect) return;
    const values = [[el.zoneLeft, el.zoneLeftOut, rect.left], [el.zoneRight, el.zoneRightOut, rect.right],
                    [el.zoneTop, el.zoneTopOut, rect.top], [el.zoneBottom, el.zoneBottomOut, rect.bottom]];
    values.forEach(([input, output, value]) => { input.value = String(value); output.textContent = value + "%"; });
    el.zoneMargin.value = String(Math.min(20, rect.margin));
    el.zoneMarginOut.textContent = (Number(el.zoneMargin.value) / 100).toFixed(2).replace(".", ",");
    el.zoneSliderNote.textContent = rect.isRectangle
      ? "Os controles representam a zona retangular mostrada no preview."
      : "A zona atual é um polígono livre. Os controles mostram seu contorno; mover um deles a substituirá por um retângulo.";
  }

  function setZone(zone) {
    el.zoneJson.value = zoneToText(zone);
    readZone();
    syncZoneControls(zone);
    drawPreview();
  }

  /** Aplica os cinco controles rápidos. Mantém pelo menos 5% de largura e altura. */
  function applyRectangleControls(changed) {
    let left = Number(el.zoneLeft.value), right = Number(el.zoneRight.value);
    let top = Number(el.zoneTop.value), bottom = Number(el.zoneBottom.value);
    const margin = Number(el.zoneMargin.value);
    if (right - left < 5) {
      if (changed === el.zoneLeft) right = Math.min(100, left + 5);
      else left = Math.max(0, right - 5);
    }
    if (bottom - top < 5) {
      if (changed === el.zoneTop) bottom = Math.min(100, top + 5);
      else top = Math.max(0, bottom - 5);
    }
    const zone = zoneFromRectPercent(left, top, right, bottom, margin);
    if (!zone) return;
    setZone(zone);
    el.status.textContent = "Zona retangular atualizada no preview. Clique em Analisar para executar o modelo.";
    refreshButtons();
  }

  /** Carrega o arquivo escolhido na pré-visualização. A imagem vira uma URL `blob:` local (nada é enviado ainda);
      a URL anterior é revogada para liberar a memória. */
  function loadImage(file) {
    if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
    state.imageUrl = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      state.image = img;
      el.previewEmpty.hidden = true;
      el.preview.hidden = false;
      drawPreview();
      refreshButtons();
    };
    img.onerror = () => {
      state.image = null;
      state.file = null;
      el.preview.hidden = true;
      el.previewEmpty.hidden = false;
      showError("Não foi possível abrir o arquivo como imagem. Escolha um JPEG ou PNG.");
      refreshButtons();
    };
    img.src = state.imageUrl;
  }

  /* --- Eventos --- */
  el.file.addEventListener("change", () => {
    state.fileToken += 1;   // qualquer troca de arquivo invalida o resultado anterior
    showError("");
    const file = el.file.files && el.file.files[0];
    if (!file) { state.file = null; refreshButtons(); return; }
    if (!/^image\/(jpeg|png)$/.test(file.type)) {
      state.file = null;
      refreshButtons();
      showError("Tipo de arquivo não aceito (" + (file.type || "desconhecido") + "). Envie JPEG ou PNG.");
      return;
    }
    state.file = file;
    el.status.textContent = "Imagem carregada: " + file.name + ".";
    loadImage(file);
    refreshButtons();
  });

  el.range.addEventListener("input", () => setConf(el.range.value));
  el.number.addEventListener("input", () => {
    const v = currentConf();
    if (Number.isFinite(v) && v >= 0.01 && v <= 0.99) setConf(v);
  });
  document.querySelectorAll("[data-conf]").forEach((b) => b.addEventListener("click", () => setConf(b.dataset.conf)));
  document.querySelectorAll("button[data-image-scale]").forEach((b) => b.addEventListener("click", () => setImageScale(b.dataset.imageScale)));

  el.zoneJson.addEventListener("input", () => {
    const parsed = readZone();
    if (parsed.zone) syncZoneControls(parsed.zone);
    drawPreview();
  });
  el.zoneReset.addEventListener("click", () => { setZone(state.defaultZone || FALLBACK_ZONE); el.status.textContent = "Zona padrão restaurada."; });
  [el.zoneLeft, el.zoneRight, el.zoneTop, el.zoneBottom, el.zoneMargin]
    .forEach((control) => control.addEventListener("input", () => applyRectangleControls(control)));

  /* --- Análise --- */
  async function parseBody(response) {
    const type = response.headers.get("content-type") || "";
    if (type.includes("application/json")) { try { return await response.json(); } catch (e) { return null; } }
    return null;
  }

  /**
   * Envia a imagem ao serviço e mostra o resultado. Passos:
   * 1) valida arquivo, limiar e zona; 2) captura o arquivo e a chave do que esta análise usa, ANTES de esperar;
   * 3) chama /detect (JSON) e /detect/image (PNG) em paralelo, cada um com seu FormData; 4) só desenha se as duas respostas deram certo.
   * Se algo mudar durante a espera, a chave guardada deixa de bater com a atual e o selo mostra "Desatualizado".
   */
  async function analyze() {
    showError("");
    if (!state.file) { showError("Escolha uma imagem JPEG ou PNG antes de analisar."); return; }
    const analyzedFile = state.file;   // a entrada desta análise não muda se o usuário escolher outro arquivo enquanto espera
    const conf = currentConf();
    if (!Number.isFinite(conf) || conf <= 0 || conf >= 1) { showError("O limiar deve ser um número maior que 0 e menor que 1."); el.number.focus(); return; }
    const parsed = readZone();
    if (parsed.error) { showError("Zona inválida. " + parsed.error); el.zoneJson.focus(); return; }
    const key = analysisKey(state.fileToken, conf, el.zoneJson.value);   // o que ESTA análise usa, capturado antes de esperar

    state.busy = true;
    el.resultSection.setAttribute("aria-busy", "true");
    refreshButtons();
    el.status.textContent = "Analisando… (limiar " + formatConf(conf) + ")";
    const started = performance.now();

    const form = () => {
      const f = new FormData();
      f.append("file", analyzedFile, analyzedFile.name);
      f.append("zone", JSON.stringify(parsed.zone));
      f.append("conf", String(conf));
      return f;
    };

    try {
      const [jsonRes, pngRes] = await Promise.all([
        fetch("/detect", { method: "POST", body: form() }),
        fetch("/detect/image", { method: "POST", body: form() }),
      ]);
      if (!jsonRes.ok) { const b = await parseBody(jsonRes); throw new Error(httpErrorMessage(jsonRes.status, b && b.detail)); }
      if (!pngRes.ok) { const b = await parseBody(pngRes); throw new Error(httpErrorMessage(pngRes.status, b && b.detail)); }
      const data = await jsonRes.json();
      const blob = await pngRes.blob();
      renderResult(conf, data, blob, analyzedFile.name);
      state.lastAnalyzedKey = key;   // se algo mudou durante a espera, currentKey() != key e o selo mostra "Desatualizado"
      const elapsed = Math.round(performance.now() - started);
      el.status.textContent = "Análise concluída em " + elapsed + " ms (JSON e imagem). Observe o resultado e registre sua hipótese antes de revelar o diagnóstico.";
    } catch (err) {
      const offline = err instanceof TypeError;
      showError(offline ? "Não foi possível falar com o serviço. Confira se o container (ou o uvicorn) está em execução e se esta página foi aberta a partir dele." : err.message);
      el.status.textContent = "";
    } finally {
      state.busy = false;
      el.resultSection.setAttribute("aria-busy", "false");
      refreshButtons();
      refreshFreshness();
    }
  }
  el.analyze.addEventListener("click", analyze);

  /* Qualquer mudança nos controles de entrada (arquivo, limiar ou zona) reavalia o selo e o botão.
     Ouvinte no cartão, que roda depois dos tratadores de cada controle (bolha do evento). */
  function syncUi() { refreshButtons(); refreshFreshness(); }
  const entrada = document.getElementById("entrada");
  ["input", "change", "click"].forEach((type) => entrada.addEventListener(type, syncUi));

  /** Mostra o resultado da mesma análise: faixa de risco, contagens, PNG anotado, tabela de pessoas, tempos e JSON.
      Monta a tabela com `createElement` e `textContent`, sem inserir HTML como texto: o conteúdo vindo do serviço não vira marcação.
      A URL `blob:` do PNG anterior é revogada; o histórico guarda no máximo 6 linhas de texto. */
  function renderResult(conf, data, blob, analyzedFileName) {
    el.resultEmpty.hidden = true;
    el.result.hidden = false;
    el.diagnosisDetails.open = false;
    el.technicalDetails.open = false;
    el.historyWrap.open = false;
    const level = LEVELS[data.risk_level];
    el.banner.dataset.level = data.risk_level;
    el.riskIcon.textContent = level.icon;
    el.riskLabel.textContent = level.label;
    el.riskMessage.textContent = data.alert.message;
    el.nTotal.textContent = data.summary.persons_total;
    el.nGreen.textContent = data.summary.green;
    el.nYellow.textContent = data.summary.yellow;
    el.nRed.textContent = data.summary.red;

    if (state.annotatedUrl) URL.revokeObjectURL(state.annotatedUrl);
    state.annotatedUrl = URL.createObjectURL(blob);
    el.annotated.src = state.annotatedUrl;
    el.annotated.alt = "Imagem anotada pelo serviço, com zona, faixa de atenção e caixas rotuladas por nível. Registre sua hipótese antes de revelar o diagnóstico textual.";

    el.personsBody.textContent = "";
    data.persons.forEach((p) => {
      const tr = document.createElement("tr");
      const cells = [String(p.id), (p.confidence * 100).toFixed(1).replace(".", ",") + "%"];
      cells.forEach((t) => { const td = document.createElement("td"); td.textContent = t; tr.appendChild(td); });
      const tdLevel = document.createElement("td");
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.dataset.level = p.risk_level;
      tag.textContent = LEVELS[p.risk_level].icon + " " + LEVELS[p.risk_level].label;
      tdLevel.appendChild(tag);
      tr.appendChild(tdLevel);
      const tdDist = document.createElement("td");
      tdDist.textContent = String(p.distance_to_zone_px).replace(".", ",");
      tr.appendChild(tdDist);
      el.personsBody.appendChild(tr);
    });
    el.personsNone.hidden = data.persons.length > 0;

    const t = data.metadata.timings;
    el.timings.textContent = "";
    [["Pré-processamento", t.preprocess_ms], ["Inferência", t.inference_ms], ["Pós-processamento", t.postprocess_ms], ["Total", t.total_ms]].forEach(([name, value]) => {
      const div = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = name + ":";
      const dd = document.createElement("dd");
      dd.textContent = String(value).replace(".", ",");
      div.append(dt, dd);
      el.timings.appendChild(div);
    });

    el.jsonOut.textContent = JSON.stringify(data, null, 2);

    const li = document.createElement("li");
    li.textContent = summarize(conf, data) + " (" + analyzedFileName + ")";
    el.history.prepend(li);
    while (el.history.children.length > 6) el.history.lastElementChild.remove();
    el.historyWrap.hidden = false;
  }

  /* --- Inicialização --- */
  async function init() {
    setImageScale(document.documentElement.dataset.imageScale || 75);
    setConf(0.35);
    try {
      const health = await fetch("/health");
      if (!health.ok) throw new Error("HTTP " + health.status);
      const h = await health.json();
      el.serviceStatus.dataset.state = "ok";
      el.serviceStatus.textContent = "Serviço ativo · modelo " + h.model + " · " + h.providers.join(", ");
    } catch (e) {
      el.serviceStatus.dataset.state = "erro";
      el.serviceStatus.textContent = "Serviço indisponível";
      showError("Não foi possível consultar /health. Confira se o serviço está em execução.");
    }
    try {
      const res = await fetch("/zone");
      if (!res.ok) throw new Error("HTTP " + res.status);
      state.defaultZone = await res.json();
      setZone(state.defaultZone);
    } catch (e) {
      state.defaultZone = FALLBACK_ZONE;
      setZone(FALLBACK_ZONE);
      el.status.textContent = "Não foi possível ler GET /zone; usando uma zona de exemplo local.";
    }
    refreshButtons();
  }
  init();
}
