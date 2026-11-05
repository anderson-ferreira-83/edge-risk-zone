// Testes da lógica pura do selo de frescor e do bloqueio de Analisar (sem navegador).
// Executar: node --test tests/demo_logic.test.mjs   (o pytest também chama este arquivo quando há Node)
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const demo = createRequire(import.meta.url)("../app/static/demo.js");
const { analysisKey, canonicalZone, freshnessOf, analyzeBlockReason } = demo;

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

test("Analisar é bloqueado só com imagem e desenho ligado, e o motivo é um texto", () => {
  assert.equal(analyzeBlockReason({ hasImage: true, drawing: false }), null);
  assert.equal(analyzeBlockReason({ hasImage: false, drawing: true }), null);   // sem imagem o botão já está desabilitado
  const motivo = analyzeBlockReason({ hasImage: true, drawing: true });
  assert.equal(typeof motivo, "string");
  assert.match(motivo, /Desenhar polígono no preview/);
});

test("sair do desenho com zona válida volta a permitir a análise", () => {
  assert.equal(analyzeBlockReason({ hasImage: true, drawing: false }), null);
  assert.notEqual(canonicalZone(ZONE).startsWith("invalida:"), true);
});
