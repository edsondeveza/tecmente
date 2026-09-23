"""dados.py — Acesso a dados consolidado: pasta tratada, CSV e SQL.

Fonte única para resolução da pasta ``*_tratado`` mais recente e para o
chaveamento entre leitura de CSV (FONTE = "csv") e consulta direta ao banco
(FONTE = "sql"), hoje replicado em visualizador/visualizador_interativo.

FONTE e CAMINHO_BASE são configurações injetáveis: passe ``fonte``/``base``
em ``carregar_dados`` para sobrescrever sem tocar nos módulos globais.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from config import DB_CONFIG, ENCODING

log = logging.getLogger(__name__)

# Chaveamento de fonte: "csv" ou "sql"
FONTE: str = "csv"

# Diretório raiz dos dados — relativo ao projeto
CAMINHO_BASE: Path = Path(__file__).resolve().parent.parent.parent / "data"


def configurar(fonte: str | None = None, base: str | Path | None = None) -> None:
    """Sobrescreve as configurações globais de fonte/pasta de dados.

    Args:
        fonte: "csv" ou "sql". Valida o valor informado.
        base:  Caminho do diretório raiz dos dados (onde ficam as pastas
               YYYY-MM-DD e YYYY-MM-DD_tratado).
    """
    if fonte is not None:
        if fonte.lower() not in {"csv", "sql"}:
            raise ValueError(f"FONTE inválida: '{fonte}'. Use 'csv' ou 'sql'.")
        global FONTE
        FONTE = fonte.lower()
    if base is not None:
        global CAMINHO_BASE
        CAMINHO_BASE = Path(base)


def fonte_atual() -> str:
    """Retorna a fonte ativa (pode ter sido alterada via :func:`configurar`).

    Use quando o valor precisar ser lido em tempo de execução — um import
    ``from tecmente.dados import FONTE`` congela o valor no momento do import.
    """
    return FONTE


def resolver_caminho_dados(base: Path | None = None) -> Path:
    """Retorna a pasta _tratado mais recente dentro do diretório base.

    Args:
        base: Diretório raiz onde ficam as pastas de extração
              (padrão: CAMINHO_BASE).

    Returns:
        Path da pasta "_tratado" mais recente encontrada.

    Raises:
        FileNotFoundError: Se nenhuma pasta "_tratado" for encontrada.
    """
    raiz = base or CAMINHO_BASE
    # Ordem alfabética = cronológica, dado que o formato é ISO 8601.
    pastas = sorted(raiz.glob("*_tratado"), reverse=True)
    if not pastas:
        raise FileNotFoundError(f"Nenhuma pasta '_tratado' encontrada em: {raiz}")
    escolhida = pastas[0]
    log.info("Pasta de dados resolvida: %s", escolhida)
    return escolhida


def carregar_dados(
    nome_csv: str,
    query_sql: str | None = None,
    *,
    fonte: str | None = None,
    base: Path | None = None,
) -> pd.DataFrame:
    """Carrega dados da fonte ativa (parâmetro ``fonte`` ou global FONTE).

    FONTE = "csv": lê o CSV tratado em ``resolver_caminho_dados(base)``.
    FONTE = "sql": executa ``query_sql`` contra o banco MySQL.

    Args:
        nome_csv:  Nome do arquivo CSV tratado (ex.: "vendas_tratado.csv").
        query_sql: Query SQL a executar quando fonte = "sql". Obrigatória
                   nesse modo; ignorada caso contrário.
        fonte:     "csv" ou "sql" — sobrescreve o global FONTE.
        base:      Raiz de dados — sobrescreve o global CAMINHO_BASE.

    Returns:
        DataFrame com os dados carregados.

    Raises:
        ValueError:     Se fonte = "sql" e query_sql não for fornecida,
                        ou fonte inválida.
        FileNotFoundError: Se fonte = "csv" e o arquivo não existir.
    """
    fonte_ativa = (fonte or FONTE).lower()
    if fonte_ativa == "csv":
        pasta_dados = resolver_caminho_dados(base)
        caminho = pasta_dados / nome_csv
        if not caminho.exists():
            raise FileNotFoundError(f"Arquivo não encontrado: {caminho}")
        log.info("Lendo CSV: %s", caminho)
        return pd.read_csv(caminho, sep=",", encoding=ENCODING)

    if fonte_ativa == "sql":
        if not query_sql:
            raise ValueError("query_sql é obrigatória quando fonte = 'sql'.")
        try:
            import mysql.connector  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "mysql-connector-python não instalado. "
                "Execute: poetry add mysql-connector-python"
            ) from exc
        log.info("Consultando banco de dados...")
        conn = mysql.connector.connect(**DB_CONFIG)
        try:
            return pd.read_sql(query_sql, conn)
        finally:
            conn.close()

    raise ValueError(f"FONTE inválida: '{fonte_ativa}'. Use 'csv' ou 'sql'.")
