// SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
// SPDX-License-Identifier: MIT
// Testes da lógica pura do selo de frescor e dos sliders da zona (sem navegador).
// Executar: node --test tests/demo_logic.test.mjs   (o pytest também chama este arquivo quando há Node)
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const demo = createRequire(import.meta.url)("../app/static/demo.js");
const { analysisKey, canonicalZone, freshnessOf, zoneFromRectPercent, rectPercentFromZone } = demo;

const ZONE = '{"polygon":[[0.3,0.45],[0.98,0.45],[0.98,0.98],[0.3,0.98]],"margin":0.06}';
const ZONE_PRETTY = `{
  "polygon": [
    [0.3, 0.45],
    [0.98, 0.45],
    [0.98, 0.98],
    [0.3, 0.98]
  ],
  "margin": 0.06
}`;

test("a chave ignora espaços e quebras de linha do JSON da zona", () => {
  assert.equal(analysisKey(1, 0.35, ZONE), analysisKey(1, 0.35, ZONE_PRETTY));
});

test("a chave muda ao trocar o arquivo (contador), o limiar, a zona ou a margem", () => {
  const base = analysisKey(1, 0.35, ZONE);
  assert.notEqual(base, analysisKey(2, 0.35, ZONE), "arquivo");
  assert.notEqual(base, analysisKey(1, 0.10, ZONE), "limiar");
  assert.notEqual(base, analysisKey(1, 0.35, ZONE.replace("0.98,0.98]", "0.97,0.98]")), "vértice");
  assert.notEqual(base, analysisKey(1, 0.35, ZONE.replace('"margin":0.06', '"margin":0.07')), "margem");

});

test("zona inválida tem chave própria, estável e diferente da válida", () => {
  const ruim = analysisKey(1, 0.35, '{"polygon":[[0,0],[1,1]]}');
  assert.equal(ruim, analysisKey(1, 0.35, '{"polygon":[[0,0],[1,1]]}'));
  assert.notEqual(ruim, analysisKey(1, 0.35, ZONE));
  assert.match(canonicalZone("não é json"), /^invalida:/);
});

test("selo: sem análise é 'none'; mesma chave é 'fresh'; chave diferente é 'stale'", () => {
  const k = analysisKey(1, 0.35, ZONE);
  assert.equal(freshnessOf(k, null), "none");
  assert.equal(freshnessOf(k, undefined), "none");
  assert.equal(freshnessOf(k, k), "fresh");
  assert.equal(freshnessOf(analysisKey(1, 0.25, ZONE), k), "stale");
});

test("uma nova análise com os parâmetros atuais volta para 'fresh'", () => {
  const antiga = analysisKey(1, 0.35, ZONE);
  const atual = analysisKey(1, 0.10, ZONE);
  assert.equal(freshnessOf(atual, antiga), "stale");
  assert.equal(freshnessOf(atual, atual), "fresh");   // depois de analisar com 0,10
});

test("mudança DURANTE a análise não vira falso 'Atualizado'", () => {
  const chaveCapturadaAoClicar = analysisKey(1, 0.35, ZONE);   // analyze() captura antes de esperar o serviço
  const chaveDepoisDaMudanca = analysisKey(1, 0.50, ZONE);     // o usuário mexeu no limiar durante a espera
  const ultimaAnalisada = chaveCapturadaAoClicar;              // ao concluir, grava a chave CAPTURADA, não a atual
  assert.equal(freshnessOf(chaveDepoisDaMudanca, ultimaAnalisada), "stale");
});

test("os sliders geram exatamente o contrato polygon + margin", () => {
  const rectangle = zoneFromRectPercent(30, 45, 98, 98, 6);
  assert.deepEqual(rectangle, JSON.parse(ZONE));
  assert.deepEqual(rectPercentFromZone(rectangle), { left: 30, top: 45, right: 98, bottom: 98, margin: 6, isRectangle: true });
  assert.equal(zoneFromRectPercent(60, 20, 55, 80, 6), null, "bordas invertidas são recusadas");
});

test("um polígono livre é reconhecido sem fingir que seus vértices são clicáveis", () => {
  const free = { polygon: [[0.1, 0.2], [0.8, 0.1], [0.9, 0.9]], margin: 0.04 };
  assert.deepEqual(rectPercentFromZone(free), { left: 10, top: 10, right: 90, bottom: 90, margin: 4, isRectangle: false });
  assert.notEqual(canonicalZone(JSON.stringify(free)).startsWith("invalida:"), true);
});
