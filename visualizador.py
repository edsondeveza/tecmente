# -*- coding: utf-8 -*-
"""
visualizador.py — Camada BI da TecMente.

Responsabilidade: geração de gráficos e relatórios visuais a partir dos
dados tratados pelo tratador.py ou diretamente das views analíticas do banco.

Papel no pipeline:
    DBA      → extrator.py     (extração de dados brutos)
    Analista → tratador.py     (limpeza, normalização, cálculos)
    BI       → visualizador.py (visualizações, dashboards, relatórios)

Fontes suportadas (chaveadas por FONTE):
    "csv" → lê os CSVs tratados em CAMINHO_DADOS
    "sql" → consulta as views analíticas do banco via MySQL

Saída (Fase 1 — Matplotlib/Seaborn):
    PNGs salvos em output/graficos/

Saída (Fase 2 — Plotly, futura):
    HTML interativo salvo em output/relatorios/

Uso:
    python visualizador.py

Dependências:
    matplotlib, seaborn, pandas, mysql-connector-python

Autor: Edson
Versão: 1.2.0 — caminho de dados relativo ao script (2026-03-20)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from matplotlib.patches import Patch

# Fonte única de dados (pasta/CSV/SQL) e configurações injetáveis
from tecmente.dados import carregar_dados, configurar, fonte_atual

# ---------------------------------------------------------------------------
# Configuração de logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurações globais
# ---------------------------------------------------------------------------

# Chaveamento de fonte/pasta: injetáveis via dados.configurar()/parâmetros.
# FONTE/CAMINHO_BASE reexportados de tecmente.dados (fonte única).

# Diretórios de saída — relativos ao diretório do script
CAMINHO_GRAFICOS: Path = Path(__file__).parent / "output" / "graficos"
CAMINHO_RELATORIOS: Path = Path(__file__).parent / "output" / "relatorios"

# ---------------------------------------------------------------------------
# Paleta de cores TecMente
# ---------------------------------------------------------------------------
# Primária : azul-petróleo profundo  — tecnologia, confiança
# Secundária: âmbar                  — destaque, métricas positivas
# Apoio     : cinza-chumbo, branco   — neutros para texto e fundo

PALETA: dict[str, str] = {
    "primaria": "#1B3A5C",  # azul-petróleo
    "secundaria": "#E8A020",  # âmbar
    "destaque": "#2E86AB",  # azul-médio (séries adicionais)
    "alerta": "#C0392B",  # vermelho (cancelamentos, queda)
    "neutro": "#5D6D7E",  # cinza-chumbo
    "fundo": "#F4F6F8",  # cinza-claro (background dos gráficos)
    "texto": "#1C2833",  # quase-preto
}

# Sequência de cores para gráficos com múltiplas categorias
SEQUENCIA_CORES: list[str] = [
    PALETA["primaria"],
    PALETA["secundaria"],
    PALETA["destaque"],
    PALETA["neutro"],
    "#7D3C98",  # roxo
    "#117A65",  # verde-escuro
    "#D35400",  # laranja
]

# ---------------------------------------------------------------------------
# Estilo global do Matplotlib
# ---------------------------------------------------------------------------


def configurar_estilo() -> None:
    """Aplica o estilo visual padrão TecMente em todos os gráficos."""
    plt.rcParams.update(
        {
            "figure.facecolor": PALETA["fundo"],
            "axes.facecolor": "white",
            "axes.edgecolor": PALETA["neutro"],
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "axes.titlecolor": PALETA["texto"],
            "axes.labelcolor": PALETA["texto"],
            "xtick.color": PALETA["neutro"],
            "ytick.color": PALETA["neutro"],
            "font.family": "sans-serif",
            "text.color": PALETA["texto"],
            "figure.dpi": 150,
            "axes.grid": True,
            "grid.color": "#E5E8EA",
            "grid.linewidth": 0.7,
        }
    )


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------


def garantir_diretorios() -> None:
    """Cria os diretórios de saída se não existirem."""
    CAMINHO_GRAFICOS.mkdir(parents=True, exist_ok=True)
    CAMINHO_RELATORIOS.mkdir(parents=True, exist_ok=True)
    log.info("Diretórios de saída verificados")


def salvar_figura(fig: plt.Figure, nome_arquivo: str) -> None:  # type: ignore
    """Salva uma figura em PNG no diretório de gráficos.

    Args:
        fig: Objeto Figure do Matplotlib a ser salvo.
        nome_arquivo: Nome do arquivo sem extensão (ex.: "d01_lojas").
    """
    caminho = CAMINHO_GRAFICOS / f"{nome_arquivo}.png"
    fig.savefig(caminho, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    log.info("Gráfico salvo: %s", caminho)


# ---------------------------------------------------------------------------
# Carregamento de dados — delegado a tecmente.dados (single source)
# ---------------------------------------------------------------------------


def dashboards_disponiveis() -> list[str]:
    """Nomes dos dashboards habilitados, na ordem de execução."""
    return [
        "d01_faturamento_por_loja",
        "d02_total_por_unidade",
        "d03_top_vendedores",
        "d04_faturamento_mensal",
        "d05_faturamento_por_categoria",
        "d06_produtos_ticket_medio",
        "d07_rfm",
    ]


# ---------------------------------------------------------------------------
# Dashboard 01 — % de faturamento por loja (Filiais vs CD Online)
# ---------------------------------------------------------------------------


def dashboard_01_faturamento_por_loja() -> None:
    """Gera pizza e barras horizontais com participação de faturamento por loja.

    Gráfico esquerdo:
        Pizza com % de participação por loja.

    Gráfico direito:
        Barras horizontais com valor absoluto (R$),
        ordenadas do maior para o menor.

    Fonte CSV:
        vendas_tratado.csv (colunas: loja_nome, subtotal)

    Fonte SQL:
        vw_vendas_itens (pedidos não cancelados)

    Saída:
        output/graficos/d01_faturamento_por_loja.png
    """
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql=(
            "SELECT loja_nome, subtotal FROM vw_vendas_itens "
            "WHERE status != 'Cancelado'"
        ),
    )

    # ------------------------------------------------------------------ #
    # Agregação
    # ------------------------------------------------------------------ #
    faturamento = (
        df.groupby("loja_nome", as_index=False)["subtotal"]
        .sum()
        .sort_values(by=["subtotal"], ascending=False)  # type: ignore
    )
    faturamento = faturamento.rename(columns={"loja_nome": "loja", "subtotal": "total"})

    total_geral: float = faturamento["total"].sum()
    faturamento["pct"] = faturamento["total"] / total_geral * 100

    n_lojas: int = len(faturamento)

    # Garante quantidade suficiente de cores
    cores: list[str] = (SEQUENCIA_CORES * ((n_lojas // len(SEQUENCIA_CORES)) + 1))[
        :n_lojas
    ]

    # ------------------------------------------------------------------ #
    # Criação da figura
    # ------------------------------------------------------------------ #
    fig, (ax_pizza, ax_barras) = plt.subplots(1, 2, figsize=(16, 7))
    fig.patch.set_facecolor(PALETA["fundo"])

    fig.suptitle(
        "Faturamento por Loja - TecMente",
        fontsize=16,
        fontweight="bold",
        color=PALETA["texto"],
        y=1.02,
    )

    # ------------------------------------------------------------------ #
    # Gráfico de pizza
    # ------------------------------------------------------------------ #
    _, texts, autotexts = ax_pizza.pie(
        faturamento["total"],
        labels=faturamento["loja"],
        colors=cores,
        autopct="%1.1f%%",
        startangle=140,
        pctdistance=0.7,
        labeldistance=1.05,
        wedgeprops={"edgecolor": "white", "linewidth": 1.5},
    )

    for text in texts:
        text.set_fontsize(9)
        text.set_color(PALETA["texto"])

    for autotext in autotexts:
        autotext.set_fontsize(8)
        autotext.set_color("white")
        autotext.set_fontweight("bold")

    ax_pizza.set_title(
        "Participação no Faturamento (%)",
        fontsize=12,
        fontweight="bold",
        color=PALETA["texto"],
        pad=12,
    )

    # ------------------------------------------------------------------ #
    # Gráfico de barras horizontais
    # ------------------------------------------------------------------ #
    barras = ax_barras.barh(
        faturamento["loja"],
        faturamento["total"],
        color=cores,
        edgecolor="white",
        linewidth=0.8,
    )

    for barra, valor in zip(barras, faturamento["total"]):
        ax_barras.text(
            barra.get_width() * 1.01,
            barra.get_y() + barra.get_height() / 2,
            f"R$ {valor:_.0f}".replace("_", "."),
            va="center",
            ha="left",
            fontsize=8,
            color=PALETA["texto"],
        )

    ax_barras.set_title(
        "Faturamento Total por Loja (R$)",
        fontsize=12,
        fontweight="bold",
        color=PALETA["texto"],
        pad=12,
    )

    ax_barras.set_xlabel("Receita (R$)", color=PALETA["neutro"])
    ax_barras.invert_yaxis()

    ax_barras.xaxis.set_major_formatter(
        plt.FuncFormatter(  # type: ignore
            lambda x, _: f"R$ {x / 1_000_000:.1f}M"
        )
    )

    ax_barras.tick_params(axis="y", labelsize=9)

    # Grid mais elegante
    ax_barras.grid(axis="x", linestyle="--", alpha=0.4)
    ax_barras.grid(axis="y", visible=False)

    # Remove bordas desnecessárias
    sns.despine(ax=ax_barras, left=True, top=True, right=True)

    # ------------------------------------------------------------------ #
    # Finalização
    # ------------------------------------------------------------------ #
    plt.tight_layout()
    salvar_figura(fig, "d01_faturamento_por_loja")

    log.info(
        "[D01] Total geral: R$ %s | Lojas: %d",
        f"{total_geral:_.0f}".replace("_", "."),
        n_lojas,
    )


# ---------------------------------------------------------------------------
# Dashboard 02 — Total faturado por unidade
# ---------------------------------------------------------------------------


def dashboard_02_total_por_unidade() -> None:
    """Gera três painéis de barras horizontais com desempenho por unidade.

    Painel esquerdo : faturamento total por loja (R$).
    Painel central  : número de pedidos únicos por loja.
    Painel direito  : ticket médio por loja (R$).

    Fonte CSV : vendas_tratado.csv  (colunas: loja_nome, subtotal, id_pedido)
    Fonte SQL : vw_vendas_itens
    Saída     : output/graficos/d02_total_por_unidade.png
    """
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql=(
            "SELECT loja_nome, subtotal, id_pedido FROM vw_vendas_itens "
            "WHERE status != 'Cancelado'"
        ),
    )

    # --- Agregação ---------------------------------------------------------
    # id_pedido repete por ter múltiplos itens — nunique() conta pedidos reais
    pedidos = (
        df.groupby("loja_nome")["id_pedido"]
        .nunique()
        .reset_index()
        .rename(columns={"loja_nome": "loja", "id_pedido": "pedidos"})
    )
    faturamento = (
        df.groupby(["loja_nome"], as_index=False)["subtotal"]
        .sum()
        .rename(columns={"loja_nome": "loja", "subtotal": "total"})
    )  # type: ignore
    resumo = faturamento.merge(pedidos, on="loja")
    resumo["ticket_medio"] = resumo["total"] / resumo["pedidos"]
    resumo = resumo.sort_values("total", ascending=False)

    n_lojas: int = len(resumo)
    cores: list[str] = (SEQUENCIA_CORES * ((n_lojas // len(SEQUENCIA_CORES)) + 1))[
        :n_lojas
    ]

    # --- Figura: três painéis lado a lado ----------------------------------
    fig, (ax_fat, ax_ped, ax_ticket) = plt.subplots(1, 3, figsize=(20, 7))
    fig.patch.set_facecolor(PALETA["fundo"])
    fig.suptitle(
        "Desempenho por Unidade - TecMente",
        fontsize=16,
        fontweight="bold",
        color=PALETA["texto"],
        y=1.02,
    )

    def _barras_h(
        ax: plt.Axes,  # type: ignore
        valores: pd.Series,
        rotulos: pd.Series,
        titulo: str,
        formatter: plt.FuncFormatter,  # type: ignore
        label_fmt: str,
    ) -> None:
        """Desenha barras horizontais padronizadas num eixo."""
        barras = ax.barh(
            rotulos, valores, color=cores, edgecolor="white", linewidth=0.8
        )
        for barra, valor in zip(barras, valores):
            ax.text(
                barra.get_width() * 1.01,
                barra.get_y() + barra.get_height() / 2,
                label_fmt.format(valor),
                va="center",
                ha="left",
                fontsize=8,
                color=PALETA["texto"],
            )
        ax.set_title(
            titulo, fontsize=11, fontweight="bold", color=PALETA["texto"], pad=10
        )
        ax.invert_yaxis()
        ax.xaxis.set_major_formatter(formatter)
        ax.tick_params(axis="y", labelsize=9)
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.grid(axis="y", visible=False)
        sns.despine(ax=ax, left=True, top=True, right=True)

    _barras_h(
        ax=ax_fat,
        valores=resumo["total"],
        rotulos=resumo["loja"],
        titulo="Faturamento Total (R$)",
        formatter=plt.FuncFormatter(  # pyright: ignore[reportPrivateImportUsage]
            lambda x, _: f"R$ {x / 1_000_000:.1f}M"
        ),
        label_fmt="R$ {:,.0f}",
    )
    _barras_h(
        ax=ax_ped,
        valores=resumo["pedidos"],
        rotulos=resumo["loja"],
        titulo="Pedidos por Loja",
        formatter=plt.FuncFormatter(lambda x, _: f"{x:,.0f}"),  # type: ignore
        label_fmt="{:.0f}",
    )
    _barras_h(
        ax=ax_ticket,
        valores=resumo["ticket_medio"],
        rotulos=resumo["loja"],
        titulo="Ticket Médio (R$)",
        formatter=plt.FuncFormatter(  # pyright: ignore[reportPrivateImportUsage]
            lambda x, _: f"R$ {x:,.0f}"
        ),
        label_fmt="R$ {:.2f}",
    )

    plt.tight_layout()
    salvar_figura(fig, "d02_total_por_unidade")

    log.info(
        "[D02] Unidade: %d | Faturamento Total: R$ %s",
        n_lojas,
        f"{resumo['total'].sum():.0f}".replace("_", "."),
    )


# ---------------------------------------------------------------------------
# Dashboard 03 — Top vendedores por loja
# ---------------------------------------------------------------------------


def dashboard_03_top_vendedores() -> None:
    """Gera grade 2x3 com o top 5 vendedores por loja em faturamento.

    Cada subplot representa uma loja com barras horizontais mostrando
    os 5 funcionários com maior faturamento gerado.

    Fonte CSV : vendas_tratado.csv + equipe_lojas_tratado.csv
                (join por id_funcionario)
    Fonte SQL : vw_vendas_itens + funcionario
    Saída     : output/graficos/d03_top_vendedores.png
    """
    df_vendas = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql=(
            "SELECT id_funcionario, loja_nome, subtotal, id_pedido "
            "FROM vw_vendas_itens WHERE status != 'Cancelado' "
            "AND id_funcionario IS NOT NULL"
        ),
    )
    df_equipe = carregar_dados(
        nome_csv="equipe_lojas_tratado.csv",
        query_sql="SELECT id_funcionario, nome, sobrenome, cargo FROM funcionario",
    )

    # --- Preparo -----------------------------------------------------------
    # Nome completo do vendedor
    df_equipe["vendedor"] = df_equipe["nome"] + " " + df_equipe["sobrenome"]

    # Join: traz nome e cargo para cada linha de venda
    df = df_vendas.merge(
        df_equipe[["id_funcionario", "vendedor", "cargo"]],
        on="id_funcionario",
        how="left",
    )

    # Agrega por loja + vendedor
    resumo = df.groupby(["loja_nome", "vendedor"], as_index=False).agg(
        faturamento=("subtotal", "sum"), pedidos=("id_pedido", "nunique")
    )

    lojas: list[str] = sorted(resumo["loja_nome"].unique())
    n_lojas: int = len(lojas)
    if n_lojas == 0:
        log.warning("[D03] Nenhuma loja com vendedores encontrada. Pulando.")
        return
    top_n: int = 5
    # --- Figura: grade dinâmica (3 colunas; linhas conforme nº de lojas) -----
    n_cols: int = 3
    n_rows: int = (n_lojas + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(20, 6 * n_rows), squeeze=False)
    fig.patch.set_facecolor(PALETA["fundo"])
    fig.suptitle(
        f"Top {top_n} Vendedores por Loja — TecMente",
        fontsize=16,
        fontweight="bold",
        color=PALETA["texto"],
        y=1.02,
    )

    # Achata a grade em lista para iterar com índice
    axes_flat = axes.flatten()

    for idx, loja in enumerate(lojas):
        ax = axes_flat[idx]

        top = (
            resumo[resumo["loja_nome"] == loja]
            .nlargest(top_n, "faturamento")
            # menor no topo → maior no final
            .sort_values("faturamento", ascending=True)
        )

        barras = ax.barh(
            top["vendedor"],
            top["faturamento"],
            color=PALETA["primaria"],
            edgecolor="white",
            linewidth=0.8,
        )

        # Destaca a barra do primeiro colocado
        barras[-1].set_color(PALETA["secundaria"])

        for barra, valor in zip(barras, top["faturamento"]):
            ax.text(
                barra.get_width() * 1.01,
                barra.get_y() + barra.get_height() / 2,
                f"R$ {valor:,.0f}",
                va="center",
                ha="left",
                fontsize=7.5,
                color=PALETA["texto"],
            )

        ax.set_title(loja, fontsize=11, fontweight="bold", color=PALETA["texto"], pad=8)
        ax.xaxis.set_major_formatter(
            plt.FuncFormatter(  # pyright: ignore[reportPrivateImportUsage]
                lambda x, _: f"R$ {x / 1_000:.0f}K"
            )
        )
        ax.tick_params(axis="y", labelsize=8.5)
        ax.grid(axis="x", linestyle="--", alpha=0.4)
        ax.grid(axis="y", visible=False)
        sns.despine(ax=ax, left=True, top=True, right=True)

    # Oculta subplots vazios se n_lojas < n_rows * n_cols
    for idx in range(n_lojas, len(axes_flat)):
        axes_flat[idx].set_visible(False)

    plt.tight_layout()
    salvar_figura(fig, "d03_top_vendedores")

    log.info(
        "[D03] Lojas: %d | Top %d vendedores por loja exibidos.",
        n_lojas,
        top_n,
    )


# ---------------------------------------------------------------------------
# Dashboard 04 — Faturamento mensal
# ---------------------------------------------------------------------------


def dashboard_04_faturamento_mensal() -> None:
    """Gera série temporal com faturamento bruto, líquido e cancelamentos por mês.

    Painel principal (eixo esquerdo):
        Linha azul-petróleo : faturamento bruto mensal (vendas ativas).
        Linha âmbar         : faturamento líquido (bruto - cancelamentos).

    Painel secundário (eixo direito):
        Barras vermelhas    : valor cancelado por mês.

    Fonte CSV : vendas_tratado.csv + vendas_cancelados.csv
                (colunas: ano, mes, subtotal)
    Fonte SQL : vw_vendas_itens (filtrada por status)
    Saída     : output/graficos/d04_faturamento_mensal.png
    """
    df_ativas = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql=(
            "SELECT ano, mes, subtotal FROM vw_vendas_itens "
            "WHERE status != 'Cancelado'"
        ),
    )
    df_cancelados = carregar_dados(
        nome_csv="vendas_cancelados.csv",
        query_sql=(
            "SELECT ano, mes, subtotal FROM vw_vendas_itens "
            "WHERE status = 'Cancelado'"
        ),
    )

    # --- Agregação mensal --------------------------------------------------
    bruto = (
        df_ativas.groupby(["ano", "mes"], as_index=False)["subtotal"]
        .sum()
        .rename(columns={"subtotal": "bruto"})
    )  # type: ignore
    cancelado = (
        df_cancelados.groupby(["ano", "mes"], as_index=False)["subtotal"]
        .sum()
        .rename(columns={"subtotal": "cancelado"})
    )  # type: ignore

    mensal = bruto.merge(cancelado, on=["ano", "mes"], how="left")
    mensal["cancelado"] = mensal["cancelado"].fillna(0)
    mensal["liquido"] = mensal["bruto"] - mensal["cancelado"]

    # Rótulo de período para o eixo X: "Jan/23", "Fev/23" ...
    meses_abrev = [
        "Jan",
        "Fev",
        "Mar",
        "Abr",
        "Mai",
        "Jun",
        "Jul",
        "Ago",
        "Set",
        "Out",
        "Nov",
        "Dez",
    ]
    mensal["periodo"] = mensal.apply(
        lambda r: f"{meses_abrev[int(r['mes']) - 1]}/{str(int(r['ano']))[2:]}",
        axis=1,
    )
    mensal = mensal.sort_values(["ano", "mes"])
    periodos = mensal["periodo"].tolist()
    x = range(len(periodos))

    # --- Figura ------------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(18, 7))
    fig.patch.set_facecolor(PALETA["fundo"])

    # Eixo secundário para cancelamentos
    ax2 = ax1.twinx()

    # Barras de cancelamento (eixo direito — fundo)
    ax2.bar(
        x,
        mensal["cancelado"],
        color=PALETA["alerta"],
        alpha=0.35,
        width=0.6,
        label="Cancelamento (R$)",
    )
    ax2.set_ylabel("Cancelamentos (R$)", color=PALETA["alerta"], fontsize=10)
    ax2.tick_params(axis="y", labelcolor=PALETA["alerta"])
    ax2.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda y, _: f"R$ {y / 1_000:.0f}K")  # type: ignore
    )

    # Linhas de faturamento (eixo esquerdo — frente)
    ax1.plot(
        x,
        mensal["bruto"],
        color=PALETA["primaria"],
        linewidth=2.5,
        marker="o",
        markersize=4,
        label="Faturamento Bruto",
        zorder=3,
    )
    ax1.plot(
        x,
        mensal["liquido"],
        color=PALETA["secundaria"],
        linewidth=2,
        marker="o",
        markersize=4,
        linestyle="--",
        label="Faturamento Líquido",
        zorder=3,
    )

    ax1.set_ylabel("Faturamento (R$)", color=PALETA["texto"], fontsize=10)
    ax1.yaxis.set_major_formatter(
        plt.FuncFormatter(  # type: ignore
            lambda y, _: f"R$ {y / 1_000_000:.1f}M"
        )
    )
    ax1.tick_params(axis="y", labelcolor=PALETA["neutro"])
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(periodos, rotation=45, ha="right", fontsize=8)
    ax1.grid(axis="y", linestyle="--", alpha=0.4)
    ax1.grid(axis="x", visible=False)

    # Legenda unificada dos dois eixos
    linhas1, labels1 = ax1.get_legend_handles_labels()
    linhas2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(
        linhas1 + linhas2,
        labels1 + labels2,
        loc="upper left",
        fontsize=9,
        framealpha=0.8,
    )

    fig.suptitle(
        "Faturamento Mensal — TecMente",
        fontsize=16,
        fontweight="bold",
        color=PALETA["texto"],
        y=1.01,
    )

    sns.despine(ax=ax1, top=True, right=False)

    plt.tight_layout()
    salvar_figura(fig, "d04_faturamento_mensal")

    log.info(
        "[D04] Períodos: %d | Bruto total: R$ %s | Cancelado total: R$ %s",
        len(periodos),
        f"{mensal['bruto'].sum():_.0f}".replace("_", "."),
        f"{mensal['cancelado'].sum():_.0f}".replace("_", "."),
    )


# ---------------------------------------------------------------------------
# Dashboard 05 — Faturamento por categoria de produto
# ---------------------------------------------------------------------------


def dashboard_05_faturamento_por_categoria() -> None:
    """Gera barras de faturamento por categoria pai com curva de Pareto acumulada.

    Painel esquerdo (eixo principal):
        Barras verticais com faturamento por categoria pai, ordenadas
        do maior para o menor.

    Painel direito (eixo secundário):
        Linha de Pareto com % acumulado do faturamento total.
        Linha de referência tracejada em 80% (regra de Pareto).

    Fonte CSV : vendas_tratado.csv  (colunas: categoria_pai, subtotal)
    Fonte SQL : vw_vendas_itens
    Saída     : output/graficos/d05_faturamento_por_categoria.png
    """
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql=(
            "SELECT categoria_pai, subtotal FROM vw_vendas_itens "
            "WHERE status != 'Cancelado'"
        ),
    )

    # --- Agregação por categoria pai ---------------------------------------
    categorias = (
        df.groupby("categoria_pai", as_index=False)["subtotal"]
        .sum()
        .rename(columns={"subtotal": "total"})  # type: ignore
        .sort_values("total", ascending=False)
    )

    total_geral: float = categorias["total"].sum()
    categorias["pct_acum"] = categorias["total"].cumsum() / total_geral * 100

    n: int = len(categorias)
    cores = [PALETA["primaria"]] * n

    # Destaca categorias que juntas chegam a 80% em âmbar
    # Vetorizado: reutiliza pct_acum (mesmo cálculo do old loop iterrows), com
    # semântica estrita <= preservada para manter a regra de negócio do Pareto.
    limite_pareto: float = 80.0
    cores = [
        PALETA["secundaria"] if p <= limite_pareto else PALETA["primaria"]
        for p in categorias["pct_acum"]
    ]

    # --- Figura: eixo duplo ------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(18, 8))
    fig.patch.set_facecolor(PALETA["fundo"])

    ax2 = ax1.twinx()

    x = range(n)

    # Barras de faturamento (eixo esquerdo)
    ax1.bar(
        x,
        categorias["total"],
        color=cores,
        edgecolor="white",
        linewidth=0.8,
        zorder=2,
    )

    # Rótulos nas barras
    for i, (valor, cat) in enumerate(
        zip(categorias["total"], categorias["categoria_pai"])
    ):
        ax1.text(
            i,
            valor * 1.01,
            f"R$ {valor / 1_000_000:.1f}M",
            ha="center",
            va="bottom",
            fontsize=7.5,
            color=PALETA["texto"],
        )

    # Linha de Pareto (eixo direito)
    ax2.plot(
        x,
        categorias["pct_acum"],
        color=PALETA["destaque"],
        linewidth=2,
        marker="o",
        markersize=5,
        zorder=3,
        label="% Acumulado",
    )

    # Linha de referência em 80%
    ax2.axhline(
        limite_pareto,
        color=PALETA["alerta"],
        linestyle="--",
        linewidth=1.2,
        alpha=0.7,
        label="80% (Pareto)",
    )

    # Configurações eixo esquerdo
    ax1.set_ylabel("Faturamento (R$)", color=PALETA["texto"], fontsize=10)
    ax1.yaxis.set_major_formatter(
        plt.FuncFormatter(  # type: ignore
            lambda y, _: f"R$ {y / 1_000_000:.1f}M"
        )
    )
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(
        categorias["categoria_pai"],
        rotation=35,
        ha="right",
        fontsize=8.5,
    )
    ax1.grid(axis="y", linestyle="--", alpha=0.4)
    ax1.grid(axis="x", visible=False)
    ax1.tick_params(axis="y", labelcolor=PALETA["neutro"])

    # Configurações eixo direito
    ax2.set_ylabel("% Acumulado", color=PALETA["destaque"], fontsize=10)
    ax2.set_ylim(0, 110)
    ax2.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda y, _: f"{y:.0f}%")  # type: ignore
    )
    ax2.tick_params(axis="y", labelcolor=PALETA["destaque"])

    # Legenda unificada
    linhas2, labels2 = ax2.get_legend_handles_labels()
    legenda_extra = [
        Patch(color=PALETA["secundaria"], label="Top 80% do faturamento"),
        Patch(color=PALETA["primaria"], label="Demais categorias"),
    ]
    ax1.legend(
        legenda_extra + linhas2,
        [p.get_label() for p in legenda_extra] + labels2,  # type: ignore
        loc="center right",
        fontsize=9,
        framealpha=0.8,
    )

    fig.suptitle(
        "Faturamento por Categoria — TecMente",
        fontsize=16,
        fontweight="bold",
        color=PALETA["texto"],
        y=1.01,
    )

    sns.despine(ax=ax1, top=True, right=False)
    plt.tight_layout()
    salvar_figura(fig, "d05_faturamento_por_categoria")

    log.info(
        "[D05] Categorias: %d | Total: R$ %s",
        n,
        f"{total_geral:_.0f}".replace("_", "."),
    )


# ---------------------------------------------------------------------------
# Dashboard 06 — Representatividade por produto e ticket médio
# ---------------------------------------------------------------------------


def dashboard_06_produtos_ticket_medio() -> None:
    """Gera barras verticais com top 20 produtos por faturamento e ticket médio.

    Eixo esquerdo  : barras verticais com faturamento total por produto.
    Eixo direito   : linha com ticket médio por produto (subtotal / pedidos).

    O destaque em âmbar marca os produtos com ticket médio acima da média geral,
    enquanto o azul-petróleo marca os abaixo da média.

    Fonte CSV : vendas_tratado.csv  (colunas: produto_nome, subtotal, id_pedido)
    Fonte SQL : vw_vendas_itens
    Saída     : output/graficos/d06_produtos_ticket_medio.png
    """
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql=(
            "SELECT produto_nome, subtotal, id_pedido FROM vw_vendas_itens "
            "WHERE status != 'Cancelado'"
        ),
    )

    # --- Agregação top 20 -------------------------------------------------
    resumo = (
        df.groupby("produto_nome", as_index=False)
        .agg(
            faturamento=("subtotal", "sum"),
            pedidos=("id_pedido", "nunique"),
        )
        .nlargest(20, "faturamento")
        .sort_values("faturamento", ascending=False)
    )
    resumo["ticket_medio"] = resumo["faturamento"] / resumo["pedidos"]

    media_ticket: float = resumo["ticket_medio"].mean()

    # Cores das barras: âmbar se ticket acima da média, azul caso contrário
    cores = [
        PALETA["secundaria"] if t >= media_ticket else PALETA["primaria"]
        for t in resumo["ticket_medio"]
    ]

    # Nomes curtos para o eixo X (primeiros 28 chars)
    resumo["nome_curto"] = resumo["produto_nome"].str[:28] + "…"

    n: int = len(resumo)
    x = range(n)

    # --- Figura ------------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(20, 9))
    fig.patch.set_facecolor(PALETA["fundo"])

    ax2 = ax1.twinx()
    ax2.set_ylim(0, resumo["ticket_medio"].max() * 1.15)

    # Barras de faturamento (eixo esquerdo)
    ax1.bar(
        x,
        resumo["faturamento"],
        color=cores,
        edgecolor="white",
        linewidth=0.8,
        zorder=2,
        width=0.6,
    )

    # Rótulos nas barras
    for i, valor in enumerate(resumo["faturamento"]):
        ax1.text(
            i,
            valor * 1.01,
            f"R$ {valor / 1_000:.0f}K",
            ha="center",
            va="bottom",
            fontsize=7,
            color=PALETA["texto"],
            rotation=0,
        )

    # Linha de ticket médio (eixo direito)
    ax2.plot(
        x,
        resumo["ticket_medio"],
        color=PALETA["destaque"],
        linewidth=2,
        marker="D",
        markersize=5,
        zorder=3,
        label="Ticket Médio (R$)",
    )

    # Linha de referência: média geral do ticket
    ax2.axhline(
        media_ticket,
        color=PALETA["neutro"],
        linestyle="--",
        linewidth=1.2,
        alpha=0.7,
        label=f"Média geral: R$ {media_ticket:,.0f}",
    )

    # Configurações eixo esquerdo
    ax1.set_ylabel("Faturamento (R$)", color=PALETA["texto"], fontsize=10)
    ax1.yaxis.set_major_formatter(
        plt.FuncFormatter(  # type: ignore
            lambda y, _: f"R$ {y / 1_000_000:.1f}M"
        )
    )
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(
        resumo["nome_curto"],
        rotation=40,
        ha="right",
        fontsize=7.5,
    )
    ax1.tick_params(axis="y", labelcolor=PALETA["neutro"])
    ax1.grid(axis="y", linestyle="--", alpha=0.4)
    ax1.grid(axis="x", visible=False)

    # Configurações eixo direito
    ax2.set_ylabel("Ticket Médio (R$)", color=PALETA["destaque"], fontsize=10)
    ax2.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda y, _: f"R$ {y:,.0f}")  # type: ignore
    )
    ax2.tick_params(axis="y", labelcolor=PALETA["destaque"])

    # Legenda unificada
    linhas2, labels2 = ax2.get_legend_handles_labels()
    legenda_extra = [
        Patch(color=PALETA["secundaria"], label="Ticket acima da média"),
        Patch(color=PALETA["primaria"], label="Ticket abaixo da média"),
    ]
    ax1.legend(
        legenda_extra + linhas2,
        [p.get_label() for p in legenda_extra] + labels2,  # type: ignore
        loc="upper right",
        fontsize=8.5,
        framealpha=0.8,
    )

    fig.suptitle(
        "Top 20 Produtos — Faturamento e Ticket Médio | TecMente",
        fontsize=15,
        fontweight="bold",
        color=PALETA["texto"],
        y=1.01,
    )

    sns.despine(ax=ax1, top=True, right=False)
    plt.tight_layout()
    salvar_figura(fig, "d06_produtos_ticket_medio")

    log.info(
        "[D06] Top %d produtos | Ticket médio geral: R$ %s",
        n,
        f"{media_ticket:,.0f}",
    )


# ---------------------------------------------------------------------------
# Dashboard 07 — Análise RFM de clientes
# ---------------------------------------------------------------------------


def dashboard_07_rfm() -> None:
    """Gera análise RFM de clientes com scatter e heatmap em arquivos separados.

    Arquivo 1 — d07_rfm_scatter.png:
        Dispersão Recência × Frequência. Tamanho proporcional ao Valor.
        Cor pelo score M (valor) via colormap contínuo.

    Arquivo 2 — d07_rfm_heatmap.png:
        Heatmap com valor total agregado por combinação R × F (quartis).

    Cálculo RFM:
        Recência  : dias desde o último pedido (data_ref = último dia + 1)
        Frequência: pedidos únicos por cliente (nunique)
        Valor     : soma do subtotal de todos os pedidos

    Segmentação por quartis:
        R: 4 = mais recente, 1 = mais antigo
        F: 4 = mais frequente, 1 = menos frequente
        M: 4 = maior valor, 1 = menor valor

    Fonte CSV : clientes_tratado.csv + vendas_tratado.csv (join por id_cliente)
    Fonte SQL : vw_clientes + vw_vendas_itens
    Saída     : output/graficos/d07_rfm_scatter.png
                output/graficos/d07_rfm_heatmap.png
    """
    df_clientes = carregar_dados(
        nome_csv="clientes_tratado.csv",
        query_sql="SELECT * FROM vw_clientes",
    )
    df_vendas = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql=(
            "SELECT id_cliente, id_pedido, data_pedido, subtotal "
            "FROM vw_vendas_itens WHERE status != 'Cancelado'"
        ),
    )

    # --- Merge ------------------------------------------------------------
    df = df_vendas.merge(
        df_clientes[["id_cliente", "nome", "sobrenome", "data_cadastro"]],
        on="id_cliente",
        how="left",
    )
    df["data_pedido"] = pd.to_datetime(df["data_pedido"], errors="coerce")

    # --- Cálculo RFM ------------------------------------------------------
    data_ref = df["data_pedido"].max() + pd.Timedelta(days=1)

    rfm = (
        df.groupby("id_cliente")
        .agg(
            recencia=("data_pedido", lambda x: (data_ref - x.max()).days),
            frequencia=("id_pedido", "nunique"),
            valor=("subtotal", "sum"),
        )
        .reset_index()
    )

    # Scores por quartis — limites extraídos via dict
    quartis = rfm[["recencia", "frequencia", "valor"]].quantile([0.25, 0.5, 0.75])
    q_rec = quartis["recencia"].to_dict()
    q_freq = quartis["frequencia"].to_dict()
    q_val = quartis["valor"].to_dict()

    rfm["R"] = rfm["recencia"].apply(
        lambda x: (
            4
            if x <= q_rec[0.25]
            else 3
            if x <= q_rec[0.50]
            else 2
            if x <= q_rec[0.75]
            else 1
        )
    )
    rfm["F"] = rfm["frequencia"].apply(
        lambda x: (
            1
            if x <= q_freq[0.25]
            else 2
            if x <= q_freq[0.50]
            else 3
            if x <= q_freq[0.75]
            else 4
        )
    )
    rfm["M"] = rfm["valor"].apply(
        lambda x: (
            1
            if x <= q_val[0.25]
            else 2
            if x <= q_val[0.50]
            else 3
            if x <= q_val[0.75]
            else 4
        )
    )

    # --- Figura 1: Scatter ------------------------------------------------
    fig_scatter, ax1 = plt.subplots(figsize=(16, 8))
    fig_scatter.patch.set_facecolor(PALETA["fundo"])

    scatter = ax1.scatter(
        rfm["recencia"],
        rfm["frequencia"],
        s=rfm["valor"] / 1_000,
        c=rfm["M"],
        cmap="viridis",
        alpha=0.6,
        edgecolors="white",
        linewidth=0.4,
        zorder=3,
    )

    cbar = plt.colorbar(scatter, ax=ax1)
    cbar.set_label("Score de Valor (M)", color=PALETA["texto"])

    ax1.set_xlabel("Recência (dias)", fontsize=10, color=PALETA["texto"])
    ax1.set_ylabel("Frequência de Compras", fontsize=10, color=PALETA["texto"])
    ax1.set_title(
        "RFM — Recência × Frequência (tamanho = Valor)",
        fontsize=16,
        fontweight="bold",
        color=PALETA["texto"],
        pad=12,
    )
    ax1.grid(linestyle="--", alpha=0.4)
    sns.despine(ax=ax1, top=True, right=True)

    plt.tight_layout()
    salvar_figura(fig_scatter, "d07_rfm_scatter")

    # --- Figura 2: Heatmap ------------------------------------------------
    heatmap_data = rfm.pivot_table(
        index="R",
        columns="F",
        values="valor",
        aggfunc="sum",
        fill_value=0,
    )

    fig_heatmap, ax2 = plt.subplots(figsize=(10, 7))
    fig_heatmap.patch.set_facecolor(PALETA["fundo"])

    sns.heatmap(
        heatmap_data,
        ax=ax2,
        cmap="YlGnBu",
        annot=True,
        fmt=".0f",
        linewidths=0.5,
        linecolor="white",
        cbar_kws={"label": "Valor Total (R$)"},
    )

    ax2.set_title(
        "Heatmap RFM — Valor Total por Segmento R × F",
        fontsize=14,
        fontweight="bold",
        color=PALETA["texto"],
        pad=12,
    )
    ax2.set_xlabel("Frequência (1=baixo, 4=alto)", fontsize=10, color=PALETA["texto"])
    ax2.set_ylabel("Recência (1=antigo, 4=recente)", fontsize=10, color=PALETA["texto"])

    plt.tight_layout()
    salvar_figura(fig_heatmap, "d07_rfm_heatmap")

    # --- Log --------------------------------------------------------------
    r4f4 = heatmap_data.loc[4, 4] if (4, 4) in heatmap_data.index else 0.0
    log.info(
        "[D07] Clientes: %d | Valor total: R$ %s | R4F4: R$ %s",
        len(rfm),
        f"{rfm['valor'].sum():_.0f}".replace("_", "."),
        f"{r4f4:_.0f}".replace("_", "."),
    )


# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------


def main() -> None:
    """Orquestra a geração de todos os dashboards."""
    parser = argparse.ArgumentParser(description="Visualizador BI — TecMente")
    parser.add_argument(
        "--fonte",
        type=str,
        choices=["csv", "sql"],
        help="Fonte de dados: 'csv' (tratado) ou 'sql' (banco MySQL).",
    )
    parser.add_argument(
        "--dados",
        type=str,
        help="Diretório raiz dos dados (onde ficam as pastas *_tratado).",
    )
    args = parser.parse_args()
    configurar(fonte=args.fonte, base=args.dados)

    log.info("=" * 60)
    log.info("TecMente — Visualizador BI  |  Fonte: %s", fonte_atual().upper())
    log.info("=" * 60)

    configurar_estilo()
    garantir_diretorios()

    mapeamento = {
        "d01_faturamento_por_loja": dashboard_01_faturamento_por_loja,
        "d02_total_por_unidade": dashboard_02_total_por_unidade,
        "d03_top_vendedores": dashboard_03_top_vendedores,
        "d04_faturamento_mensal": dashboard_04_faturamento_mensal,
        "d05_faturamento_por_categoria": dashboard_05_faturamento_por_categoria,
        "d06_produtos_ticket_medio": dashboard_06_produtos_ticket_medio,
        "d07_rfm": dashboard_07_rfm,
    }
    dashboards = [mapeamento[nome] for nome in dashboards_disponiveis()]

    total = len(dashboards)
    erros: list[str] = []

    for i, fn in enumerate(dashboards, start=1):
        log.info("Executando dashboard %d/%d: %s", i, total, fn.__name__)
        try:
            fn()
        except NotImplementedError:
            log.warning("  ↳ Não ainda - pulando.")
        except Exception as exc:  # noqa: BLE001
            log.error("  ↳ Erro em %s: %s", fn.__name__, exc)
            erros.append(fn.__name__)

    log.info("-" * 60)
    if erros:
        log.warning("Concluído com erros em: %s", ",".join(erros))
        sys.exit(1)
    else:
        log.info("Todos os dashboards concluídos com sucesso.")
    log.info("Gráficos em: %s", CAMINHO_GRAFICOS.resolve())


if __name__ == "__main__":
    main()
