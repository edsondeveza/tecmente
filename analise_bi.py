# -*- coding: utf-8 -*-
"""
analise_bi.py — Papel: Analista de BI Sênior
=============================================
Módulo de análises avançadas de Business Intelligence a partir dos dados
tratados (``vendas_tratado.csv``, ``clientes_tratado.csv`` e
``produtos_estoque_tratado.csv``).

O que é analisado
------------------
1. Retenção por coorte      — % de clientes de cada mês de aquisição que
                              voltam a comprar nos meses seguintes.
2. LTV por segmento         — lifetime value médio por tipo (PF/PJ) e canal.
3. RFM rotulado             — segmentação RFM (recência, frequência,
                              monetário) com rótulos de marketing.
4. Afinidade de cesta       — produtos que costumam ser comprados juntos.
5. ABC/XYZ de produtos      — importância por receita (ABC) vs. estabilidade
                              de demanda (XYZ), com estratégia por quadrante.
6. Saúde de estoque         — cobertura de dias e risco de ruptura/excesso
                              por produto e loja.
7. Cancelamento por canal   — taxa e receita perdida por canal de venda.

Saída
------
output/analises/coorte_retencao.csv
output/analises/ltv_segmentos.csv
output/analises/rfm_clientes.csv
output/analises/rfm_resumo.csv
output/analises/afinidade_cesta.csv
output/analises/abc_xyz_produtos.csv
output/analises/saude_estoque.csv
output/analises/cancelamento_canal.csv
output/analises/relatorio_analises.txt
output/graficos/bi_*.html

Uso
---
    python analise_bi.py                       # roda todas as análises
    python analise_bi.py --apenas rfm          # só uma análise específica
    python analise_bi.py --apenas coorte,abc   # múltiplas pelo nome

Autor: Edson Deveza — Analista de BI Sênior
Versão: 1.0
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px

from visualizador import CAMINHO_BASE, CAMINHO_GRAFICOS, resolver_caminho_dados

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Pasta de saída das análises — relativa ao script
CAMINHO_ANALISES: Path = Path(__file__).parent / "output" / "analises"

# Status considerados como venda efetiva (os demais são tratados à parte)
STATUS_ATIVO: tuple[str, ...] = ("Concluído", "Enviado", "Processando")


# ---------------------------------------------------------------------------
# Carregamento e utilitários
# ---------------------------------------------------------------------------


def _carregar_csv(nome: str) -> pd.DataFrame:
    """Carrega um CSV tratado, convertendo a data de pedido.

    Args:
        nome: Nome do arquivo dentro da pasta _tratado.

    Returns:
        DataFrame carregado com ``data_pedido`` como datetime64.
    """
    pasta = resolver_caminho_dados(CAMINHO_BASE)
    df = pd.read_csv(pasta / nome, sep=",", encoding="utf-8-sig")
    if "data_pedido" in df.columns:
        df["data_pedido"] = pd.to_datetime(df["data_pedido"])
    return df


def _salvar_csv(df: pd.DataFrame, nome: str) -> None:
    """Grava um DataFrame em UTF-8 com BOM (compatível com Excel)."""
    caminho = CAMINHO_ANALISES / nome
    df.to_csv(caminho, index=False, encoding="utf-8-sig")
    log.info("Arquivo salvo: %s", caminho)


def _pedidos_faturados(vendas: pd.DataFrame) -> pd.DataFrame:
    """Agrega vendas no nível de pedido, preservando o faturamento.

    O CSV de vendas tem uma linha por item; a coluna ``valor_total`` repete
    o valor do pedido em cada linha. Somar ``valor_total`` por linha inflaria
    o faturamento. Este helper deduplica a nível de pedido para que somas de
    ``valor_total`` reflitam o faturamento real de cada pedido.

    Args:
        vendas: DataFrame de vendas tratadas (nível item).

    Returns:
        DataFrame com um registro por pedido e colunas ``valor_total``
        (valor do pedido) e ``subtotal`` (soma dos itens do pedido).
    """
    pedidos = vendas.groupby(
        ["id_pedido", "id_cliente", "canal", "data_pedido", "status"],
        as_index=False,
    ).agg(valor_total=("valor_total", "first"), subtotal=("subtotal", "sum"))
    return pedidos


# ---------------------------------------------------------------------------
# 1. Retenção por coorte
# ---------------------------------------------------------------------------


def coorte_retencao(vendas: pd.DataFrame) -> pd.DataFrame:
    """Calcula a retenção por coorte mensal de aquisição.

    A coorte de um cliente é o mês do seu primeiro pedido. A retenção de um
    mês ``i`` é o % de clientes da coorte que compraram novamente no
    ``i``-ésimo mês após a aquisição (incluindo o mês 0 = aquisição).

    Args:
        vendas: DataFrame de vendas tratadas.

    Returns:
        DataFrame pivô coorte × mês pós-aquisição com % de retenção.
    """
    ativas = vendas[vendas["status"].isin(STATUS_ATIVO)].copy()
    ativas["mes_coorte"] = ativas.groupby("id_cliente")["data_pedido"].transform("min")
    ativas["coorte"] = ativas["mes_coorte"].dt.to_period("M")
    ativas["mes_num"] = ativas["data_pedido"].dt.to_period("M")
    ativas["mes_p"] = (ativas["mes_num"] - ativas["coorte"]).apply(lambda x: x.n)

    linhas = (
        ativas.groupby(["coorte", "mes_p"])["id_cliente"]
        .nunique()
        .rename("clientes")
        .reset_index()
    )
    tamanhos = ativas.groupby("coorte")["id_cliente"].nunique().rename("base")
    linhas = linhas.merge(tamanhos, on="coorte")
    linhas["retencao"] = (linhas["clientes"] / linhas["base"] * 100).round(1)

    pivot = linhas.pivot(index="coorte", columns="mes_p", values="retencao")
    pivot = pivot.sort_index().reindex(sorted(pivot.columns), axis=1)
    pivot = pivot.fillna("").astype(str)
    pivot.index = pivot.index.astype(str)

    _salvar_csv(pivot.reset_index(), "coorte_retencao.csv")

    # Heatmap de retenção
    pct = linhas.pivot(index="coorte", columns="mes_p", values="retencao")
    pct.index = pct.index.astype(str)
    fig = px.imshow(
        pct,
        color_continuous_scale="Blues",
        text_auto=".1f",
        aspect="auto",
        labels={"color": "Retenção (%)"},
        title="Retenção de Clientes por Coorte — TecMente",
    )
    fig.update_layout(
        height=560,
        xaxis_title="Mês pós-aquisição",
        yaxis_title="Coorte (mês de aquisição)",
        template="plotly_white",
    )
    caminho = CAMINHO_GRAFICOS / "bi_coorte_retencao.html"
    fig.write_html(caminho, include_plotlyjs="cdn", full_html=True)
    log.info("Gráfico salvo: %s", caminho)
    log.info("[Coorte] %d coortes analisadas", len(pct))
    return pivot


# ---------------------------------------------------------------------------
# 2. LTV por segmento
# ---------------------------------------------------------------------------


def ltv_segmentos(vendas: pd.DataFrame, clientes: pd.DataFrame) -> pd.DataFrame:
    """Calcula lifetime value e métricas por segmento (tipo × canal).

    Segmento = tipo de cliente (PF/PJ) × canal de venda. O LTV é o
    faturamento líquido acumulado do segmento dividido pelo número de
    clientes, expresso como valor médio por cliente no período observado.

    Args:
        vendas: DataFrame de vendas tratadas.
        clientes: DataFrame de clientes tratados.

    Returns:
        DataFrame agregado por tipo × canal.
    """
    ativas = vendas[vendas["status"].isin(STATUS_ATIVO)].copy()
    seg = _pedidos_faturados(ativas).merge(
        clientes[["id_cliente", "tipo"]], on="id_cliente", how="left"
    )

    agrupado = (
        seg.groupby(["tipo", "canal"], as_index=False)
        .agg(
            clientes=("id_cliente", "nunique"),
            pedidos=("id_pedido", "nunique"),
            receita_liquida=("valor_total", "sum"),
        )
        .sort_values("receita_liquida", ascending=False)
    )
    agrupado["ticket_medio"] = (
        agrupado["receita_liquida"] / agrupado["pedidos"]
    ).round(2)
    agrupado["pedidos_por_cliente"] = (
        agrupado["pedidos"] / agrupado["clientes"]
    ).round(1)
    agrupado["ltv_medio"] = (agrupado["receita_liquida"] / agrupado["clientes"]).round(
        2
    )

    _salvar_csv(agrupado, "ltv_segmentos.csv")
    log.info(
        "[LTV] %d segmentos | maior LTV: %s (%s) = R$ %.2f",
        len(agrupado),
        agrupado.iloc[0]["canal"],
        agrupado.iloc[0]["tipo"],
        agrupado.iloc[0]["ltv_medio"],
    )
    return agrupado


# ---------------------------------------------------------------------------
# 3. RFM rotulado
# ---------------------------------------------------------------------------


def rfm_rotulado(
    vendas: pd.DataFrame, clientes: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Segmenta os clientes pelo modelo RFM com rótulos de marketing.

    As pontuações de 1 a 5 são derivadas por quintis:

    - Recência (R): dias desde o último pedido → quanto menor, melhor.
    - Frequência (F): nº de pedidos ativos → quanto maior, melhor.
    - Monetário (M): soma do valor dos pedidos ativos → quanto maior, melhor.

    Rótulos clássicos: Campeões, Fiéis, Promissores, Novos, Em Risco,
    Perdendo, Inativos.

    Args:
        vendas: DataFrame de vendas tratadas.
        clientes: DataFrame de clientes tratados.

    Returns:
        Tupla (df_rfm, df_resumo) com o detalhamento por cliente e o resumo
        por rótulo.
    """
    ativas = vendas[vendas["status"].isin(STATUS_ATIVO)].copy()
    data_ref = ativas["data_pedido"].max()

    pedidos = _pedidos_faturados(ativas)
    por_cli = pedidos.groupby("id_cliente", as_index=False).agg(
        recencia=("data_pedido", "max"),
        frequencia=("id_pedido", "nunique"),
        monetario=("valor_total", "sum"),
    )
    por_cli["recencia"] = (data_ref - por_cli["recencia"]).dt.days

    def _score(serie: pd.Series) -> pd.Series:
        try:
            return pd.qcut(serie, q=5, labels=False, duplicates="drop") + 1
        except ValueError:
            return pd.Series(3, index=serie.index)

    rfm = por_cli.copy()
    rfm["r_score"] = _score(rfm["recencia"])
    rfm["f_score"] = _score(rfm["frequencia"])
    rfm["m_score"] = _score(rfm["monetario"])
    rfm["rfm_total"] = rfm["r_score"] + rfm["f_score"] + rfm["m_score"]
    # Recência é invertida: quanto menor o score, mais distante é o cliente.
    rfm["r_score"] = 6 - rfm["r_score"]

    condicoes = [
        (rfm["rfm_total"] >= 13) & (rfm["f_score"] >= 4),
        (rfm["rfm_total"] >= 10) & (rfm["f_score"] >= 2),
        (rfm["rfm_total"] >= 10),
        (rfm["rfm_total"] <= 6) & (rfm["r_score"] >= 4),
        (rfm["rfm_total"] <= 6) & (rfm["recencia"] <= 90),
        (rfm["rfm_total"] <= 6),
        (rfm["r_score"] <= 2) & (rfm["f_score"] <= 2),
    ]
    rotulos = [
        "Campeões",
        "Fiéis",
        "Promissores",
        "Novos",
        "Em Risco",
        "Perdendo",
        "Inativos",
    ]
    rfm["rotulo"] = pd.Series(
        np.select(condicoes, rotulos, default="Outros"), index=rfm.index
    )

    rfm = rfm.merge(
        clientes[["id_cliente", "tipo", "estado"]], on="id_cliente", how="left"
    )

    resumo = (
        rfm.groupby("rotulo", as_index=False)
        .agg(
            clientes=("id_cliente", "count"),
            monetario_total=("monetario", "sum"),
        )
        .assign(
            pct_clientes=lambda d: (d["clientes"] / d["clientes"].sum() * 100).round(1)
        )
        .sort_values("clientes", ascending=False)
    )
    resumo["%_monetario"] = (
        resumo["monetario_total"] / resumo["monetario_total"].sum() * 100
    ).round(1)

    _salvar_csv(rfm, "rfm_clientes.csv")
    _salvar_csv(resumo, "rfm_resumo.csv")

    # Scatter F × R colorido por monetário
    fig = px.scatter(
        rfm,
        x="f_score",
        y="r_score",
        color="m_score",
        size="monetario",
        color_continuous_scale="Blues",
        labels={"f_score": "Frequência (score)", "r_score": "Recência (score)"},
        title="Mapa RFM — Posicionamento dos clientes",
    )
    fig.update_layout(template="plotly_white", height=560)
    caminho = CAMINHO_GRAFICOS / "bi_rfm_scatter.html"
    fig.write_html(caminho, include_plotlyjs="cdn", full_html=True)
    log.info("Gráfico salvo: %s", caminho)
    log.info("[RFM] %d clientes classificados em %d rótulos", len(rfm), len(resumo))
    return rfm, resumo


# ---------------------------------------------------------------------------
# 4. Afinidade de cesta
# ---------------------------------------------------------------------------


def afinidade_cesta(vendas: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Identifica pares de produtos com maior co-ocorrência em pedidos.

    Considera apenas pedidos ativos com 2 ou mais produtos e conta quantas
    vezes cada par aparece junto em um mesmo pedido.

    Args:
        vendas: DataFrame de vendas tratadas.
        top_n: Quantos pares retornar (ordenação por co-ocorrências).

    Returns:
        DataFrame com produto_a, produto_b, co_ocorrencias e receita_conjunta.
    """
    ativas = vendas[vendas["status"].isin(STATUS_ATIVO)].copy()
    nomes_prod = ativas[["id_produto", "produto_nome"]].drop_duplicates("id_produto")

    pedidos = ativas.groupby("id_pedido")["id_produto"].apply(set)
    multi = pedidos[pedidos.apply(len) >= 2]

    receita_por_pedido = ativas.groupby("id_pedido")["valor_total"].first().to_dict()
    pares: dict[tuple[int, int], list] = {}

    for id_ped, produtos in multi.items():
        itens = sorted(produtos)
        for i in range(len(itens)):
            for j in range(i + 1, len(itens)):
                chave = (itens[i], itens[j])
                if chave not in pares:
                    pares[chave] = [0, 0.0]
                pares[chave][0] += 1
                pares[chave][1] += receita_por_pedido.get(id_ped, 0.0)

    linhas = [
        {
            "produto_a": nomes_prod.set_index("id_produto").at[a, "produto_nome"],
            "produto_b": nomes_prod.set_index("id_produto").at[b, "produto_nome"],
            "co_ocorrencias": cnt,
            "receita_conjunta": round(rec, 2),
        }
        for (a, b), (cnt, rec) in pares.items()
    ]
    df = pd.DataFrame(linhas).sort_values("co_ocorrencias", ascending=False)
    df = df.head(top_n).reset_index(drop=True)

    _salvar_csv(df, "afinidade_cesta.csv")
    if not df.empty:
        log.info(
            "[Cesta] %d pares | top1: %s + %s (%dx co-ocorrências)",
            len(pares),
            df.iloc[0]["produto_a"],
            df.iloc[0]["produto_b"],
            df.iloc[0]["co_ocorrencias"],
        )
    else:
        log.info("[Cesta] nenhum par encontrado")
    return df


# ---------------------------------------------------------------------------
# 5. ABC / XYZ de produtos
# ---------------------------------------------------------------------------


def abc_xyz(vendas: pd.DataFrame, estoque: pd.DataFrame) -> pd.DataFrame:
    """Classifica produtos por receita (ABC) e estabilidade de demanda (XYZ).

    ABC: A = primeiros 80% da receita acumulada; B = até 95%; C = restante.
    XYZ: X = CV < 0.5 (demanda estável); Y = 0.5–1.0; Z = > 1.0 (irregular).

    Args:
        vendas: DataFrame de vendas tratadas.
        estoque: DataFrame produtos × loja (margem por produto).

    Returns:
        DataFrame com um registro por produto e suas classificações A/B/C
        e X/Y/Z, incluindo uma sugestão de estratégia por quadrante.
    """
    ativas = vendas[vendas["status"].isin(STATUS_ATIVO)].copy()
    ativas["receita"] = ativas["subtotal"]
    ativas["mes"] = ativas["data_pedido"].dt.to_period("M")

    # ABC por receita
    abc = (
        ativas.groupby("id_produto", as_index=False)
        .agg(receita_total=("receita", "sum"))
        .sort_values("receita_total", ascending=False)
        .reset_index(drop=True)
    )
    tot = abc["receita_total"].sum()
    abc["pct_acum"] = abc["receita_total"].cumsum() / tot * 100
    abc["abc"] = abc["pct_acum"].apply(
        lambda p: "A" if p <= 80 else ("B" if p <= 95 else "C")
    )

    # XYZ por CV do giro mensal
    grelha = ativas.pivot_table(
        index="id_produto", columns="mes", values="quantidade", aggfunc="sum"
    ).fillna(0)
    media = grelha.mean(axis=1)
    desvio = grelha.std(axis=1)
    cv = (desvio / media.replace(0, np.nan)).fillna(2.0)
    abc["cv"] = abc["id_produto"].map(cv)
    abc["xyz"] = abc["cv"].apply(
        lambda v: "X" if v < 0.5 else ("Y" if v <= 1.0 else "Z")
    )

    estrategias = {
        ("A", "X"): "Baseline: manter prateleira e abastecimento previsível",
        ("A", "Y"): "Baseline: equilibrar estoque via previsão por grupo",
        ("A", "Z"): "Baseline: estoque de segurança maior, evitar ruptura",
        ("B", "X"): "Eficiência: revisar preço/margem e catálogo",
        ("B", "Y"): "Eficiência: acompanhar sazonalidade e promoções",
        ("B", "Z"): "Mobilidade: itens de impulso, controlar capital parado",
        ("C", "X"): "Mobilidade: rotatividade alta, revisar mix",
        ("C", "Y"): "Retrato: revisar mix e prazo de validade",
        ("C", "Z"): "Retrato: avaliar descontinuação ou pedido sob demanda",
    }
    abc["estrategia"] = abc.apply(
        lambda r: estrategias.get((r["abc"], r["xyz"]), "Revisar categoria"),
        axis=1,
    )

    margem = estoque.groupby("id_produto")["margem_pct"].mean().round(1)
    abc["margem_media"] = abc["id_produto"].map(margem)

    _salvar_csv(abc, "abc_xyz_produtos.csv")

    fig = px.scatter(
        abc,
        x="cv",
        y="receita_total",
        color="abc",
        symbol="xyz",
        hover_name="id_produto",
        labels={"cv": "CV do giro (XYZ)", "receita_total": "Receita total (R$)"},
        title="ABC × XYZ — Priorização de gestão por produto",
    )
    fig.update_layout(template="plotly_white", height=560)
    caminho = CAMINHO_GRAFICOS / "bi_abc_xyz.html"
    fig.write_html(caminho, include_plotlyjs="cdn", full_html=True)
    log.info("Gráfico salvo: %s", caminho)
    log.info(
        "[ABC/XYZ] A=%d B=%d C=%d | X=%d Y=%d Z=%d",
        (abc["abc"] == "A").sum(),
        (abc["abc"] == "B").sum(),
        (abc["abc"] == "C").sum(),
        (abc["xyz"] == "X").sum(),
        (abc["xyz"] == "Y").sum(),
        (abc["xyz"] == "Z").sum(),
    )
    return abc


# ---------------------------------------------------------------------------
# 6. Saúde de estoque
# ---------------------------------------------------------------------------


def saude_estoque(estoque: pd.DataFrame, vendas: pd.DataFrame) -> pd.DataFrame:
    """Calcula cobertura de estoque e alertas de ruptura/excesso.

    Usa o estoque total da rede (``estoque_total_rede``) contra o giro médio
    diário de cada produto. Produtos sem estoque suficiente para o giro são
    sinalizados como ruptura; os com cobertura muito acima da mediana, como
    excesso de capital parado.

    Args:
        estoque: DataFrame produtos × loja (com estoque_total_rede).
        vendas: DataFrame de vendas tratadas.

    Returns:
        DataFrame com um registro por produto e seu status de cobertura.
    """
    ativas = vendas[vendas["status"].isin(STATUS_ATIVO)].copy()
    n_dias = max((ativas["data_pedido"].max() - ativas["data_pedido"].min()).days, 1)

    giro = ativas.groupby("id_produto", as_index=False).agg(
        quantidade_vendida=("quantidade", "sum")
    )
    resumo_estoque = estoque.groupby("id_produto", as_index=False).agg(
        estoque_total=("estoque_total_rede", "first"),
        preco_venda=("preco_venda", "first"),
        lojas_ativas=("id_loja", "nunique"),
    )
    final = resumo_estoque.merge(giro, on="id_produto", how="left")
    final["quantidade_vendida"] = final["quantidade_vendida"].fillna(0)
    final["giro_diario"] = final["quantidade_vendida"] / n_dias
    final["cobertura_dias"] = (
        final["estoque_total"] / final["giro_diario"].replace(0, np.nan)
    ).round(1)

    mediana = final["cobertura_dias"].median(skipna=True)
    final["alerta"] = np.select(
        [
            final["giro_diario"] >= final["estoque_total"],
            final["cobertura_dias"] > mediana * 3,
        ],
        ["RISCO DE RUPTURA", "EXCESSO DE CAPITAL"],
        default="SAUDÁVEL",
    )

    _salvar_csv(final, "saude_estoque.csv")
    log.info(
        "[Estoque] saudável=%d | ruptura=%d | excesso=%d",
        (final["alerta"] == "SAUDÁVEL").sum(),
        (final["alerta"] == "RISCO DE RUPTURA").sum(),
        (final["alerta"] == "EXCESSO DE CAPITAL").sum(),
    )
    return final


# ---------------------------------------------------------------------------
# 7. Cancelamento por canal
# ---------------------------------------------------------------------------


def cancelamento_canal(vendas: pd.DataFrame) -> pd.DataFrame:
    """Analisa taxa de cancelamento e receita perdida por canal.

    Os pedidos cancelados são extraídos para um arquivo separado
    (``vendas_cancelados.csv``) pelo tratador; quando presente, ele é
    combinado às vendas ativas para calcular a taxa por canal.

    Args:
        vendas: DataFrame de vendas tratadas ativas (nível item).

    Returns:
        DataFrame por canal com pedidos, cancelamentos, taxa e receita perdida.
    """
    ativas_ped = _pedidos_faturados(vendas)
    try:
        cancelados = _carregar_csv("vendas_cancelados.csv")
        canc_ped = _pedidos_faturados(cancelados)
    except FileNotFoundError:
        log.warning(
            "vendas_cancelados.csv não encontrado; usando cancelados de "
            "vendas_tratado.csv se houver."
        )
        canc_ped = _pedidos_faturados(vendas[vendas["status"] == "Cancelado"])

    por_canal = ativas_ped.groupby("canal", as_index=False).agg(
        pedidos=("id_pedido", "nunique"),
        receita_total=("valor_total", "sum"),
    )
    canc = canc_ped.groupby("canal", as_index=False).agg(
        cancelados=("id_pedido", "nunique"),
        receita_perdida=("valor_total", "sum"),
    )
    final = por_canal.merge(canc, on="canal", how="left")
    final[["cancelados", "receita_perdida"]] = final[
        ["cancelados", "receita_perdida"]
    ].fillna(0)
    final["taxa_cancelamento"] = (
        final["cancelados"] / (final["pedidos"] + final["cancelados"]) * 100
    ).round(2)
    final["%_receita_perdida"] = (
        final["receita_perdida"]
        / (final["receita_total"] + final["receita_perdida"]).replace(0, np.nan)
        * 100
    ).round(2)
    final = final.sort_values("taxa_cancelamento", ascending=False)

    _salvar_csv(final, "cancelamento_canal.csv")

    fig = px.bar(
        final,
        x="canal",
        y="taxa_cancelamento",
        color="taxa_cancelamento",
        text="taxa_cancelamento",
        color_continuous_scale="Reds",
        labels={"taxa_cancelamento": "Taxa de cancelamento (%)"},
        title="Cancelamento por Canal — TecMente",
    )
    fig.update_traces(texttemplate="%{text:.2f}%", textposition="outside")
    fig.update_layout(template="plotly_white", height=520)
    caminho = CAMINHO_GRAFICOS / "bi_cancelamento_canal.html"
    fig.write_html(caminho, include_plotlyjs="cdn", full_html=True)
    log.info("Gráfico salvo: %s", caminho)
    log.info(
        "[Cancelamento] pior canal: %s (%.2f%%)",
        final.iloc[0]["canal"],
        final.iloc[0]["taxa_cancelamento"],
    )
    return final


# ---------------------------------------------------------------------------
# Relatório consolidado
# ---------------------------------------------------------------------------


def escrever_relatorio(
    coorte: pd.DataFrame,
    ltv: pd.DataFrame,
    rfm_resumo: pd.DataFrame,
    abc_xyz_: pd.DataFrame,
    estoque: pd.DataFrame,
    cancel: pd.DataFrame,
) -> None:
    """Grava o relatório textual consolidado com os principais achados.

    Args:
        coorte: DataFrame da análise de retenção por coorte.
        ltv: DataFrame de LTV por segmento.
        rfm_resumo: Resumo dos rótulos RFM.
        abc_xyz_: Classificação ABC/XYZ por produto.
        estoque: Saúde de estoque por produto.
        cancel: Cancelamento por canal.
    """
    top_ltv = ltv.iloc[0]
    campeoes = rfm_resumo[rfm_resumo["rotulo"] == "Campeões"]
    pct_campeoes = float(campeoes["pct_clientes"].sum()) if not campeoes.empty else 0.0
    pct_m = float(campeoes["%_monetario"].sum()) if not campeoes.empty else 0.0
    n_cat_a = int((abc_xyz_["abc"] == "A").sum())
    ruptura = int((estoque["alerta"] == "RISCO DE RUPTURA").sum())
    pior_canal = cancel.iloc[0]

    linhas = [
        "=" * 55,
        "  TecMente — Relatório de Análises de BI",
        f"  Gerado em : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 55,
        "1. Retenção por coorte",
        f"   Coortes analisadas: {len(coorte)} meses de aquisição.",
        "   Matriz completa em coorte_retencao.csv.",
        "",
        "2. LTV por segmento",
        f"   Maior LTV: {top_ltv['canal']} / {top_ltv['tipo']}",
        f"   → R$ {top_ltv['ltv_medio']:,.2f} por cliente "
        f"({top_ltv['pedidos']:,} pedidos).",
        "",
        "3. RFM",
        f"   Campeões: {pct_campeoes:.1f}% dos clientes, "
        f"{pct_m:.1f}% do faturamento.",
        "   Detalhamento por cliente em rfm_clientes.csv.",
        "",
        "4. Afinidade de cesta",
        "   Top pares de produtos em afinidade_cesta.csv.",
        "",
        "5. ABC/XYZ",
        f"   Produtos classe A: {n_cat_a} — ver abc_xyz_produtos.csv.",
        "",
        "6. Saúde de estoque",
        f"   Risco de ruptura: {ruptura} produtos — saude_estoque.csv.",
        "",
        "7. Cancelamento por canal",
        f"   Pior canal: {pior_canal['canal']} "
        f"({pior_canal['taxa_cancelamento']:.1f}% de cancelamentos, "
        f"{pior_canal['%_receita_perdida']:.1f}% da receita).",
        "=" * 55,
        "  Contexto: dados simulados TecMente para fins didáticos.",
        "=" * 55,
    ]
    caminho = CAMINHO_ANALISES / "relatorio_analises.txt"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    log.info("Relatório salvo: %s", caminho)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------

# Nome → função chamada, usado pela seleção parcial (--apenas)
_ANALISES: dict[str, tuple[str, ...]] = {
    "coorte": ("coorte_retencao",),
    "ltv": ("ltv_segmentos",),
    "rfm": ("rfm_rotulado",),
    "cesta": ("afinidade_cesta",),
    "abc": ("abc_xyz",),
    "estoque": ("saude_estoque",),
    "cancelamento": ("cancelamento_canal",),
}


def main() -> None:
    """Orquestra todas as análises de BI de ponta a ponta."""
    parser = argparse.ArgumentParser(
        description="Análises avançadas de BI — TecMente (Analista de BI)"
    )
    parser.add_argument(
        "--apenas",
        type=str,
        default="",
        help="Executar apenas análises específicas separadas por vírgula: "
        "coorte, ltv, rfm, cesta, abc, estoque, cancelamento.",
    )
    args = parser.parse_args()

    CAMINHO_ANALISES.mkdir(parents=True, exist_ok=True)

    if args.apenas:
        selecionadas = [s.strip() for s in args.apenas.split(",") if s.strip()]
    else:
        selecionadas = list(_ANALISES)

    if not selecionadas:
        log.error("Nenhuma análise selecionada. Use: --apenas rfm")
        return

    log.info("=" * 55)
    log.info("TecMente — Análises de BI  (Analista de BI)")
    log.info("=" * 55)

    vendas = _carregar_csv("vendas_tratado.csv")
    log.info("Vendas: %d linhas", len(vendas))
    clientes = _carregar_csv("clientes_tratado.csv")
    estoque = _carregar_csv("produtos_estoque_tratado.csv")

    coorte = rfm_resumo = ltv = abc_xyz_ = saude_est = cancel = None

    for nome in selecionadas:
        for func in _ANALISES.get(nome, ()):
            log.info("▶ %s", func)
            if func == "coorte_retencao":
                coorte = coorte_retencao(vendas)
            elif func == "ltv_segmentos":
                ltv = ltv_segmentos(vendas, clientes)
            elif func == "rfm_rotulado":
                _, rfm_resumo = rfm_rotulado(vendas, clientes)
            elif func == "afinidade_cesta":
                afinidade_cesta(vendas)
            elif func == "abc_xyz":
                abc_xyz_ = abc_xyz(vendas, estoque)
            elif func == "saude_estoque":
                saude_est = saude_estoque(estoque, vendas)
            elif func == "cancelamento_canal":
                cancel = cancelamento_canal(vendas)
            else:
                log.warning("Função desconhecida: %s", func)

    if all(
        v is not None for v in (coorte, ltv, rfm_resumo, abc_xyz_, saude_est, cancel)
    ):
        escrever_relatorio(coorte, ltv, rfm_resumo, abc_xyz_, saude_est, cancel)

    log.info("=" * 55)
    log.info("Análises em: %s", CAMINHO_ANALISES.resolve())
    log.info("=" * 55)


if __name__ == "__main__":
    main()
