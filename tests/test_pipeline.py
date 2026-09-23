# -*- coding: utf-8 -*-
"""Testes unitários para o pipeline.py e para a resolução de pastas.

Não requerem banco de dados.

Executar com:
    poetry run pytest tests/test_pipeline.py -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import executar_etapa
from tecmente.dados import resolver_caminho_dados

# =============================================================================
# resolver_caminho_dados (visualizador) — lógica reutilizada pelo pipeline
# =============================================================================


class TestResolverCaminhoDados:
    def test_seleciona_pasta_mais_recente(self, tmp_path: Path) -> None:
        for nome in ["2023-01-01_tratado", "2023-06-15_tratado", "2024-03-30_tratado"]:
            (tmp_path / nome).mkdir()
        escolhida = resolver_caminho_dados(tmp_path)
        assert escolhida == tmp_path / "2024-03-30_tratado"

    def test_ordem_ignora_pastas_sem_padrao(self, tmp_path: Path) -> None:
        (tmp_path / "2023-01-01_tratado").mkdir()
        (tmp_path / "2023-06-15_tratado").mkdir()
        (tmp_path / "qualquer_coisa").mkdir()
        escolhida = resolver_caminho_dados(tmp_path)
        assert escolhida.name == "2023-06-15_tratado"

    def test_pasta_inexistente_lanca_erro(self, tmp_path: Path) -> None:
        # Nome que NÃO casa com o glob "*_tratado" (ex: "sem_tratado" casaria).
        (tmp_path / "apenas_extracoes").mkdir()
        with pytest.raises(FileNotFoundError):
            resolver_caminho_dados(tmp_path)


# =============================================================================
# executar_etapa (pipeline.py) — validação de código de saída
# =============================================================================


class TestExecutarEtapa:
    def test_script_inexistente_retorna_false(self) -> None:
        # subprocess espera só código exato no caminho; usar um arquivo inexistente
        # ainda cai em FileNotFoundError e retorna False (tratado no pipeline).
        assert executar_etapa("Inexistente", "nao_existe.py") is False

    def test_script_ok_retorna_true(self, tmp_path: Path) -> None:
        script = tmp_path / "ok.py"
        script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        assert executar_etapa("OK", str(script)) is True

    def test_script_falha_retorna_false(self, tmp_path: Path) -> None:
        script = tmp_path / "fail.py"
        script.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")
        assert executar_etapa("Falha", str(script)) is False
