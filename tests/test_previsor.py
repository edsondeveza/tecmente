"""Testes do módulo previsor (funções puras de preparação/avaliação)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from previsor import (
    COLUNAS_FEATURES,
    avaliar_modelo,
    construir_features,
    dividir_treino_teste,
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
        assert set(metricas) == {"mae", "rmse", "mape"}
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
