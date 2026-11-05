#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Anderson H. R. Ferreira
# SPDX-License-Identifier: MIT
"""Confere a arquitetura real dos binários dentro de uma imagem Docker, sem executá-la.

Uso: python scripts/verify_arch.py edge-risk-zone:arm64 linux/arm64

Cria um container parado (não executa nada), copia /deps e o interpretador Python e lê o
campo e_machine do cabeçalho ELF (62 = x86-64, 183 = AArch64). Serve para provar que a
imagem gerada em um notebook x86_64 contém de fato binários ARM64 para a Raspberry Pi 5.
"""
from __future__ import annotations

import collections
import glob
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

MACHINES = {62: "x86-64", 183: "AArch64"}


def elf_machine(path: str) -> str | None:
    """Arquitetura de um binário ELF, lida do campo `e_machine` do cabeçalho.

    O campo ocupa 2 bytes, em little-endian, nas posições 18 e 19 (`header[18:20]`). Devolve `None` se o
    arquivo não for ELF (os 4 primeiros bytes devem ser `0x7f` seguido de `ELF`) e "outra" se o código da
    máquina não estiver em `MACHINES`.
    """
    with open(path, "rb") as handle:
        header = handle.read(20)
    if header[:4] != b"\x7fELF":
        return None
    return MACHINES.get(struct.unpack("<H", header[18:20])[0], "outra")


def main(image: str, platform: str) -> int:
    """Confere os binários da imagem para a plataforma pedida. Devolve 0 se todos têm a arquitetura esperada.

    `docker create` apenas monta o container, sem executar nada; só `/deps` e o interpretador são copiados
    para uma pasta temporária e lidos como arquivos. O container é removido ao final, mesmo em caso de erro.
    """
    name = f"verify-arch-{abs(hash((image, platform))) % 10**6}"
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(["docker", "create", "--platform", platform, "--name", name, image],
                           check=True, capture_output=True)
            subprocess.run(["docker", "cp", f"{name}:/deps", f"{tmp}/deps"], check=True, capture_output=True)
            subprocess.run(["docker", "cp", f"{name}:/usr/local/bin/python3.12", f"{tmp}/python"],
                           check=True, capture_output=True)
        finally:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        counts = collections.Counter(
            m for p in glob.glob(f"{tmp}/deps/**/*.so*", recursive=True) if (m := elf_machine(p)))
        python_arch = elf_machine(f"{tmp}/python")
    expected = "AArch64" if platform.endswith("arm64") else "x86-64"
    print(f"{image} ({platform}): python3.12={python_arch}; bibliotecas .so={dict(counts)}")
    ok = python_arch == expected and set(counts) == {expected}
    print("OK: todos os binários são", expected if ok else f"INESPERADO (esperado {expected})")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], sys.argv[2]))
