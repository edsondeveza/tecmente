"""tecmente_cli.py — Interface de linha de comando (entry point) do TecMente.

Agrupa os módulos do pipeline sob um único comando instalável:

    tecmente pipeline                        # pipeline completo
    tecmente gerar | extrair | tratar | visualizar | interativo | prever | bi | validar

Opcionais são repassados ao script alvo após o comando, ex.:

    tecmente prever --steps 12
    tecmente visualizar --fonte sql --dados "C:\\dados"
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_PACOTE_ROOT = Path(__file__).resolve().parent
_PROJETO_ROOT = _PACOTE_ROOT.parent.parent

_SCRIPTS: dict[str, str] = {
    "gerar": "gerador_mestre.py",
    "extrair": "extrator.py",
    "tratar": "tratador.py",
    "visualizar": "visualizador.py",
    "interativo": "visualizador_interativo.py",
    "prever": "previsor.py",
    "bi": "analise_bi.py",
    "validar": "validador_coerencia.py",
    "pipeline": "pipeline.py",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tecmente",
        description="Orquestra os módulos do pipeline TecMente.",
    )
    parser.add_argument("comando", choices=sorted(_SCRIPTS), help="Etapa a executar.")
    parser.add_argument(
        "args",
        nargs="*",
        help="Argumentos adicionais repassados ao script alvo.",
    )
    args = parser.parse_args()

    script = _PROJETO_ROOT / _SCRIPTS[args.comando]
    if not script.exists():
        sys.stderr.write(f"Script não encontrado: {script}\n")
        sys.exit(1)

    resultado = subprocess.run([sys.executable, str(script), *args.args])
    sys.exit(resultado.returncode)


if __name__ == "__main__":
    main()
