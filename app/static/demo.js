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

/** Converte coordenadas de clique (em pixels do elemento) em ponto normalizado de 0 a 1, com 3 casas. */
function clickToNormalized(clientX, clientY, rect) {
  const clamp = (v) => Math.min(1, Math.max(0, v));
  const round = (v) => Math.round(v * 1000) / 1000;
  return [round(clamp((clientX - rect.left) / rect.width)), round(clamp((clientY - rect.top) / rect.height))];
}

if (typeof module !== "undefined") {
  module.exports = { formatConf, parseConf, parseZoneText, zoneToText, httpErrorMessage, summarize, clickToNormalized };
}

/* ---------- Interface (somente no navegador) ---------- */
if (typeof document !== "undefined") {
  const $ = (id) => document.getElementById(id);
  const el = {
    file: $("file"), preview: $("preview"), previewEmpty: $("preview-empty"),
    range: $("conf-range"), number: $("conf-number"), confText: $("conf-text"),
    zoneJson: $("zone-json"), zoneError: $("zone-error"), zoneReset: $("zone-reset"),
    drawToggle: $("draw-toggle"), drawUndo: $("draw-undo"),
    analyze: $("analyze"), status: $("status"), error: $("error"),
    serviceStatus: $("service-status"), resultSection: $("resultado"),
    resultEmpty: $("result-empty"), result: $("result"),
    banner: $("risk-banner"), riskIcon: $("risk-icon"), riskLabel: $("risk-label"), riskMessage: $("risk-message"),
    nTotal: $("n-total"), nGreen: $("n-green"), nYellow: $("n-yellow"), nRed: $("n-red"),
    annotated: $("annotated"), personsBody: $("persons-body"), personsNone: $("persons-none"),
    timings: $("timings"), jsonOut: $("json-out"), historyWrap: $("history-wrap"), history: $("history"),
  };
  const state = { file: null, imageUrl: null, image: null, defaultZone: null, annotatedUrl: null, drawing: false, busy: false };

  function currentConf() { return parseConf(el.number.value); }

  function setConf(value) {
    const v = Number(value);
    el.range.value = String(v);
    el.number.value = String(v);
    el.confText.textContent = formatConf(v);
    document.querySelectorAll(".chip-btn").forEach((b) => b.setAttribute("aria-pressed", String(Math.abs(Number(b.dataset.conf) - v) < 1e-9)));
  }

  function showError(message) {
    el.error.textContent = message;
    el.error.hidden = !message;
  }

  function refreshButtons() {
    const hasImage = !!state.file;
    el.analyze.disabled = !hasImage || state.busy;
    el.drawToggle.disabled = !hasImage;
    el.drawUndo.disabled = !hasImage || !state.drawing;
  }

  /* --- Zona e pré-visualização --- */
  function readZone() {
    const parsed = parseZoneText(el.zoneJson.value);
    el.zoneJson.setAttribute("aria-invalid", parsed.error ? "true" : "false");
    el.zoneError.textContent = parsed.error || "";
    return parsed;
  }

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
    ctx.font = "bold " + Math.round(14 * scale) + "px sans-serif";
    pts.forEach((p, i) => {
      ctx.beginPath();
      ctx.arc(p[0], p[1], 7 * scale, 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();
      ctx.lineWidth = 2 * scale;
      ctx.strokeStyle = "#000532";
      ctx.stroke();
      ctx.fillStyle = "#000532";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(i + 1), p[0], p[1]);
    });
    c.setAttribute("aria-label", "Pré-visualização da imagem enviada, com a zona de risco de " + pts.length + " vértices desenhada em vermelho e numerada");
  }

  function setZone(zone) {
    el.zoneJson.value = zoneToText(zone);
    readZone();
    drawPreview();
  }

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
  document.querySelectorAll(".chip-btn").forEach((b) => b.addEventListener("click", () => setConf(b.dataset.conf)));

  el.zoneJson.addEventListener("input", () => { readZone(); drawPreview(); });
  el.zoneReset.addEventListener("click", () => { setZone(state.defaultZone || FALLBACK_ZONE); el.status.textContent = "Zona padrão restaurada."; });

  el.drawToggle.addEventListener("click", () => {
    state.drawing = !state.drawing;
    el.drawToggle.setAttribute("aria-pressed", String(state.drawing));
    el.preview.classList.toggle("drawing", state.drawing);
    if (state.drawing) {
      // começa um polígono novo, preservando a margem atual
      const parsed = parseZoneText(el.zoneJson.value);
      const margin = parsed.zone && parsed.zone.margin !== undefined ? parsed.zone.margin : FALLBACK_ZONE.margin;
      el.zoneJson.value = zoneToText({ polygon: [], margin }).replace("[\n\n  ]", "[]");
      el.zoneJson.setAttribute("aria-invalid", "true");
      el.zoneError.textContent = "Desenhando: clique na pré-visualização para marcar ao menos 3 vértices.";
      drawPreview();
      el.status.textContent = "Modo de desenho ativo: cada clique na imagem acrescenta um vértice.";
    } else {
      readZone();
      el.status.textContent = "Modo de desenho encerrado.";
    }
    refreshButtons();
  });

  function currentPolygon() {
    try { const d = JSON.parse(el.zoneJson.value); return Array.isArray(d.polygon) ? d : null; } catch (e) { return null; }
  }

  el.preview.addEventListener("click", (ev) => {
    if (!state.drawing) return;
    const zone = currentPolygon() || { polygon: [], margin: FALLBACK_ZONE.margin };
    zone.polygon.push(clickToNormalized(ev.clientX, ev.clientY, el.preview.getBoundingClientRect()));
    el.zoneJson.value = zoneToText(zone);
    const parsed = readZone();
    if (!parsed.error) el.zoneError.textContent = "";
    else el.zoneError.textContent = "Desenhando: " + zone.polygon.length + " vértice(s); faltam " + Math.max(0, 3 - zone.polygon.length) + " para uma zona válida.";
    drawPreview();
  });

  el.drawUndo.addEventListener("click", () => {
    const zone = currentPolygon();
    if (!zone || !zone.polygon.length) return;
    zone.polygon.pop();
    el.zoneJson.value = zoneToText(zone);
    readZone();
    if (zone.polygon.length < 3) el.zoneError.textContent = "Desenhando: " + zone.polygon.length + " vértice(s); faltam " + (3 - zone.polygon.length) + " para uma zona válida.";
    drawPreview();
  });

  /* --- Análise --- */
  async function parseBody(response) {
    const type = response.headers.get("content-type") || "";
    if (type.includes("application/json")) { try { return await response.json(); } catch (e) { return null; } }
    return null;
  }

  async function analyze() {
    showError("");
    if (!state.file) { showError("Escolha uma imagem JPEG ou PNG antes de analisar."); return; }
    const conf = currentConf();
    if (!Number.isFinite(conf) || conf <= 0 || conf >= 1) { showError("O limiar deve ser um número maior que 0 e menor que 1."); el.number.focus(); return; }
    const parsed = readZone();
    if (parsed.error) { showError("Zona inválida. " + parsed.error); el.zoneJson.focus(); return; }

    state.busy = true;
    el.resultSection.setAttribute("aria-busy", "true");
    refreshButtons();
    el.status.textContent = "Analisando… (limiar " + formatConf(conf) + ")";
    const started = performance.now();

    const form = () => {
      const f = new FormData();
      f.append("file", state.file, state.file.name);
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
      renderResult(conf, data, blob);
      const elapsed = Math.round(performance.now() - started);
      el.status.textContent = "Análise concluída em " + elapsed + " ms (JSON e imagem), " + summarize(conf, data) + ".";
    } catch (err) {
      const offline = err instanceof TypeError;
      showError(offline ? "Não foi possível falar com o serviço. Confira se o container (ou o uvicorn) está em execução e se esta página foi aberta a partir dele." : err.message);
      el.status.textContent = "";
    } finally {
      state.busy = false;
      el.resultSection.setAttribute("aria-busy", "false");
      refreshButtons();
    }
  }
  el.analyze.addEventListener("click", analyze);

  function renderResult(conf, data, blob) {
    el.resultEmpty.hidden = true;
    el.result.hidden = false;
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
    el.annotated.alt = "Imagem anotada pelo serviço: " + summarize(conf, data) + ". Zona em vermelho, faixa de atenção em amarelo e caixas rotuladas por nível.";

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
    li.textContent = summarize(conf, data) + " (" + state.file.name + ")";
    el.history.prepend(li);
    while (el.history.children.length > 6) el.history.lastElementChild.remove();
    el.historyWrap.hidden = false;
  }

  /* --- Inicialização --- */
  async function init() {
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
