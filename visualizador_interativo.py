# -*- coding: utf-8 -*-
"""
visualizador_interativo.py — Camada BI interativa da TecMente (Fase 2).

Responsabilidade: geração de dashboards interativos (HTML + Plotly)
a partir dos mesmos dados usados pelo visualizador.py (matplotlib).

Reutiliza a lógica de carregamento de dados do visualizador.py:
    carregar_dados, resolver_caminho_dados, PALETA, FONTE, CAMINHO_BASE

Papel no pipeline:
    DBA      → extrator.py     (extração de dados brutos)
    Analista → tratador.py     (limpeza, normalização, cálculos)
    BI       → visualizador.py          (dashboards estáticos PNG)
    BI       → visualizador_interativo.py (dashboards interativos HTML)

Saída:
    HTML interativos em output/relatorios/ (plotly).

Uso:
    python visualizador_interativo.py

Autor: Edson Deveza
Versão: 1.0 (Fase 2 — Plotly)
"""

from __future__ import annotations

import logging

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from visualizador import (
    CAMINHO_BASE,
    CAMINHO_RELATORIOS,
    FONTE,
    PALETA,
    SEQUENCIA_CORES,
    carregar_dados,
    garantir_diretorios,
    resolver_caminho_dados,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Estilo base
# ---------------------------------------------------------------------------

# Estilo global aplicado a todas as figuras Plotly.
ESTILO = dict(
    template="plotly_white",
    paper_bgcolor=PALETA["fundo"],
    plot_bgcolor="white",
    font=dict(family="sans-serif", color=PALETA["texto"]),
)


def _aplicar_estilo(fig: go.Figure) -> go.Figure:
    """Aplica o estilo base e a grade suave em uma figura Plotly."""
    fig.update_layout(**ESTILO)
    fig.update_xaxes(gridcolor="#E5E8EA")
    fig.update_yaxes(gridcolor="#E5E8EA")
    return fig


def _moeda(milhar: bool = True) -> dict:
    """Formato de tooltip/tick de moeda para eixos."""
    return (
        dict(
            tickprefix="R$ ",
            separatethousands=True,
        )
        if milhar
        else dict(tickprefix="R$ ")
    )


def salvar_html(fig: go.Figure, nome_arquivo: str) -> None:
    """Salva uma figura Plotly em HTML interativo no diretório de relatórios.

    Args:
        fig: Objeto Figure do Plotly.
        nome_arquivo: Nome do arquivo sem extensão (ex.: "d01_lojas").
    """
    caminho = CAMINHO_RELATORIOS / f"{nome_arquivo}.html"
    fig.write_html(caminho, include_plotlyjs="cdn", full_html=True)
    log.info("Dashboard interativo salvo: %s", caminho)


# ---------------------------------------------------------------------------
# Dashboard 01 — Faturamento por loja
# ---------------------------------------------------------------------------


def dashboard_01_interativo() -> None:
    """Pizza (participação %) + barras horizontais (valor absoluto) por loja."""
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql="SELECT * FROM vw_vendas_canal",
    )

    faturamento = (
        df.groupby("loja_nome")["subtotal"]
        .sum()
        .reset_index()
        .sort_values("subtotal", ascending=False)
        .rename(columns={"loja_nome": "loja", "subtotal": "total"})
    )
    total_geral: float = float(faturamento["total"].sum())
    faturamento["pct"] = faturamento["total"] / total_geral * 100

    n_lojas = len(faturamento)
    cores = (SEQUENCIA_CORES * ((n_lojas // len(SEQUENCIA_CORES)) + 1))[:n_lojas]

    fig = make_subplots(
        rows=1,
        cols=2,
        column_widths=[0.45, 0.55],
        specs=[[{"type": "domain"}, {"type": "xy"}]],
        subplot_titles=(
            "Participação no Faturamento (%)",
            "Faturamento Total por Loja (R$)",
        ),
    )

    fig.add_trace(
        go.Pie(
            labels=faturamento["loja"],
            values=faturamento["total"],
            hole=0.0,
            marker=dict(colors=cores),
            textinfo="percent",
            textfont=dict(size=10, color=PALETA["texto"]),
            hovertemplate="%{label}<br>%{percent}<br>R$ %{value:,.0f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            y=faturamento["loja"],
            x=faturamento["total"],
            orientation="h",
            marker=dict(color=cores),
            text=[f"R$ {v:,.0f}" for v in faturamento["total"]],
            textposition="outside",
            hovertemplate="%{y}<br>R$ %{x:,.2f}<extra></extra>",
        ),
        row=1,
        col=2,
    )

    fig.update_layout(
        title="Faturamento por Loja — TecMente",
        height=520,
    )
    fig.update_yaxes(tickfont=dict(size=10), row=1, col=2)
    fig.update_xaxes(**_moeda(), row=1, col=2)

    _aplicar_estilo(fig)
    salvar_html(fig, "d01_faturamento_por_loja")
    log.info(
        "[D01-interativo] Lojas: %d | Total: R$ %s", n_lojas, f"{total_geral:,.0f}"
    )


# ---------------------------------------------------------------------------
# Dashboard 02 — Total por unidade
# ---------------------------------------------------------------------------


def dashboard_02_interativo() -> None:
    """Três painéis de barras horizontais: faturamento, pedidos e ticket médio."""
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql="SELECT * FROM vw_vendas_canal",
    )

    pedidos = (
        df.groupby("loja_nome")["id_pedido"]
        .nunique()
        .reset_index()
        .rename(columns={"loja_nome": "loja", "id_pedido": "pedidos"})
    )
    faturamento = (
        df.groupby("loja_nome")["subtotal"]
        .sum()
        .reset_index()
        .rename(columns={"loja_nome": "loja", "subtotal": "total"})
    )
    resumo = faturamento.merge(pedidos, on="loja")
    resumo["ticket_medio"] = resumo["total"] / resumo["pedidos"]
    resumo = resumo.sort_values("total", ascending=False)

    n_lojas = len(resumo)
    cores = (SEQUENCIA_CORES * ((n_lojas // len(SEQUENCIA_CORES)) + 1))[:n_lojas]

    fig = make_subplots(
        rows=1,
        cols=3,
        column_widths=[0.33, 0.33, 0.34],
        subplot_titles=(
            "Faturamento Total (R$)",
            "Pedidos por Loja",
            "Ticket Médio (R$)",
        ),
    )

    fig.add_trace(
        go.Bar(
            y=resumo["loja"],
            x=resumo["total"],
            orientation="h",
            marker=dict(color=cores),
            text=[f"R$ {v:,.0f}" for v in resumo["total"]],
            textposition="outside",
            hovertemplate="%{y}<br>R$ %{x:,.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            y=resumo["loja"],
            x=resumo["pedidos"],
            orientation="h",
            marker=dict(color=cores),
            text=[f"{v:,.0f}" for v in resumo["pedidos"]],
            textposition="outside",
            hovertemplate="%{y}<br>%{x:,.0f} pedidos<extra></extra>",
        ),
        row=1,
        col=2,
    )

    fig.add_trace(
        go.Bar(
            y=resumo["loja"],
            x=resumo["ticket_medio"],
            orientation="h",
            marker=dict(color=cores),
            text=[f"R$ {v:,.2f}" for v in resumo["ticket_medio"]],
            textposition="outside",
            hovertemplate="%{y}<br>R$ %{x:,.2f}<extra></extra>",
        ),
        row=1,
        col=3,
    )

    fig.update_layout(title="Desempenho por Unidade — TecMente", height=520)
    fig.update_yaxes(tickfont=dict(size=10))
    _aplicar_estilo(fig)
    salvar_html(fig, "d02_total_por_unidade")
    log.info("[D02-interativo] Unidades: %d", n_lojas)


# ---------------------------------------------------------------------------
# Dashboard 03 — Top vendedores por loja
# ---------------------------------------------------------------------------


def dashboard_03_interativo() -> None:
    """Grade 2×3 com o top 5 vendedores por loja em faturamento."""
    df_vendas = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql="SELECT * FROM vw_vendas_canal",
    )
    df_equipe = carregar_dados(
        nome_csv="equipe_lojas_tratado.csv",
        query_sql="SELECT id_funcionario, nome, sobrenome, cargo FROM funcionario",
    )

    df_equipe["vendedor"] = df_equipe["nome"] + " " + df_equipe["sobrenome"]
    df = df_vendas.merge(
        df_equipe[["id_funcionario", "vendedor", "cargo"]],
        on="id_funcionario",
        how="left",
    )

    resumo = df.groupby(["loja_nome", "vendedor"], as_index=False).agg(
        faturamento=("subtotal", "sum"), pedidos=("id_pedido", "nunique")
    )

    lojas: list[str] = sorted(str(x) for x in resumo["loja_nome"].unique())
    top_n = 5

    fig = make_subplots(
        rows=2,
        cols=3,
        subplot_titles=lojas,
        shared_yaxes=False,
    )

    for idx, loja in enumerate(lojas, start=1):
        top = (
            resumo[resumo["loja_nome"] == loja]
            .nlargest(top_n, "faturamento")
            .sort_values("faturamento", ascending=True)
        )
        cores = [PALETA["primaria"]] * len(top)
        if len(top) > 0:
            cores[-1] = PALETA["secundaria"]  # destaca 1º colocado

        fig.add_trace(
            go.Bar(
                y=top["vendedor"],
                x=top["faturamento"],
                orientation="h",
                marker=dict(color=cores),
                text=[f"R$ {v:,.0f}" for v in top["faturamento"]],
                textposition="outside",
                textfont=dict(size=9),
                hovertemplate="%{y}<br>R$ %{x:,.2f}<extra></extra>",
            ),
            row=((idx - 1) // 3) + 1,
            col=((idx - 1) % 3) + 1,
        )

    fig.update_layout(
        title=f"Top {top_n} Vendedores por Loja — TecMente",
        height=820,
        showlegend=False,
    )
    fig.update_xaxes(**_moeda(milhar=False), tickfont=dict(size=9))
    _aplicar_estilo(fig)

    # Oculta subplots vazios quando houver menos lojas que células
    for idx in range(len(lojas) + 1, 7):
        fig.add_annotation(
            text="",
            row=((idx - 1) // 3) + 1,
            col=((idx - 1) % 3) + 1,
        )

    salvar_html(fig, "d03_top_vendedores")
    log.info("[D03-interativo] Lojas: %d", len(lojas))


# ---------------------------------------------------------------------------
# Dashboard 04 — Faturamento mensal
# ---------------------------------------------------------------------------


def dashboard_04_interativo() -> None:
    """Série temporal mensal: bruto + líquido (eixo esq.) e cancelamentos."""
    df_ativas = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql="SELECT * FROM vw_faturamento_mensal",
    )
    df_cancelados = carregar_dados(
        nome_csv="vendas_cancelados.csv",
        query_sql="SELECT * FROM vw_faturamento_mensal",
    )

    bruto = (
        df_ativas.groupby(["ano", "mes"])["subtotal"]
        .sum()
        .reset_index()
        .rename(columns={"subtotal": "bruto"})
    )
    cancelado = (
        df_cancelados.groupby(["ano", "mes"])["subtotal"]
        .sum()
        .reset_index()
        .rename(columns={"subtotal": "cancelado"})
    )
    mensal = bruto.merge(cancelado, on=["ano", "mes"], how="left")
    mensal["cancelado"] = mensal["cancelado"].fillna(0)
    mensal["liquido"] = mensal["bruto"] - mensal["cancelado"]

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

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Eixo esquerdo — faturamento
    fig.add_trace(
        go.Scatter(
            x=mensal["periodo"],
            y=mensal["bruto"],
            mode="lines+markers",
            name="Faturamento Bruto",
            line=dict(color=PALETA["primaria"], width=2.5),
            hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=mensal["periodo"],
            y=mensal["liquido"],
            mode="lines+markers",
            name="Faturamento Líquido",
            line=dict(color=PALETA["secundaria"], width=2, dash="dash"),
            hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
        ),
        secondary_y=False,
    )

    # Eixo direito — cancelamentos
    fig.add_trace(
        go.Bar(
            x=mensal["periodo"],
            y=mensal["cancelado"],
            name="Cancelamentos (R$)",
            marker=dict(color=PALETA["alerta"], opacity=0.35),
            hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title="Faturamento Mensal — TecMente",
        height=560,
        legend=dict(orientation="h", y=1.15),
    )
    fig.update_xaxes(tickangle=-45, tickfont=dict(size=9))
    fig.update_yaxes(**_moeda(), secondary_y=False, title="Faturamento (R$)")
    fig.update_yaxes(
        tickprefix="R$ ",
        secondary_y=True,
        title="Cancelamentos (R$)",
        tickfont=dict(color=PALETA["alerta"]),
    )

    _aplicar_estilo(fig)
    salvar_html(fig, "d04_faturamento_mensal")
    log.info("[D04-interativo] Períodos: %d", len(mensal))


# ---------------------------------------------------------------------------
# Dashboard 05 — Faturamento por categoria (Pareto)
# ---------------------------------------------------------------------------


def dashboard_05_interativo() -> None:
    """Barras por categoria + curva de Pareto acumulada com referência em 80%."""
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql="SELECT * FROM vw_categorias",
    )

    categorias = (
        df.groupby("categoria_pai")["subtotal"]
        .sum()
        .reset_index()
        .rename(columns={"subtotal": "total"})
        .sort_values("total", ascending=False)
    )
    total_geral: float = float(categorias["total"].sum())
    categorias["pct_acum"] = categorias["total"].cumsum() / total_geral * 100

    # Vetorizado: reutiliza pct_acum (mesmo cálculo do old loop iterrows), com
    # semântica estrita <= preservada para manter a regra de negócio do Pareto.
    cores = [
        PALETA["secundaria"] if p <= 80.0 else PALETA["primaria"]
        for p in categorias["pct_acum"]
    ]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=categorias["categoria_pai"],
            y=categorias["total"],
            name="Faturamento",
            marker=dict(color=cores),
            text=[f"R$ {v / 1e6:.1f}M" for v in categorias["total"]],
            textposition="outside",
            textfont=dict(size=9),
            hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=categorias["categoria_pai"],
            y=categorias["pct_acum"],
            mode="lines+markers",
            name="% Acumulado",
            line=dict(color=PALETA["destaque"], width=2),
            hovertemplate="%{x}<br>%{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )

    # Linha de referência (Pareto 80%)
    fig.add_hline(
        y=80,
        line_dash="dash",
        line_color=PALETA["alerta"],
        annotation_text="80% (Pareto)",
        annotation_position="bottom right",
        secondary_y=True,
    )

    fig.update_layout(
        title="Faturamento por Categoria — TecMente (Pareto)",
        height=560,
        legend=dict(orientation="h", y=1.15),
    )
    fig.update_xaxes(tickangle=-35, tickfont=dict(size=9))
    fig.update_yaxes(**_moeda(), secondary_y=False, title="Faturamento (R$)")
    fig.update_yaxes(
        tickformat=".0f", secondary_y=True, title="% Acumulado", range=[0, 110]
    )

    _aplicar_estilo(fig)
    salvar_html(fig, "d05_faturamento_por_categoria")
    log.info("[D05-interativo] Categorias: %d", len(categorias))


# ---------------------------------------------------------------------------
# Dashboard 06 — Top produtos e ticket médio
# ---------------------------------------------------------------------------


def dashboard_06_interativo() -> None:
    """Top 20 produtos: faturamento (barras) e ticket médio (linha)."""
    df = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql="SELECT * FROM vw_ranking_produtos",
    )

    resumo = (
        df.groupby("produto_nome", as_index=False)
        .agg(faturamento=("subtotal", "sum"), pedidos=("id_pedido", "nunique"))
        .nlargest(20, "faturamento")
        .sort_values("faturamento", ascending=False)
    )
    resumo["ticket_medio"] = resumo["faturamento"] / resumo["pedidos"]
    media_ticket: float = float(resumo["ticket_medio"].mean())

    cores = [
        PALETA["secundaria"] if t >= media_ticket else PALETA["primaria"]
        for t in resumo["ticket_medio"]
    ]
    nomes = (resumo["produto_nome"].str[:28] + "…").tolist()

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Bar(
            x=nomes,
            y=resumo["faturamento"],
            name="Faturamento",
            marker=dict(color=cores),
            text=[f"R$ {v / 1e3:.0f}K" for v in resumo["faturamento"]],
            textposition="outside",
            textfont=dict(size=8),
            hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
        ),
        secondary_y=False,
    )

    fig.add_trace(
        go.Scatter(
            x=nomes,
            y=resumo["ticket_medio"],
            mode="lines+markers",
            name="Ticket Médio (R$)",
            marker=dict(symbol="diamond", size=6),
            line=dict(color=PALETA["destaque"], width=2),
            hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>",
        ),
        secondary_y=True,
    )

    fig.add_hline(
        y=media_ticket,
        line_dash="dash",
        line_color=PALETA["neutro"],
        annotation_text=f"Média: R$ {media_ticket:,.0f}",
        annotation_position="bottom right",
        secondary_y=True,
    )

    fig.update_layout(
        title="Top 20 Produtos — Faturamento e Ticket Médio | TecMente",
        height=620,
        legend=dict(orientation="h", y=1.15),
    )
    fig.update_xaxes(tickangle=-40, tickfont=dict(size=8))
    fig.update_yaxes(**_moeda(), secondary_y=False, title="Faturamento (R$)")
    fig.update_yaxes(**_moeda(), secondary_y=True, title="Ticket Médio (R$)")

    _aplicar_estilo(fig)
    salvar_html(fig, "d06_produtos_ticket_medio")
    log.info(
        "[D06-interativo] Produtos: %d | Ticket médio geral: R$ %s",
        len(resumo),
        f"{media_ticket:,.0f}",
    )


# ---------------------------------------------------------------------------
# Dashboard 07 — RFM (scatter + heatmap)
# ---------------------------------------------------------------------------


def dashboard_07_interativo() -> None:
    """Dispersão Recência×Frequência (tamanho=Valor) e heatmap R×F."""
    df_clientes = carregar_dados(
        nome_csv="clientes_tratado.csv",
        query_sql="SELECT * FROM vw_clientes",
    )
    df_vendas = carregar_dados(
        nome_csv="vendas_tratado.csv",
        query_sql="SELECT * FROM vw_vendas_canal",
    )

    df = df_vendas.merge(
        df_clientes[["id_cliente", "nome", "sobrenome", "data_cadastro"]],
        on="id_cliente",
        how="left",
    )
    df["data_pedido"] = pd.to_datetime(df["data_pedido"], errors="coerce")

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

    quartis = rfm[["recencia", "frequencia", "valor"]].quantile([0.25, 0.5, 0.75])
    # Limites por coluna extraídos via dict (chaves float exatas de 0.25/0.5/0.75)
    limites = {col: quartis[col].to_dict() for col in quartis.columns}

    def _score(col: str, invert: bool) -> list[int]:
        def _q(v: float) -> int:
            qs = limites[col]
            if invert:
                return (
                    4
                    if v <= qs[0.25]
                    else 3
                    if v <= qs[0.50]
                    else 2
                    if v <= qs[0.75]
                    else 1
                )
            return (
                1
                if v <= qs[0.25]
                else 2
                if v <= qs[0.50]
                else 3
                if v <= qs[0.75]
                else 4
            )

        return [_q(v) for v in rfm[col]]

    rfm["R"] = _score("recencia", invert=True)
    rfm["F"] = _score("frequencia", invert=False)
    rfm["M"] = _score("valor", invert=False)

    # --- Scatter -----------------------------------------------------------
    fig_scatter = go.Figure(
        go.Scatter(
            x=rfm["recencia"],
            y=rfm["frequencia"],
            mode="markers",
            name="Clientes",
            marker=dict(
                size=rfm["valor"] / 1000,
                color=rfm["M"],
                colorscale="viridis",
                showscale=True,
                colorbar=dict(title="Score M"),
                opacity=0.6,
                line=dict(width=0.4, color="white"),
            ),
            hovertemplate=(
                "Cliente %{customdata}<br>Recência: %{x:.0f}d<br>"
                "Frequência: %{y:.0f}<br>Valor: R$ %{marker.size:,.0f}"
                "k<br>M: %{marker.color}<extra></extra>"
            ),
            customdata=rfm["id_cliente"],
        )
    )
    fig_scatter.update_layout(
        title="RFM — Recência × Frequência (tamanho = Valor)",
        xaxis_title="Recência (dias)",
        yaxis_title="Frequência de Compras",
        height=620,
    )
    _aplicar_estilo(fig_scatter)
    salvar_html(fig_scatter, "d07_rfm_scatter")

    # --- Heatmap -----------------------------------------------------------
    heatmap_data = rfm.pivot_table(
        index="R",
        columns="F",
        values="valor",
        aggfunc="sum",
        fill_value=0,
    ).sort_index(ascending=False)

    fig_heatmap = go.Figure(
        go.Heatmap(
            x=heatmap_data.columns,
            y=heatmap_data.index,
            z=heatmap_data.values,
            colorscale="YlGnBu",
            text=[[f"R$ {v:,.0f}" for v in row] for row in heatmap_data.values],
            texttemplate="%{text}",
            textfont=dict(size=10),
            colorbar=dict(title="Valor Total (R$)"),
            hovertemplate="R=%{y} F=%{x}<br>R$ %{z:,.2f}<extra></extra>",
        )
    )
    fig_heatmap.update_layout(
        title="Heatmap RFM — Valor Total por Segmento R × F",
        xaxis_title="Frequência (1=baixo, 4=alto)",
        yaxis_title="Recência (1=antigo, 4=recente)",
        height=620,
    )
    _aplicar_estilo(fig_heatmap)
    salvar_html(fig_heatmap, "d07_rfm_heatmap")

    log.info("[D07-interativo] Clientes: %d", len(rfm))


# ---------------------------------------------------------------------------
# Orquestrador principal
# ---------------------------------------------------------------------------


def main() -> None:
    """Gera todos os dashboards interativos (Plotly) em HTML."""
    log.info("=" * 60)
    log.info("TecMente — Visualizador Interativo  |  Fonte: %s", FONTE.upper())
    log.info("=" * 60)

    garantir_diretorios()
    # Valida que há dados tratados disponíveis antes de prosseguir
    resolver_caminho_dados(CAMINHO_BASE)

    dashboards = [
        dashboard_01_interativo,
        dashboard_02_interativo,
        dashboard_03_interativo,
        dashboard_04_interativo,
        dashboard_05_interativo,
        dashboard_06_interativo,
        dashboard_07_interativo,
    ]

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
    else:
        log.info("Todos os dashboards interativos concluídos com sucesso.")
    log.info("Dashboards em: %s", CAMINHO_RELATORIOS.resolve())


if __name__ == "__main__":
    main()
