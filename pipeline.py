# -*- coding: utf-8 -*-
"""
pipeline.py — Automação do pipeline TecMente
=============================================
Orquestra todas as etapas do pipeline em sequência via ``subprocess``:

  1. extrator.py                — extração do banco
  2. tratador.py                — tratamento / ofuscação
  3. visualizador.py            — gráficos estáticos (matplotlib)
  4. visualizador_interativo.py — dashboards interativos (Plotly)
  5. previsor.py                — previsão de vendas (scikit-learn) [opcional]
  6. analise_bi.py              — análises avançadas de BI [opcional]

Uso
---
    python pipeline.py                     # roda tudo (sem previsão/BI)
    python pipeline.py --prever            # inclui previsão
    python pipeline.py --bi                # inclui análises de BI
    python pipeline.py --prever --bi       # inclui ambos
    python pipeline.py --dias 7            # extração dos últimos 7 dias
    python pipeline.py --dias 30 --prever  # 30 dias + previsão

Agendamento (Windows Task Scheduler / cron)
--------------------------------------------
Windows (tarefas agendadas):
    schtasks /create /tn "TecMente_Pipeline" /tr "C:\\estudos\\tecmente\\.venv\\Scripts\\python.exe C:\\estudos\\tecmente\\pipeline.py --prever" /sc daily /st 06:00

Linux/macOS (crontab):
    0 6 * * * cd /caminho/tecmente && .venv/bin/python pipeline.py --prever >> pipeline.log 2>&1

Autor: Edson Deveza
Versão: 1.0
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Habilita UTF-8 para todas as operações de I/O do Python neste processo.
# Alinhado com o padrão UTF-8 do projeto e garante consistência com os filhos.
# PYTHONUTF8=1 não funciona em runtime (I/O já inicializado); reconfigure é o
# caminho correto para forçar UTF-8 no processo atual.
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Pasta raiz do projeto — relativa ao script
PASTA_RAIZ: Path = Path(__file__).parent

# Padrão para extrair o nível de log de mensagens dos scripts filhos.
# Formato esperado: "2026-09-15 10:41:07 INFO     Mensagem..."
_PADRAO_LOG = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+"
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+"
)
_NIVEIS_LOG: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def executar_etapa(nome: str, script: str, args: list[str] | None = None) -> bool:
    """Executa um script Python como subprocess e valida o código de saída.

    Args:
        nome: Nome descritivo da etapa (para logs).
        script: Caminho do script .py a executar (absoluto ou relativo à raiz).
        args: Argumentos extras do CLI (opcional).

    Returns:
        ``True`` se a etapa terminou com código 0, ``False`` caso contrário.
    """
    caminho_script = Path(script)
    if not caminho_script.is_absolute():
        caminho_script = PASTA_RAIZ / caminho_script
    cmd: list[str] = [sys.executable, str(caminho_script)]
    if args:
        cmd.extend(args)

    # Força UTF-8 no processo filho (mecanismo oficial Python 3.7+).
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    log.info("─" * 55)
    log.info("▶ Início : %s", nome)
    log.info("  Comando: %s", " ".join(cmd))
    t0 = time.perf_counter()

    try:
        resultado = subprocess.run(
            cmd,
            cwd=str(PASTA_RAIZ),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        duracao = time.perf_counter() - t0

        if resultado.stdout.strip():
            for linha in resultado.stdout.strip().splitlines():
                m = _PADRAO_LOG.match(linha)
                nivel = _NIVEIS_LOG.get(m.group(1), logging.INFO) if m else logging.INFO
                log.log(nivel, "  │ %s", linha)
        if resultado.stderr.strip():
            for linha in resultado.stderr.strip().splitlines():
                m = _PADRAO_LOG.match(linha)
                nivel = _NIVEIS_LOG.get(m.group(1), logging.INFO) if m else logging.INFO
                log.log(nivel, "  │ %s", linha)

        if resultado.returncode == 0:
            log.info("✔ Fim    : %s (%.1fs) — sucesso", nome, duracao)
            return True
        else:
            log.error(
                "✘ Fim    : %s (%.1fs) — falhou (código %d)",
                nome,
                duracao,
                resultado.returncode,
            )
            return False
    except Exception as exc:
        log.error("✘ Erro ao executar %s: %s", nome, exc)
        return False


def main() -> None:
    """Executa o pipeline completo de ponta a ponta."""
    parser = argparse.ArgumentParser(
        description="Pipeline completo TecMente — extração até previsão"
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=3650,
        help="Dias de histórico para extração (padrão: 3650 ≈ todo o histórico "
        "disponível; a janela do gerador é configurável em ANOS_HISTORICO).",
    )
    parser.add_argument(
        "--prever",
        action="store_true",
        help="Incluir o previsor de vendas ao final do pipeline.",
    )
    parser.add_argument(
        "--bi",
        action="store_true",
        help="Incluir as análises avançadas de BI (analise_bi.py).",
    )
    args = parser.parse_args()

    log.info("=" * 55)
    log.info("  TecMente — Pipeline Completo")
    log.info("  Hora de início: %s", time.strftime("%Y-%m-%d %H:%M:%S"))
    log.info("=" * 55)

    etapas: list[tuple[str, str, list[str]]] = [
        ("Extração", "extrator.py", ["--dias", str(args.dias)]),
        ("Tratamento", "tratador.py", []),
        ("Visualização Estática", "visualizador.py", []),
        ("Visualização Interativa", "visualizador_interativo.py", []),
    ]
    if args.prever:
        etapas.append(("Previsão de Vendas", "previsor.py", []))
    if args.bi:
        etapas.append(("Análises de BI", "analise_bi.py", []))

    t_inicio = time.perf_counter()
    falhas: list[str] = []

    for nome, script, cmd_args in etapas:
        ok = executar_etapa(nome, script, cmd_args)
        if not ok:
            falhas.append(nome)
            log.error("Pipeline interrompido em: %s", nome)
            break

    duracao_total = time.perf_counter() - t_inicio
    log.info("=" * 55)

    if falhas:
        log.error(
            "Pipeline finalizado com FALHA em %s (%.1fs total).",
            ", ".join(falhas),
            duracao_total,
        )
        sys.exit(1)
    else:
        log.info(
            "Pipeline finalizado com SUCESSO em %.1fs. Todas as %d etapas concluídas.",
            duracao_total,
            len(etapas),
        )


if __name__ == "__main__":
    main()
