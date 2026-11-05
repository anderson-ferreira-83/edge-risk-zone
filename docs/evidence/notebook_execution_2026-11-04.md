# Evidência de execução no notebook — 04/11/2026

Ambiente: notebook x86_64, Docker Desktop/WSL. Execução local, sem serviço externo de inferência.

## Container AMD64

Comando:

```bash
docker compose up --build -d
```

Estado observado:

```text
container=running
health=healthy
read_only=true
user=10001:10001
porta=8000:8000
```

`GET /health`:

```json
{"status":"ok","model":"yolox_tiny.onnx","input_size":416,"providers":["CPUExecutionProvider"],"version":"0.1.0"}
```

Também verificados com HTTP 200: `/zone`, `/demo` e `/docs`. A página `/demo` foi servida com CSP restrita à própria origem e `Cache-Control: no-store`.

## Endpoints obrigatórios

Imagem: `samples/assembly.jpg`, zona padrão.

| Limiar | `POST /detect` | `POST /detect/image` | Medição pontual total |
|---:|---|---|---:|
| 0,35 | 1 pessoa verde; risco geral verde | PNG 1280×1027 | 94,32 ms |
| 0,10 | 4 detecções: 2 verdes, 1 amarela, 1 vermelha; risco geral vermelho | PNG 1280×1027 | 33,18 ms |

Os tempos são uma execução pontual e não substituem o benchmark com aquecimento e percentis. Em 0,10, a caixa vermelha é um falso positivo sobre o equipamento; não é a mulher que está na zona.

## Build multi-arquitetura

Comando:

```bash
bash scripts/build_multiarch.sh
```

Resultado:

```text
linux/amd64 -> linux/amd64
python3.12=x86-64; bibliotecas .so={'x86-64': 53}
OK: todos os binários são x86-64

linux/arm64 -> linux/arm64
python3.12=AArch64; bibliotecas .so={'AArch64': 52}
OK: todos os binários são AArch64
```

Imagens carregadas localmente:

```text
amd64 sha256:0c50851c55605950948eea9c5428b9a09a5d9c56c7dc8f096ff4f72e2d86fbcf
arm64 sha256:4898b134904e4f0035b13ec82b9e24190bcd642e4655de5e2a8abba1ae99869f
```

Limite da evidência: os binários ARM64 foram inspecionados sem executar a imagem. Não houve benchmark em Raspberry Pi 5.
