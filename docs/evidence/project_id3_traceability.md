# Rastreabilidade: projeto escolhido (ID 3 da matriz)

Este documento confronta o que a matriz de projetos pede para o **ID 3** com o que este repositório entrega,
incluindo o que **não** foi feito. Cada linha aponta para um arquivo, uma rota ou um teste que o avaliador pode abrir.

## Fonte

| Campo | Valor |
|---|---|
| Arquivo | `matriz-projetos-EdgeAI-VisaoComputacional.xlsx` (material do processo seletivo; **não** é redistribuído aqui) |
| Aba | `Projetos Edge AI - Visão Comput` |
| Projeto | Linha 6, **ID 3**: "Monitoramento de Comportamento de Risco em Zonas de Máquinas Pesadas" |
| Campos confrontados | `D6:H6` (Objetivo, Motivação e Relevância, Descrição do Problema, Características do Ambiente, Aplicabilidade) |
| SHA-256 do arquivo | `30d72bd0c3bd2972f3b2c89b654597a68a2b4003d8ad2f5242a2492dc37291e6` |

Os trechos entre aspas abaixo são citações curtas da matriz, usadas apenas para rastreabilidade.

## Situação de cada requisito

Legenda: **Atendido** · **Parcial** · **Adaptado** (escopo ajustado e declarado) · **Não validado** · **Contexto** (citado na matriz, sem requisito técnico).

| # | A matriz pede | O que este repositório faz | Evidência | Situação |
|---:|---|---|---|---|
| 1 | "delimitar virtualmente a zona de risco via configuração de polígono na imagem" | Polígono em coordenadas normalizadas, configurável por arquivo (`ZONE_PATH`, `config/zone.json`), por requisição (campo `zone`) e por cliques em `/demo` | [`app/config.py`](../../app/config.py), `GET /zone`, [`tests/test_geometry.py`](../../tests/test_geometry.py) | **Atendido** |
| 2 | "detectar a presença de pessoas nessa região" | YOLOX-Tiny (COCO) detecta pessoas; o ponto de contato com o piso é testado contra o polígono | [`app/detector.py`](../../app/detector.py), [`app/risk.py`](../../app/risk.py), [`tests/test_risk.py`](../../tests/test_risk.py) | **Atendido**, com um falso negativo documentado em `samples/assembly.jpg` (veja [Limitações](../../README.md#limitações)) |
| 3 | "classificar o risco (zona amarela/vermelha)" | Verde, amarelo (margem como fração da diagonal) e vermelho (dentro da zona); risco geral é o pior entre as pessoas | `classify_person` e `overall_level` em [`app/risk.py`](../../app/risk.py) | **Atendido** |
| 4 | "acionar alertas proporcionais ao nível de perigo" | Alerta informativo: campo `alert` no JSON, cabeçalho `X-Risk-Level`, PNG anotado e tela de `/demo` | `POST /detect`, `POST /detect/image` | **Parcial**: não há acionamento físico (MQTT, GPIO, buzzer) |
| 5 | "em tempo real" e monitoramento contínuo | Uma imagem por requisição; a latência de cada etapa é medida e informada | [`docs/benchmark_notebook.md`](../benchmark_notebook.md), [`docs/benchmark_api_container.json`](../benchmark_api_container.json) | **Parcial** (escopo adaptado e declarado): não há laço de câmera nem confirmação em vários quadros |
| 6 | "comportamentos de risco" | Detecta **presença em uma região**; não interpreta comportamento | README, aviso de escopo e [Limitações](../../README.md#limitações) | **Adaptado** |
| 7 | "Múltiplas pessoas em cena" | Cada pessoa recebe seu próprio nível | [`samples/airplane.jpg`](../../samples/airplane.jpg), [`samples/factory1910.jpg`](../../samples/factory1910.jpg) | **Atendido** |
| 8 | Ambiente: "posição elevada (3-5 metros)", "fumaça ou névoa", "variação de iluminação" | As imagens de exemplo são históricas, em preto e branco; nada foi medido nessas condições | [Limitações](../../README.md#limitações) | **Não validado** |
| 9a | "na Raspberry Pi 5": compatibilidade da imagem | Imagem `linux/arm64` gerada com `buildx`; todos os binários lidos como AArch64 | [`scripts/verify_arch.py`](../../scripts/verify_arch.py), [`docs/evidence/multiarch_build.txt`](multiarch_build.txt) | **Atendido** |
| 9b | "na Raspberry Pi 5": execução e latência | Não houve execução na placa nem em emulação; o intervalo de 140 a 280 ms é **hipótese** | README, [Adaptações para a Raspberry Pi 5](../../README.md#adaptações-para-a-raspberry-pi-5) | **Não validado** |
| 10 | "complemento às barreiras físicas"; "NR-12, NR-17 e ISO 13849" | Aviso explícito: protótipo educacional, não substitui barreiras físicas nem sistemas certificados | README, aviso de escopo | **Contexto**: reconhecido; nenhuma conformidade é reivindicada |

## Por que o ID 3

A escolha busca o melhor equilíbrio entre quatro fatores, e não afirma que os outros projetos fossem impossíveis:

- **Modelo pré-treinado disponível:** "pessoa" é uma das 80 classes do COCO, então o modelo escolhido serve sem treinar de novo.
  O COCO não tem capacete, colete nem luva, de modo que o ID 1 exigiria um modelo ou um conjunto especializado de EPIs.
  O ID 4 (veículos) também seria viável com classes do COCO.
- **Engenharia própria:** o valor do projeto está na regra de risco (polígono, margem, ponto do pé) e na API, que são testáveis.
- **Prazo:** uma imagem por requisição e uma regra geométrica cabem no prazo do teste.
- **Discussão pedagógica:** o tema de segurança expõe a assimetria entre os erros (falso negativo contra falso alarme), que o caso de `assembly` mostra com dados reais.

## O que ficou de fora, em uma frase

Acionamento físico, laço de câmera com confirmação em vários quadros, validação nas condições do ambiente da matriz e execução na Raspberry Pi 5.
