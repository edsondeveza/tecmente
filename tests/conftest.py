"""Fixtures globais dos testes.

Redireciona as pastas de saída de ``analise_bi`` para um diretório
temporário — evita que os testes sobrescrevam os artefatos reais em
``output/analises`` e ``output/graficos``.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _redirecionar_saidas_analise_bi(tmp_path, monkeypatch) -> None:
    saidas = tmp_path / "analises"
    graficos = tmp_path / "graficos"
    saidas.mkdir(parents=True, exist_ok=True)
    graficos.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("analise_bi.CAMINHO_ANALISES", saidas)
    monkeypatch.setattr("analise_bi.CAMINHO_GRAFICOS", graficos)
