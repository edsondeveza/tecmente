# -*- coding: utf-8 -*-
"""
previsor.py  —  Papel: Data Scientist
======================================
Previsão de faturamento diário a partir dos dados tratados.

Abordagem (didática)
---------------------
1. Carrega a pasta ``*_tratado`` mais recente.
2. Agrega o faturamento diário de ``vendas_tratado.csv``.
3. Constrói features de calendário (dia da semana, mês, dia do mês,
   semana do ano) e features de defasagem (lag) da receita em 1, 7 e
   14 dias — capturando tendência e sazonalidade semanal.
4. Divide treino/teste de forma temporal (últimos N dias = teste),
   sem embaralhar, para respeitar a ordem do tempo.
5. Treina um modelo Random Forest de regressão (scikit-learn).
6. Gera previsões para os próximos M dias (previsão recursiva) e
   calcula métricas de qualidade (MAE, RMSE, MAPE) no teste.

Saída
------
output/predicoes/previsao_vendas.csv   — histórico + previsão
output/predicoes/relatorio_previsao.txt— métricas e resumo
output/graficos/previsao_vendas.html   — gráfico Plotly interativo

Uso
---
    python previsor.py                     # padrão: 14 dias, 30 de teste
    python previsor.py --dias_prever 7     # prevê a próxima semana
    python previsor.py --teste_dias 60     # mais dias de validação

Autor: Edson Deveza — Data Scientist
Versão: 1.1 (métricas de horizonte, WAPE, baseline e backtest)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from tecmente.dados import CAMINHO_BASE, resolver_caminho_dados
from visualizador import CAMINHO_GRAFICOS, PALETA

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Pasta raiz das predições — relativa ao script
CAMINHO_PREDICOES: Path = Path(__file__).parent / "output" / "predicoes"

# Defasagens de receita usadas como features (tendência + sazonalidade semanal)
LAGS: tuple[int, ...] = (1, 7, 14)

# Nomes das colunas de features, na mesma ordem usada no treinamento.
# Mantém o sklearn capaz de alinhar as features no predict (evita o aviso
# "X does not have valid feature names").
COLUNAS_FEATURES: list[str] = ["dia_semana", "mes", "dia_mes", "semana_ano"] + [
    f"lag_{lag}" for lag in LAGS
]


def resolver_pasta_tratada() -> Path:
    """Delega ao visualizador a resolução da pasta _tratado mais recente.

    Returns:
        Path da pasta _tratado mais recente.

    Raises:
        FileNotFoundError: Se nenhuma pasta _tratado existir.
    """
    return resolver_caminho_dados(CAMINHO_BASE)


def agregar_diario(pasta: Path) -> pd.DataFrame:
    """Agrega o faturamento diário a partir do CSV de vendas tratadas.

    Args:
        pasta: Pasta _tratado que contém vendas_tratado.csv.

    Returns:
        DataFrame com colunas ``data`` (datetime) e ``receita`` (float),
        ordenado cronologicamente.
    """
    caminho = pasta / "vendas_tratado.csv"
    df = pd.read_csv(caminho, sep=",", encoding="utf-8-sig")
    # parse_dates no read_csv é desencorajado no pandas 3.x; converte-se
    # explicitamente após a leitura (produz datetime64[us] idêntico).
    df["data_pedido"] = pd.to_datetime(df["data_pedido"])
    diario = (
        df.groupby(df["data_pedido"].dt.date, as_index=False)["subtotal"]
        .sum()
        .rename(columns={"data_pedido": "data", "subtotal": "receita"})  # type: ignore
        .sort_values("data")
    )
    diario["data"] = pd.to_datetime(diario["data"])
    return diario.reset_index(drop=True)


def construir_features(serie: pd.DataFrame) -> pd.DataFrame:
    """Adiciona features de calendário e de defasagem à série diária.

    Args:
        serie: DataFrame com colunas ``data`` e ``receita``.

    Returns:
        DataFrame com features ``dia_semana``, ``mes``, ``dia_mes``,
        ``semana_ano`` e colunas de lag ``lag_1``, ``lag_7``, ``lag_14``.
        Linhas sem lag completo (início da série) são descartadas.
    """
    feats = serie.copy()
    feats["dia_semana"] = feats["data"].dt.dayofweek
    feats["mes"] = feats["data"].dt.month
    feats["dia_mes"] = feats["data"].dt.day
    feats["semana_ano"] = feats["data"].dt.isocalendar().week.astype(int)

    for lag in LAGS:
        feats[f"lag_{lag}"] = feats["receita"].shift(lag)

    return feats.dropna().reset_index(drop=True)


def dividir_treino_teste(
    dados: pd.DataFrame, teste_dias: int
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """Divide os dados em treino/teste respeitando a ordem temporal.

    Args:
        dados: DataFrame com features e alvo (``receita``).
        teste_dias: Número de dias finais reservados para teste.

    Returns:
        Tupla (X_treino, y_treino, X_teste, y_teste).
    """
    corte = len(dados) - teste_dias
    X = dados.drop(columns=["data", "receita"])
    y = dados["receita"]

    X_treino, y_treino = X.iloc[:corte], y.iloc[:corte]
    X_teste, y_teste = X.iloc[corte:], y.iloc[corte:]
    return X_treino, y_treino, X_teste, y_teste


def treinar_modelo(
    X_treino: pd.DataFrame, y_treino: pd.Series
) -> RandomForestRegressor:
    """Treina um Random Forest de regressão.

    Args:
        X_treino: Features de treino.
        y_treino: Alvo (receita) de treino.

    Returns:
        Modelo treinado.
    """
    modelo = RandomForestRegressor(
        n_estimators=300,
        max_depth=10,
        random_state=42,
        n_jobs=-1,
    )
    modelo.fit(X_treino, y_treino)
    return modelo


def backtest(
    df_diario: pd.DataFrame,
    teste_dias: int = 30,
    blocos: int = 6,
) -> dict[str, object]:
    """Avalia o modelo em vários blocos de ``teste_dias`` consecutivos.

    Medir em uma única janela final é frágil: ela costuma cair numa faixa
    sazonalmente atípica e um número só vira ruído. Vários blocos dão uma
    leitura estável e revelam se o modelo consistentemente bate (ou perde
    para) a sazonalidade pura.

    Args:
        df_diario: Série diária com ``data`` e ``receita``.
        teste_dias: Tamanho de cada bloco de teste.
        blocos: Quantos blocos usar, terminando no fim da série.

    Returns:
        Dict com as médias e desvios por métrica, do modelo e do baseline.
    """
    dados = construir_features(df_diario)
    metricas_modelo: list[dict[str, float]] = []
    metricas_base: list[dict[str, float]] = []

    for k in range(blocos):
        fim = len(dados) - teste_dias * k
        corte = fim - teste_dias
        if corte < 400:  # treino mínimo para as sazonalidades
            break
        X_treino, y_treino, X_teste, y_teste = dividir_treino_teste(
            dados.iloc[:fim].copy(), teste_dias
        )
        if len(X_treino) == 0 or len(X_teste) == 0:
            continue
        modelo = treinar_modelo(X_treino, y_treino)
        metricas_modelo.append(avaliar_modelo(y_teste, modelo.predict(X_teste)))

        treino_bruto = df_diario.iloc[:fim]
        teste_bruto = df_diario.iloc[corte:fim]
        base = baseline_sazonal(treino_bruto, teste_bruto)
        metricas_base.append(avaliar_modelo(teste_bruto["receita"], base))

    def resumo(lista: list[dict[str, float]]) -> dict[str, float]:
        if not lista:
            return {}
        df = pd.DataFrame(lista)
        return {c: float(df[c].mean()) for c in df.columns}

    saida: dict[str, object] = {
        "blocos": len(metricas_modelo),
        "teste_dias": teste_dias,
        "modelo": resumo(metricas_modelo),
        "baseline": resumo(metricas_base),
    }
    if metricas_modelo:
        df = pd.DataFrame(metricas_modelo)
        saida["desvio"] = {c: float(df[c].std()) for c in df.columns}
    return saida


def gerar_relatorio_backtest(resultado: dict[str, object]) -> list[str]:
    """Monta as linhas do relatório de backtest multi-bloque."""
    if not resultado.get("blocos"):
        return ["(backtest ignorado: série curta demais)"]
    modelo = resultado["modelo"]  # type: ignore[index]
    base = resultado["baseline"]  # type: ignore[index]
    linhas = [
        f"   Backtest: {resultado['blocos']} blocos de {resultado['teste_dias']} dias",
        "   " + "-" * 50,
        "   Métrica          Modelo      Baseline sazonal",
    ]
    rotulos = {
        "mae": "MAE (R$)",
        "rmse": "RMSE (R$)",
        "mape": "MAPE diário",
        "wape": "WAPE diário",
        "erro_horizonte": "Erro do horizonte",
    }
    for chave, rotulo in rotulos.items():
        if chave not in modelo:
            continue
        valor_base = base.get(chave, float("nan"))
        linhas.append(f"   {rotulo:<15} {modelo[chave]:>9.1f}  {valor_base:>17.1f}")
    linhas.append("   " + "-" * 50)
    linhas.append("   Nota: o MAPE diário é a média dos erros individuais e penaliza")
    linhas.append("   dias de baixa receita. O erro do horizonte (soma do período) é")
    linhas.append("   a leitura que corresponde à decisão de negócio.")
    return linhas


def prever_futuro(
    modelo: RandomForestRegressor,
    dados: pd.DataFrame,
    dias_prever: int,
) -> list[float]:
    """Gera previsões recursivas para os próximos dias.

    Usa os lags das observações reais no início e, a partir do ponto em que
    não há mais observação, preenche os lags com a própria previsão anterior
    (previsão multi-passo recursiva).

    Args:
        modelo: Modelo treinado.
        dados: DataFrame com as colunas ``data`` e ``receita``, terminando na
            última observação real (não precisa estar no formato de features).
        dias_prever: Quantos dias para frente prever.

    Returns:
        Lista com as receitas previstas.
    """
    # Última data observada e valores de receita para alimentar os lags
    ultima_data = dados["data"].iloc[-1]
    receitas = list(dados["receita"].tail(max(LAGS)))

    previsoes: list[float] = []
    for i in range(dias_prever):
        data_fut = ultima_data + timedelta(days=i + 1)
        # int() no week: o treino grava como int64 (astype(int) em
        # construir_features) e isocalendar() devolve uint32 — sem o cast o
        # predict receberia tipos divergentes entre treino e previsão.
        vetor = [
            data_fut.dayofweek,
            data_fut.month,
            data_fut.day,
            int(data_fut.isocalendar().week),
        ]
        # Lags: últimos valores conhecidos (previstos quando não há real)
        for lag in LAGS:
            valor = receitas[-lag] if len(receitas) >= lag else 0.0
            vetor.append(valor)

        amostra = pd.DataFrame([vetor], columns=COLUNAS_FEATURES)
        pred = float(modelo.predict(amostra)[0])
        previsoes.append(pred)
        receitas.append(pred)

    return previsoes


def avaliar_modelo(y_real: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
    """Calcula métricas de erro da previsão.

    Inclui três leituras do mesmo erro, porque elas respondem perguntas
    diferentes:

    - ``mae``/``rmse``/``mape``: erro **por dia**. O MAPE é a média dos APEs
      individuais, então dias de receita baixa pesam igual a dias de venda
      grande e o número tende a parecer ruim.
    - ``wape``: erro agregado ponderado pelo próprio volume
      (soma dos absolutos / soma dos reais), menos sensível a esse viés.
    - ``erro_horizonte``/``mape_horizonte``: erro na **soma do horizonte**, que
      é a decisão que o relatório realmente comunica ("quanto vou faturar nos
      próximos N dias"). Os erros diários se cancelam parcialmente aqui.

    Args:
        y_real: Valores observados.
        y_pred: Valores previstos.

    Returns:
        Dict com ``mae``, ``rmse``, ``mape``, ``wape``, ``erro_horizonte`` e
        ``mape_horizonte``.
    """
    y_real = np.asarray(y_real, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    mae = float(mean_absolute_error(y_real, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_real, y_pred)))
    nao_zero = y_real != 0
    mape = (
        float(
            np.mean(np.abs((y_real[nao_zero] - y_pred[nao_zero]) / y_real[nao_zero]))
            * 100
        )
        if nao_zero.any()
        else 0.0
    )
    soma_real = float(y_real.sum())
    wape = float(np.abs(y_real - y_pred).sum() / soma_real * 100) if soma_real else 0.0
    soma_pred = float(y_pred.sum())
    erro_horizonte = (
        float(abs(soma_pred - soma_real) / soma_real * 100) if soma_real else 0.0
    )
    return {
        "mae": mae,
        "rmse": rmse,
        "mape": mape,
        "wape": wape,
        "erro_horizonte": erro_horizonte,
        "mape_horizonte": erro_horizonte,
    }


def baseline_sazonal(treino: pd.DataFrame, teste: pd.DataFrame) -> np.ndarray:
    """Previsão ingênua por sazonalidade mensal x dia da semana.

    Usa a mediana histórica de cada combinação (mês, dia da semana) — a mesma
    estrutura de features que o modelo consome, porém sem nenhum ajuste. Serve
    como piso de comparação: um modelo que não o supera não está agregando
    nada sobre a sazonalidade pura.

    Args:
        treino: DataFrame com ``data`` e ``receita`` (colunas do histórico).
        teste:  DataFrame com ``data`` e ``receita`` (janela a prever).

    Returns:
        Array com uma previsão por linha de ``teste``.
    """
    tabela = pd.DataFrame(
        {
            "receita": np.asarray(treino["receita"], dtype=float),
            "mes": pd.to_datetime(treino["data"]).dt.month,
            "dow": pd.to_datetime(treino["data"]).dt.dayofweek,
        }
    )
    mediana = tabela.pivot_table(
        index="mes", columns="dow", values="receita", aggfunc="median"
    )
    # Células nunca vistas (mês x dow sem histórico) caem na mediana global.
    global_mediana = float(np.median(tabela["receita"]))
    lookup = {
        (mes, dow): float(mediana.loc[mes, dow])
        for mes in mediana.index
        for dow in mediana.columns
        if pd.notna(mediana.loc[mes, dow])
    }
    datas = pd.to_datetime(teste["data"])
    return np.array(
        [
            lookup.get((d.month, d.dayofweek), global_mediana)
            for d in pd.to_datetime(datas)
        ]
    )


def gerar_relatorio(
    pasta_resumo: Path,
    metricas: dict[str, float],
    num_dias: int,
    receita: float,
    linhas_backtest: list[str] | None = None,
) -> None:
    """Grava o relatório de métricas da previsão.

    Args:
        pasta_resumo: Pasta onde o relatório será salvo.
        metricas: Dict com mae/rmse/mape/wape/erro_horizonte.
        num_dias: Número de dias previstos.
        receita: Soma da receita prevista.
        linhas_backtest: Bloco opcional com a comparação multi-bloque.
    """
    linhas = [
        "=" * 55,
        "  TecMente — Relatório de Previsão de Vendas",
        f"  Gerado em : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 55,
        f"  Dias previstos           : {num_dias}",
        f"  Receita prevista (soma)  : R$ {receita:,.2f}",
        "-" * 55,
        "  ERRO DIÁRIO (média por dia)",
        f"    MAE (erro médio abs.)  : R$ {metricas['mae']:,.2f}",
        f"    RMSE                   : R$ {metricas['rmse']:,.2f}",
        f"    MAPE (%)               : {metricas['mape']:.1f}%",
        f"    WAPE (%)               : {metricas.get('wape', 0.0):.1f}%",
        "-" * 55,
        "  ERRO NO HORIZONTE (soma do período)",
        f"    Erro (%)               : {metricas.get('erro_horizonte', 0.0):.1f}%",
        "=" * 55,
        "  Como ler: o MAPE diário é a média dos erros individuais e pesa" " dias de",
        "  baixa receita tanto quanto dias de venda grande. O erro do" " horizonte",
        "  é a leitura da decisão real: quanto faturamento o período soma.",
        "=" * 55,
        "  Método: Random Forest com features de calendário e lag de 1/7/14 dias.",
        "  Previsão recursiva para os próximos dias.",
    ]
    if linhas_backtest:
        linhas.extend(
            ["=" * 55, "  BACKTEST MULTI-BLOCO vs BASELINE SAZONAL", *linhas_backtest]
        )
    caminho = pasta_resumo / "relatorio_previsao.txt"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    log.info("Relatório salvo: %s", caminho)


def gerar_grafico(
    df_hist: pd.DataFrame,
    df_fut: pd.DataFrame,
    metricas: dict[str, float],
) -> None:
    """Gera o gráfico Plotly de histórico + previsão.

    Args:
        df_hist: DataFrame histórico (data, receita).
        df_fut: DataFrame futuro (data, previsao).
        metricas: Métricas para exibir no subtítulo.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df_hist["data"],
            y=df_hist["receita"],
            mode="lines",
            name="Histórico",
            line=dict(color=PALETA["primaria"], width=1.5),
            hovertemplate="%{x|%d/%m/%Y}<br>R$ %{y:,.2f}<extra></extra>",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df_fut["data"],
            y=df_fut["previsao"],
            mode="lines+markers",
            name="Previsão",
            line=dict(color=PALETA["secundaria"], width=2.5, dash="dash"),
            marker=dict(size=6),
            fill="tozeroy",
            hovertemplate="%{x|%d/%m/%Y}<br>R$ %{y:,.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        title=(
            f"Previsão de Faturamento Diário — TecMente<br>"
            f"<sup>MAE: R$ {metricas['mae']:,.0f} | RMSE: R$ "
            f"{metricas['rmse']:,.0f} | MAPE: {metricas['mape']:.1f}%</sup>"
        ),
        template="plotly_white",
        xaxis_title="Data",
        yaxis_title="Receita (R$)",
        height=560,
        legend=dict(orientation="h", y=1.1),
    )

    caminho = CAMINHO_GRAFICOS / "previsao_vendas.html"
    fig.write_html(caminho, include_plotlyjs="cdn", full_html=True)
    log.info("Gráfico de previsão salvo: %s", caminho)


def main() -> None:
    """Orquestra a previsão de vendas de ponta a ponta."""
    parser = argparse.ArgumentParser(
        description="Previsão de faturamento diário - TecMente (Data Scientist)"
    )
    parser.add_argument(
        "--dias_prever",
        type=int,
        default=14,
        help="Quantos dias para frente prever (padrão: 14).",
    )
    parser.add_argument(
        "--teste_dias",
        type=int,
        default=30,
        help="Quantos dias finais usar como teste (padrão: 30).",
    )
    parser.add_argument(
        "--backtest",
        type=int,
        default=0,
        metavar="N",
        help="Avalia o modelo em N blocos de --teste_dias e compara com o "
        "baseline sazonal (padrão: 0, desativado).",
    )
    args = parser.parse_args()

    CAMINHO_PREDICOES.mkdir(parents=True, exist_ok=True)

    log.info("=" * 55)
    log.info("TecMente — Previsor de Vendas  (Data Scientist)")
    log.info("=" * 55)

    pasta = resolver_pasta_tratada()
    df_diario = agregar_diario(pasta)
    log.info(
        "Série diária: %d dias (%s → %s)",
        len(df_diario),
        df_diario["data"].min().date(),
        df_diario["data"].max().date(),
    )

    dados = construir_features(df_diario)
    X_treino, y_treino, X_teste, y_teste = dividir_treino_teste(dados, args.teste_dias)

    log.info("Treino: %d | Teste: %d", len(X_treino), len(X_teste))
    modelo = treinar_modelo(X_treino, y_treino)

    y_pred_teste = modelo.predict(X_teste)
    metricas = avaliar_modelo(y_teste, np.array(y_pred_teste))
    log.info(
        "Métricas no teste → MAE: R$ %.2f | RMSE: R$ %.2f | MAPE: %.1f%% "
        "| erro do horizonte: %.1f%%",
        metricas["mae"],
        metricas["rmse"],
        metricas["mape"],
        metricas["erro_horizonte"],
    )

    if args.backtest > 0:
        log.info("Backtest multi-bloque (%d blocos)...", args.backtest)
        resultado_bt = backtest(df_diario, args.teste_dias, args.backtest)
        log.info("Backtest concluído: %s", resultado_bt)

    # Previsão futura
    previsoes = prever_futuro(modelo, df_diario, args.dias_prever)
    ultima_data = df_diario["data"].iloc[-1]
    df_fut = pd.DataFrame(
        {
            "data": [
                ultima_data + timedelta(days=i + 1) for i in range(args.dias_prever)
            ],
            "previsao": previsoes,
        }
    )

    # Saída CSV
    csv_caminho = CAMINHO_PREDICOES / "previsao_vendas.csv"
    df_fut.to_csv(csv_caminho, index=False, encoding="utf-8-sig")
    log.info("Previsão futura salva: %s", csv_caminho)

    receita_total = float(sum(previsoes))
    gerar_relatorio(
        CAMINHO_PREDICOES,
        metricas,
        args.dias_prever,
        receita_total,
        gerar_relatorio_backtest(resultado_bt) if args.backtest > 0 else None,
    )
    gerar_grafico(df_diario, df_fut, metricas)

    log.info("=" * 55)
    log.info(
        "Conclusão: previsão de %d dias gerada (R$ %s).",
        args.dias_prever,
        f"{receita_total:,.2f}",
    )
    log.info("=" * 55)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("Previsão falhou.")
        sys.exit(1)
