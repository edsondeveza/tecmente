"""Testes do módulo previsor (funções puras de preparação/avaliação)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from previsor import (
    COLUNAS_FEATURES,
    agregar_diario,
    avaliar_modelo,
    backtest,
    baseline_sazonal,
    construir_features,
    dividir_treino_teste,
    gerar_relatorio_backtest,
    prever_futuro,
    treinar_modelo,
)


@pytest.fixture
def serie_diaria() -> pd.DataFrame:
    """Série diária sintética de 35 dias com sazonalidade semanal."""
    datas = pd.date_range("2024-01-01", periods=35)
    receita = 1000.0 + 100 * datas.dayofweek.to_numpy()
    return pd.DataFrame({"data": datas, "receita": receita})


class TestConstruirFeatures:
    def test_colunas_esperadas(self, serie_diaria) -> None:
        feats = construir_features(serie_diaria)
        assert set(COLUNAS_FEATURES).issubset(feats.columns)
        assert "receita" in feats.columns

    def test_descarta_primeiros_dias_sem_lag(self, serie_diaria) -> None:
        feats = construir_features(serie_diaria)
        lag_max = max((7, 14))
        assert len(feats) == len(serie_diaria) - lag_max

    def test_semana_ano_eh_inteiro(self, serie_diaria) -> None:
        feats = construir_features(serie_diaria)
        assert feats["semana_ano"].dtype == "int64"


class TestDividirTreinoTeste:
    def test_respeita_ordem_temporal(self, serie_diaria) -> None:
        feats = construir_features(serie_diaria)
        X_treino, y_treino, X_teste, y_teste = dividir_treino_teste(feats, teste_dias=7)
        assert len(X_treino) + len(X_teste) == len(feats)
        assert y_teste.index[0] > y_treino.index[-1]


class TestAvaliarModelo:
    def test_metricas_nao_negativas(self) -> None:
        y_real = pd.Series([100.0, 200.0, 150.0])
        y_pred = np.array([110.0, 190.0, 160.0])
        metricas = avaliar_modelo(y_real, y_pred)
        assert set(metricas) == {
            "mae",
            "rmse",
            "mape",
            "wape",
            "erro_horizonte",
            "mape_horizonte",
        }
        assert all(v >= 0 for v in metricas.values())
        assert metricas["mae"] > 0

    def test_mape_zero_para_serie_toda_zero(self) -> None:
        y_real = pd.Series([0.0, 0.0])
        metricas = avaliar_modelo(y_real, np.array([0.0, 0.0]))
        assert metricas["mape"] == 0.0


class TestTreinarModelo:
    def test_treina_e_prediz_formato(self, serie_diaria) -> None:
        feats = construir_features(serie_diaria)
        X, y = feats.drop(columns=["data", "receita"]), feats["receita"]
        modelo = treinar_modelo(X, y)
        assert len(modelo.predict(X.head(1))) == 1


# =============================================================================
# agregar_diario
# =============================================================================


class TestAgregarDiario:
    def _csv(self, pasta, tmp_path):
        pasta.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            {
                "id_pedido": [1, 1, 2, 3],
                "data_pedido": [
                    "2026-03-24",
                    "2026-03-23",
                    "2026-03-24",
                    "2026-03-22",
                ],
                "subtotal": [10.0, 20.0, 30.0, 40.0],
            }
        ).to_csv(pasta / "vendas_tratado.csv", index=False, encoding="utf-8")
        return pasta

    def test_soma_itens_do_mesmo_dia(self, tmp_path) -> None:
        pasta = self._csv(tmp_path / "2026-09-23_tratado", tmp_path)
        diario = agregar_diario(pasta)
        por_data = dict(zip(diario["data"].dt.strftime("%Y-%m-%d"), diario["receita"]))
        assert por_data["2026-03-24"] == 40.0  # 10 + 30
        assert por_data["2026-03-23"] == 20.0
        assert por_data["2026-03-22"] == 40.0

    def test_ordena_cronologicamente(self, tmp_path) -> None:
        pasta = self._csv(tmp_path / "2026-09-23_tratado", tmp_path)
        diario = agregar_diario(pasta)
        assert diario["data"].is_monotonic_increasing
        assert list(diario.index) == list(range(len(diario)))

    def test_colunas_de_saida(self, tmp_path) -> None:
        pasta = self._csv(tmp_path / "2026-09-23_tratado", tmp_path)
        diario = agregar_diario(pasta)
        assert list(diario.columns) == ["data", "receita"]
        assert pd.api.types.is_datetime64_any_dtype(diario["data"])


# =============================================================================
# prever_futuro
# =============================================================================


class FakeModelo:
    """Modelo que devolve um valor fixo e registra as features recebidas."""

    def __init__(self, valor: float = 100.0) -> None:
        self.valor = valor
        self.amostras: list[list[float]] = []

    def predict(self, amostra):
        # previr_futuro monta pd.DataFrame([vetor]) — uma linha, colunas 0..n-1.
        if hasattr(amostra, "iloc"):
            linha = amostra.iloc[0].tolist()
        else:
            linha = list(amostra[0])
        self.amostras.append(linha)
        return [self.valor]


class TestPreverFuturo:
    def test_gera_tantas_previsoes_quanto_dias(self, serie_diaria) -> None:
        modelo = FakeModelo()
        assert len(prever_futuro(modelo, serie_diaria, dias_prever=7)) == 7

    def test_datas_sao_consecutivas_apos_ultima_observacao(self, serie_diaria) -> None:
        modelo = FakeModelo()
        previsoes = prever_futuro(modelo, serie_diaria, dias_prever=3)
        assert len(previsoes) == 3
        assert previsoes == [100.0, 100.0, 100.0]

    def test_respeita_ordem_de_colunas(self, serie_diaria) -> None:
        """As features precisam sair na ordem que o modelo foi treinado."""
        modelo = FakeModelo()
        prever_futuro(modelo, serie_diaria, dias_prever=1)
        assert len(modelo.amostras[0]) == len(COLUNAS_FEATURES)

    def test_lag_menor_que_historico_usa_zero(self) -> None:
        """Regressão: série mais curta que o maior lag não pode estourar.

        Com 3 observações, lag_1 ainda tem histórico (vale 30.0), mas
        lag_7 e lag_14 não têm e precisam virar 0.0 — um índice negativo
        seria silenciosamente o valor errado.
        """
        curto = pd.DataFrame(
            {
                "data": pd.date_range("2026-01-01", periods=3),
                "receita": [10.0, 20.0, 30.0],
            }
        )
        modelo = FakeModelo()
        prever_futuro(modelo, curto, dias_prever=1)
        # 4 features de calendário + 3 lags.
        assert modelo.amostras[0][4:] == [30.0, 0.0, 0.0]

    def test_e_recursivo_usa_previsao_anterior(self) -> None:
        """A previsão do dia N-7 deve entrar como lag do dia N."""
        modelo = FakeModelo(valor=1000.0)
        serie = pd.DataFrame(
            {
                "data": pd.date_range("2026-01-01", periods=20),
                "receita": [500.0] * 20,
            }
        )
        prever_futuro(modelo, serie, dias_prever=8)
        # Passo 8: lag_7 deve ser a previsão do passo 1, não a observação real.
        lag7_passo8 = modelo.amostras[7][5]
        assert lag7_passo8 == 1000.0
        # No passo 1 o lag_7 ainda é uma observação real da série.
        assert modelo.amostras[0][5] == 500.0


# =============================================================================
# avaliar_modelo — métricas de horizonte
# =============================================================================


class TestMetricasDeHorizonte:
    def test_perfeito_zerando_todas_as_metricas(self) -> None:
        y = pd.Series([100.0, 200.0, 300.0])
        m = avaliar_modelo(y, np.array([100.0, 200.0, 300.0]))
        for chave in ("mae", "rmse", "mape", "wape", "erro_horizonte"):
            assert m[chave] == pytest.approx(0.0), chave

    def test_erro_horizonte_agrega_erros_diarios(self) -> None:
        """Erros grandes que se cancelam no somatório valem pouco no horizonte."""
        y = pd.Series([100.0, 200.0])
        # 200 e 100 trocados: erro enorme por dia, erro zero na soma.
        m = avaliar_modelo(y, np.array([200.0, 100.0]))
        assert m["mape"] > 50
        assert m["erro_horizonte"] == pytest.approx(0.0)

    def test_wape_penaliza_menos_que_mape(self) -> None:
        y = pd.Series([1000.0, 10.0])
        m = avaliar_modelo(y, np.array([500.0, 20.0]))
        assert m["wape"] < m["mape"]

    def test_serie_com_zeros_nao_divide_por_zero(self) -> None:
        m = avaliar_modelo(pd.Series([0.0, 100.0]), np.array([10.0, 90.0]))
        assert m["mape"] == pytest.approx(10.0)
        assert np.isfinite(m["wape"])


# =============================================================================
# baseline_sazonal
# =============================================================================


class TestBaselineSazonal:
    def test_reproduz_a_mediana_mes_x_dow(self) -> None:
        """Segunda-feira do mês 3 sempre teve 500; o baseline deve devolver 500."""
        datas = pd.to_datetime(["2024-01-01", "2025-01-01", "2024-03-04", "2025-03-03"])
        treino = pd.DataFrame({"data": datas, "receita": [100.0, 100.0, 500.0, 500.0]})
        teste = pd.DataFrame({"data": pd.to_datetime(["2026-03-02"]), "receita": [0.0]})
        prev = baseline_sazonal(treino, teste)
        assert prev[0] == pytest.approx(500.0)

    def test_celula_sem_historico_cai_na_mediana_global(self) -> None:
        treino = pd.DataFrame(
            {
                "data": pd.date_range("2024-01-01", periods=20),
                "receita": np.arange(20, dtype=float) + 100,
            }
        )
        # 15 de julho nunca aparece no treino.
        teste = pd.DataFrame({"data": pd.to_datetime(["2026-07-15"]), "receita": [0.0]})
        prev = baseline_sazonal(treino, teste)
        assert 100 <= prev[0] <= 120

    def test_uma_previsao_por_linha_do_teste(self) -> None:
        treino = pd.DataFrame(
            {
                "data": pd.date_range("2024-01-01", periods=40),
                "receita": np.arange(40, dtype=float) + 1,
            }
        )
        teste = pd.DataFrame(
            {"data": pd.date_range("2026-01-01", periods=5), "receita": np.zeros(5)}
        )
        assert len(baseline_sazonal(treino, teste)) == 5


# =============================================================================
# backtest
# =============================================================================


def serie_longa(n: int = 800) -> pd.DataFrame:
    """Série diária longa o bastante para o backtest (train mínimo = 400)."""
    datas = pd.date_range("2020-01-01", periods=n)
    dow = datas.dayofweek.to_numpy()
    receita = 1000.0 + 50 * dow + 10 * (datas.month.to_numpy() % 3)
    return pd.DataFrame({"data": datas, "receita": receita})


class TestBacktest:
    def test_devolve_media_do_modelo_e_do_baseline(self) -> None:
        r = backtest(serie_longa(), teste_dias=20, blocos=2)
        assert r["blocos"] == 2
        assert r["teste_dias"] == 20
        for chave in ("mae", "rmse", "mape", "wape", "erro_horizonte"):
            assert chave in r["modelo"]
            assert chave in r["baseline"]

    def test_serie_curta_devolve_blocos_zero(self) -> None:
        r = backtest(serie_longa(120), teste_dias=20, blocos=3)
        assert r["blocos"] == 0
        assert r["modelo"] == {}
        assert r["baseline"] == {}

    def test_inclui_desvio_padrao_entre_blocos(self) -> None:
        r = backtest(serie_longa(), teste_dias=20, blocos=3)
        assert r["blocos"] == 3
        assert "mae" in r["desvio"]


# =============================================================================
# gerar_relatorio_backtest
# =============================================================================


class TestRelatorioBacktest:
    def test_linhas_comparam_modelo_e_baseline(self) -> None:
        r = backtest(serie_longa(), teste_dias=20, blocos=2)
        linhas = gerar_relatorio_backtest(r)
        texto = "\n".join(linhas)
        assert "Baseline sazonal" in texto
        assert "Erro do horizonte" in texto

    def test_serie_curta_avisa_que_pulou(self) -> None:
        r = backtest(serie_longa(120), teste_dias=20, blocos=2)
        linhas = gerar_relatorio_backtest(r)
        assert linhas == ["(backtest ignorado: série curta demais)"]
