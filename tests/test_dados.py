"""Testes do módulo ``tecmente.dados`` — a fonte única de configuração.

Importante: ``configurar`` muta globais de módulo (``FONTE`` e
``CAMINHO_BASE``). Sem o fixture autouse de restauração, um teste pode vazar
estado e fazer outro depender da ordem de execução.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from tecmente import dados


@pytest.fixture(autouse=True)
def _restaurar_globais() -> None:
    """Restaura FONTE e CAMINHO_BASE após cada teste deste módulo."""
    fonte_original = dados.FONTE
    base_original = dados.CAMINHO_BASE
    yield
    dados.configurar(fonte=fonte_original, base=base_original)


@pytest.fixture
def arvore_dados(tmp_path) -> Path:
    """Cria data/<data>/ e data/<data>_tratado/ com um CSV dentro."""
    raiz = tmp_path / "data"
    (raiz / "2026-09-23_tratado").mkdir(parents=True)
    pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]}).to_csv(
        raiz / "2026-09-23_tratado" / "vendas_tratado.csv", index=False
    )
    return raiz


# =============================================================================
# configuração
# =============================================================================


class TestConfigurar:
    def test_fonte_padrao_e_csv(self) -> None:
        assert dados.FONTE == "csv"
        assert dados.fonte_atual() == "csv"

    def test_normaliza_fonte_para_minusculo(self) -> None:
        dados.configurar(fonte="SQL")
        assert dados.fonte_atual() == "sql"

    def test_fonte_invalida_levanta_valueerror(self) -> None:
        with pytest.raises(ValueError, match="FONTE inválida"):
            dados.configurar(fonte="xlsx")

    def test_none_preserva_valor_atual(self) -> None:
        dados.configurar(fonte="sql")
        dados.configurar(fonte=None, base=None)
        assert dados.fonte_atual() == "sql"

    def test_aceita_path_e_str_em_base(self, tmp_path) -> None:
        dados.configurar(base=tmp_path)
        assert dados.CAMINHO_BASE == Path(tmp_path)
        dados.configurar(base=str(tmp_path))
        assert dados.CAMINHO_BASE == Path(tmp_path)

    def test_import_congela_valor_mas_fonte_atual_le_ativo(self) -> None:
        """Regressão do gotcha do AGENTS.md: `from ... import FONTE` congela
        o valor no import; `fonte_atual()` lê a configuração ativa."""
        from tecmente.dados import FONTE as FONTE_CONGELADO

        dados.configurar(fonte="sql")
        assert FONTE_CONGELADO == "csv"
        assert dados.fonte_atual() == "sql"


# =============================================================================
# resolver_caminho_dados
# =============================================================================


class TestResolverCaminhoDados:
    def test_escolhe_a_pasta_mais_recente(self, tmp_path) -> None:
        for data in ("2026-01-01", "2026-09-23", "2026-03-15"):
            (tmp_path / f"{data}_tratado").mkdir()
        assert dados.resolver_caminho_dados(tmp_path).name == "2026-09-23_tratado"

    def test_ignora_pasta_sem_sufixo_tratado(self, tmp_path) -> None:
        (tmp_path / "2026-09-23").mkdir()
        (tmp_path / "2026-01-01_tratado").mkdir()
        assert dados.resolver_caminho_dados(tmp_path).name == "2026-01-01_tratado"

    def test_sem_nenhuma_pasta_levanta_filenotfound(self, tmp_path) -> None:
        with pytest.raises(FileNotFoundError, match="_tratado"):
            dados.resolver_caminho_dados(tmp_path)

    def test_usa_caminho_base_quando_base_e_none(self) -> None:
        assert dados.resolver_caminho_dados() == dados.resolver_caminho_dados(
            dados.CAMINHO_BASE
        )


# =============================================================================
# carregar_dados — CSV
# =============================================================================


class TestCarregarDadosCsv:
    def test_le_o_csv_da_pasta_mais_recente(self, arvore_dados) -> None:
        df = dados.carregar_dados("vendas_tratado.csv", base=arvore_dados)
        assert len(df) == 2
        assert list(df.columns) == ["a", "b"]

    def test_parametro_fonte_nao_altera_o_global(self, arvore_dados) -> None:
        dados.carregar_dados("vendas_tratado.csv", base=arvore_dados, fonte="csv")
        assert dados.fonte_atual() == "csv"

    def test_arquivo_ausente_levanta_filenotfound(self, arvore_dados) -> None:
        with pytest.raises(FileNotFoundError, match="nao_existe.csv"):
            dados.carregar_dados("nao_existe.csv", base=arvore_dados)

    def test_fonte_invalida_levanta_valueerror(self, arvore_dados) -> None:
        with pytest.raises(ValueError, match="FONTE inválida"):
            dados.carregar_dados(
                "vendas_tratado.csv", base=arvore_dados, fonte="parquet"
            )

    def test_sql_sem_query_levanta_valueerror(self, arvore_dados) -> None:
        """Precisa falhar ANTES de qualquer tentativa de conexão."""
        with pytest.raises(ValueError, match="query_sql é obrigatória"):
            dados.carregar_dados("vendas_tratado.csv", base=arvore_dados, fonte="sql")


# =============================================================================
# carregar_dados — SQL (sem MySQL real)
# =============================================================================


class TestCarregarDadosSql:
    def test_usa_db_config_e_fecha_conexao(self, monkeypatch) -> None:
        """A conexão precisa ser fechada mesmo se read_sql explodir."""
        registradas: dict = {}
        fechada: list[bool] = []

        class FakeConn:
            def close(self):
                fechada.append(True)

        def fake_connect(**kwargs):
            registradas.update(kwargs)
            return FakeConn()

        # A função faz `import mysql.connector` no corpo, que religa o
        # submodule ao pacote. Injetar nos dois pontos evita cair no MySQL real.
        monkeypatch.setitem(
            sys.modules, "mysql.connector", SimpleNamespace(connect=fake_connect)
        )
        import mysql

        monkeypatch.setattr(
            mysql, "connector", sys.modules["mysql.connector"], raising=False
        )
        monkeypatch.setattr(dados, "DB_CONFIG", {"user": "u", "database": "tecmente"})
        monkeypatch.setattr(
            dados.pd, "read_sql", lambda q, conn: pd.DataFrame({"x": [1, 2, 3]})
        )

        df = dados.carregar_dados("x.csv", "SELECT 1", fonte="sql")
        assert len(df) == 3
        assert registradas == {"user": "u", "database": "tecmente"}
        assert fechada == [True], "conexão deveria ser fechada no finally"

    def test_conexao_fecha_mesmo_com_erro(self, monkeypatch) -> None:
        class FakeConn:
            def close(self):
                pass

        monkeypatch.setitem(
            sys.modules,
            "mysql.connector",
            SimpleNamespace(connect=lambda **k: FakeConn()),
        )
        import mysql

        monkeypatch.setattr(
            mysql, "connector", sys.modules["mysql.connector"], raising=False
        )

        def explode(*a, **k):
            raise RuntimeError("tabela sumiu")

        monkeypatch.setattr(dados.pd, "read_sql", explode)
        with pytest.raises(RuntimeError, match="tabela sumiu"):
            dados.carregar_dados("x.csv", "SELECT 1", fonte="sql")
