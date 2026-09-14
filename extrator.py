# -*- coding: utf-8 -*-
"""
extrator.py  —  Papel: DBA
==========================
Extração semanal de dados BRUTOS do banco TecMente.

Responsabilidade exclusiva deste script
-----------------------------------------
Conectar ao banco, executar as queries e gravar os dados
exatamente como estão armazenados — sem nenhuma transformação,
cálculo, limpeza ou mascaramento. O dado bruto é entregue
ao analista de dados para tratamento posterior.

Arquivos gerados por execução
------------------------------
extrações/AAAA-MM-DD/
    vendas.csv              — pedidos + itens + canal + loja
    produtos_estoque.csv    — produtos com categoria, fornecedor e estoque
    clientes.csv            — cadastro completo de clientes (dado bruto)
    equipe_lojas.csv        — funcionários, departamentos e lojas
    extracao.log            — log de execução (linhas, tempo, erros)

O que NÃO é responsabilidade deste script
-------------------------------------------
- Mascarar CPF, CNPJ ou e-mail           → tratador.py (analista)
- Calcular margens, subtotais, lucros     → tratador.py (analista)
- Tratar nulos, duplicatas, typos         → tratador.py (analista)
- Renomear colunas ou mudar formatos      → tratador.py (analista)

Uso
---
    # Extração completa (todo o histórico)
    poetry run python extrator.py

    # Extrai apenas os últimos N dias (útil para testes)
    poetry run python extrator.py --dias 7

    # Define pasta de saída personalizada
    poetry run python extrator.py --saida /caminho/para/pasta

Agendamento semanal (Windows — Task Scheduler)
-----------------------------------------------
    Programa  : python
    Argumentos: C:\\caminho\\extrator.py
    Disparar  : Toda segunda-feira às 06:00

Agendamento semanal (Linux/Mac — cron)
---------------------------------------
    0 6 * * 1 /usr/bin/python3 /caminho/extrator.py

Pré-requisitos
--------------
- Banco ``tecmente`` populado via ``gerador_mestre.py``
- Dependência: ``mysql-connector-python``

Autor: Edson Deveza — DBA
Versão: 1.0 (extração pura, sem transformações)
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import mysql.connector

from config import DB_CONFIG, ENCODING

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

# Pasta raiz onde as subpastas de extração serão criadas — relativa ao script.
RAIZ_PROJETO: Path = Path(__file__).parent
PASTA_SAIDA: Path = RAIZ_PROJETO / "data"

# =============================================================================
# CONFIGURAÇÃO DE LOG
# =============================================================================


def configurar_log(pasta: str) -> logging.Logger:
    """Configura logger que escreve simultaneamente no arquivo e no terminal.

    Args:
        pasta: Caminho da pasta onde ``extracao.log`` será criado.

    Returns:
        Instância do logger configurada.
    """
    logger = logging.getLogger("extrator")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(os.path.join(pasta, "extracao.log"), encoding="utf-8")

    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


# =============================================================================
# HELPER — executa query e grava CSV
# =============================================================================


def _executar_e_gravar(
    cur,
    query: str,
    caminho: str,
    logger: logging.Logger,
    nome_arquivo: str,
    params: tuple | None = None,
) -> int:
    """Executa uma query e grava o resultado em CSV sem nenhuma transformação.

    Os dados saem do banco e vão direto para o arquivo — sem filtragem,
    cálculo ou alteração de valores.

    Args:
        cur:           Cursor MySQL ativo.
        query:         SQL a executar.
        caminho:       Caminho completo do arquivo CSV de destino.
        logger:        Logger da execução.
        nome_arquivo:  Nome do arquivo para exibição no log.
        params:        Parâmetros para query parametrizada (opcional).

    Returns:
        Número de linhas escritas (excluindo cabeçalho).
    """
    inicio = time.time()

    try:
        cur.execute(query, params)
        colunas = [d[0] for d in cur.description]
        rows = cur.fetchall()

    except mysql.connector.Error as e:
        logger.error(f"Erro de banco ao executar {nome_arquivo}: {e}")
        return 0

    except Exception as e:
        logger.error(f"Erro inesperado em {nome_arquivo}: {e}")
        return 0

    try:
        with open(caminho, "w", newline="", encoding=ENCODING) as f:
            writer = csv.writer(f)
            writer.writerow(colunas)
            writer.writerows(rows)

    except OSError as e:
        logger.error(f"Erro ao gravar arquivo {nome_arquivo}: {e}")
        return 0

    elapsed = time.time() - inicio
    logger.info(f"  {nome_arquivo:<25} {len(rows):>8,} linhas ({elapsed:.1f}s)")

    return len(rows)


# =============================================================================
# QUERIES — dados brutos, sem cálculos
# =============================================================================


def extrair_vendas(
    cur,
    pasta: str,
    logger: logging.Logger,
    data_inicio: str | None,
) -> int:
    """Extrai pedidos e itens de venda sem nenhuma transformação.

    Cada linha representa um item de pedido com os campos originais
    do banco, incluindo ids, valores e datas sem formatação adicional.

    Args:
        cur:         Cursor MySQL ativo.
        pasta:       Pasta de destino.
        logger:      Logger da execução.
        data_inicio: Filtro de data mínima (``AAAA-MM-DD``) ou ``None``.

    Returns:
        Número de linhas escritas.
    """
    logger.info("Extraindo vendas...")

    if data_inicio:
        filtro = "AND pe.data_pedido >= %s"
        params: tuple | None = (data_inicio,)
    else:
        filtro = ""
        params = None

    query = f"""
        SELECT
            pe.id_pedido,
            pe.id_cliente,
            pe.id_loja,
            pe.id_funcionario,
            pe.data_pedido,
            pe.status,
            pe.canal,
            pe.valor_total,
            pe.desconto,
            pe.obs,
            l.nome          AS loja_nome,
            l.tipo          AS loja_tipo,
            l.cidade        AS loja_cidade,
            l.estado        AS loja_estado,
            pi.id_item,
            pi.id_produto,
            pi.quantidade,
            # Valores efetivos registrados no pedido — o preco_unitario já embute
            # o desconto por volume (7–18% PJ / ±3% PF); custo_unitario é o custo real.
            pi.preco_unitario AS preco_venda,
            pi.custo_unitario AS preco_custo,
            p.sku,
            p.nome         AS produto_nome,
            cat.id_categoria,
            cat.nome        AS categoria_nome,
            cat.nome_pai    AS categoria_pai
        FROM pedido pe
        JOIN pedido_item    pi ON pe.id_pedido     = pi.id_pedido
        JOIN produto        p  ON pi.id_produto    = p.id_produto
        JOIN categoria      cat ON p.id_categoria  = cat.id_categoria
        JOIN loja           l  ON pe.id_loja       = l.id_loja
        WHERE 1=1 {filtro}
        ORDER BY pe.data_pedido, pe.id_pedido, pi.id_item
    """
    return _executar_e_gravar(
        cur,
        query,
        os.path.join(pasta, "vendas.csv"),
        logger,
        "vendas.csv",
        params=params,
    )


def extrair_produtos_estoque(
    cur,
    pasta: str,
    logger: logging.Logger,
) -> int:
    """Extrai produtos com estoque por loja — campos originais do banco.

    Args:
        cur:    Cursor MySQL ativo.
        pasta:  Pasta de destino.
        logger: Logger da execução.

    Returns:
        Número de linhas escritas.
    """
    logger.info("Extraindo produtos e estoque...")

    query = """
        SELECT
            p.id_produto,
            p.sku,
            p.nome,
            p.descricao,
            p.preco_custo,
            p.preco_venda,
            p.ativo,
            cat.id_categoria,
            cat.nome        AS categoria_nome,
            cat.nome_pai    AS categoria_pai,
            f.id_fornecedor,
            f.nome          AS fornecedor_nome,
            f.cnpj          AS fornecedor_cnpj,
            f.cidade        AS fornecedor_cidade,
            f.estado        AS fornecedor_estado,
            l.id_loja,
            l.nome          AS loja_nome,
            l.tipo          AS loja_tipo,
            e.quantidade    AS estoque_qtd,
            e.ultima_atualizacao
        FROM produto p
        JOIN categoria  cat ON p.id_categoria  = cat.id_categoria
        JOIN fornecedor f   ON p.id_fornecedor = f.id_fornecedor
        JOIN estoque    e   ON p.id_produto    = e.id_produto
        JOIN loja       l   ON e.id_loja       = l.id_loja
        ORDER BY cat.nome_pai, cat.nome, p.nome, l.nome
    """
    return _executar_e_gravar(
        cur,
        query,
        os.path.join(pasta, "produtos_estoque.csv"),
        logger,
        "produtos_estoque.csv",
    )


def extrair_clientes(
    cur,
    pasta: str,
    logger: logging.Logger,
) -> int:
    """Extrai cadastro de clientes exatamente como está no banco.

    CPF, CNPJ e e-mail são entregues em texto claro — o mascaramento
    é responsabilidade do tratador.py (analista de dados).

    Args:
        cur:    Cursor MySQL ativo.
        pasta:  Pasta de destino.
        logger: Logger da execução.

    Returns:
        Número de linhas escritas.
    """
    logger.info("Extraindo clientes...")

    query = """
        SELECT
            id_cliente,
            nome,
            sobrenome,
            tipo,
            email,
            telefone,
            cpf_cnpj,
            data_nascimento,
            data_cadastro,
            cidade,
            estado
        FROM cliente
        ORDER BY data_cadastro, id_cliente
    """
    return _executar_e_gravar(
        cur,
        query,
        os.path.join(pasta, "clientes.csv"),
        logger,
        "clientes.csv",
    )


def extrair_equipe_lojas(
    cur,
    pasta: str,
    logger: logging.Logger,
) -> int:
    """Extrai funcionários, departamentos e lojas como estão no banco.

    CPF dos funcionários é entregue em texto claro — mascaramento
    é responsabilidade do tratador.py (analista de dados).

    Args:
        cur:    Cursor MySQL ativo.
        pasta:  Pasta de destino.
        logger: Logger da execução.

    Returns:
        Número de linhas escritas.
    """
    logger.info("Extraindo equipe e lojas...")

    query = """
        SELECT
            f.id_funcionario,
            f.nome,
            f.sobrenome,
            f.cpf,
            f.cargo,
            f.data_admissao,
            f.salario,
            d.id_departamento,
            d.nome          AS departamento_nome,
            l.id_loja,
            l.nome          AS loja_nome,
            l.tipo          AS loja_tipo,
            l.cidade        AS loja_cidade,
            l.estado        AS loja_estado
        FROM funcionario f
        JOIN departamento d ON f.id_departamento = d.id_departamento
        JOIN loja         l ON f.id_loja         = l.id_loja
        ORDER BY l.nome, d.nome, f.nome
    """
    return _executar_e_gravar(
        cur,
        query,
        os.path.join(pasta, "equipe_lojas.csv"),
        logger,
        "equipe_lojas.csv",
    )


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    """
    Orquestra o processo completo de extração de dados brutos.

    Responsabilidades
    ------------------
    - Processar argumentos de linha de comando
    - Criar a pasta de execução (particionada por data)
    - Configurar logs
    - Conectar ao banco de dados
    - Executar extrações de forma independente
    - Gerar resumo final
    - Garantir fechamento seguro da conexão

    Código de saída
    ----------------
    0 → Sucesso
    1 → Execução com erros
    2 → Falha na conexão com o banco
    """

    # ─────────────────────────────────────────────────────────────
    # Argumentos
    # ─────────────────────────────────────────────────────────────
    parser = argparse.ArgumentParser(
        description="Extração semanal de dados brutos - TecMente (DBA)"
    )
    parser.add_argument(
        "--dias",
        type=int,
        default=None,
        help="Extrai apenas os últimos N dias (padrão: histórico completo).",
    )
    parser.add_argument(
        "--saida",
        type=str,
        default=str(PASTA_SAIDA),
        help=f"Pasta raiz de saída (padrão: {PASTA_SAIDA}).",
    )
    args = parser.parse_args()

    # ─────────────────────────────────────────────────────────────
    # Preparação
    # ─────────────────────────────────────────────────────────────
    hoje = datetime.now().strftime("%Y-%m-%d")
    pasta_execucao = os.path.join(args.saida, hoje)
    os.makedirs(pasta_execucao, exist_ok=True)

    logger = configurar_log(pasta_execucao)

    logger.info("=" * 60)
    logger.info("  TecMente - Extração Semanal v1.0 (DBA)")
    logger.info("=" * 60)
    logger.info(f"Pasta de saída : {os.path.abspath(pasta_execucao)}")
    logger.info(f"Banco          : {DB_CONFIG['database']}@{DB_CONFIG['host']}")

    data_inicio = None
    if args.dias:
        data_inicio = (datetime.now() - timedelta(days=args.dias)).strftime("%Y-%m-%d")
        logger.info(f"Período        : últimos {args.dias} dias (desde {data_inicio})")
    else:
        logger.info("Período        : histórico completo")

    logger.info("=" * 60)

    inicio_total = time.time()
    totais: dict[str, int] = {}
    erros: list[str] = []

    # ─────────────────────────────────────────────────────────────
    # Conexão + Execução (um único bloco controlado)
    # ─────────────────────────────────────────────────────────────
    conn = None
    cur = None

    try:
        # Conexão
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor(buffered=True)

        logger.info("Conexão estabelecida.")
        logger.info("-" * 60)

        # Definição das extrações
        extracoes = [
            ("vendas", extrair_vendas, (cur, pasta_execucao, logger, data_inicio)),
            (
                "produtos_estoque",
                extrair_produtos_estoque,
                (cur, pasta_execucao, logger),
            ),
            ("clientes", extrair_clientes, (cur, pasta_execucao, logger)),
            ("equipe_lojas", extrair_equipe_lojas, (cur, pasta_execucao, logger)),
        ]

        # Execução das etapas
        for nome, func, args_func in extracoes:
            try:
                totais[nome] = func(*args_func)
            except Exception:
                logger.exception(f"Erro na etapa: {nome}")
                erros.append(nome)
                totais[nome] = 0

        # ─────────────────────────────────────────────
        # Resumo
        # ─────────────────────────────────────────────
        elapsed_total = time.time() - inicio_total

        logger.info("-" * 60)
        logger.info("RESUMO")
        logger.info("-" * 60)
        logger.info(f"  vendas.csv             : {totais.get('vendas', 0):>8,} linhas")
        logger.info(
            f"  produtos_estoque.csv   : {totais.get('produtos_estoque', 0):>8,} linhas"
        )
        logger.info(
            f"  clientes.csv           : {totais.get('clientes', 0):>8,} linhas"
        )
        logger.info(
            f"  equipe_lojas.csv       : {totais.get('equipe_lojas', 0):>8,} linhas"
        )
        logger.info(f"  Total                  : {sum(totais.values()):>8,} linhas")
        logger.info(f"  Tempo total            : {elapsed_total:.1f}s")
        logger.info(f"  Etapas com erro        : {len(erros)}")

        if erros:
            logger.warning("Extração concluída COM ERROS:")
            for nome in erros:
                logger.warning(f"  Falha na etapa: {nome}")
            sys.exit(1)
        else:
            logger.info("=" * 60)
            logger.info("  Extração concluída com sucesso.")
            logger.info("  Próximo passo: tratador.py")
            logger.info("=" * 60)

    except mysql.connector.Error as e:
        logger.critical(f"Falha na conexão com o banco: {e}")
        sys.exit(2)

    finally:
        # ─────────────────────────────────────────────
        # Fechamento seguro
        # ─────────────────────────────────────────────
        if cur:
            try:
                cur.close()
            except Exception:
                logger.warning("Erro ao fechar cursor")

        if conn and conn.is_connected():
            try:
                conn.close()
            except Exception:
                logger.warning("Erro ao fechar conexão")

        logger.info("Conexão fechada.")


if __name__ == "__main__":
    main()
