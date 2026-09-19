# -*- coding: utf-8 -*-
"""Testes unitários para as funções de análise de BI do analise_bi.py.

Não requerem banco de dados — usam DataFrames sintéticos pequenos.

Executar com:
    poetry run pytest tests/test_analise_bi.py -q
"""

from __future__ import annotations

import pandas as pd
import pytest

from analise_bi import (
    _pedidos_faturados,
    abc_xyz,
    cancelamento_canal,
    coorte_retencao,
    ltv_segmentos,
    rfm_rotulado,
    saude_estoque,
)


def _vendas_fake(seed: int = 0) -> pd.DataFrame:
    """Cria um DataFrame de vendas sintético no nível de item.

    Reproduz o layout do CSV tratado (uma linha por item, com
    ``valor_total`` repetido por pedido) para validar as agregações.
    """
    vendas = pd.DataFrame(
        {
            "id_pedido": [1, 1, 2, 3, 3, 4, 5],
            "id_cliente": [10, 10, 20, 30, 30, 40, 10],
            "id_produto": [100, 101, 100, 200, 201, 300, 100],
            "quantidade": [2, 1, 3, 1, 1, 5, 1],
            "preco_venda": [50.0, 30.0, 50.0, 100.0, 40.0, 20.0, 50.0],
            "subtotal": [100.0, 30.0, 150.0, 100.0, 40.0, 100.0, 50.0],
            "valor_total": [126.1, 126.1, 145.0, 133.0, 133.0, 95.0, 121.5],
            "status": ["Concluído"] * 7,
            "canal": [
                "Site",
                "Site",
                "Marketplace",
                "Loja Física",
                "Loja Física",
                "WhatsApp",
                "Site",
            ],
            "data_pedido": [
                "2017-01-05",
                "2017-01-05",
                "2017-02-10",
                "2017-03-15",
                "2017-03-15",
                "2017-04-20",
                "2017-02-02",
            ],
            "produto_nome": [
                "Cabo A",
                "Cabo B",
                "Fonte C",
                "SSD D",
                "RAM E",
                "HD F",
                "Cabo A",
            ],
        }
    )
    vendas["data_pedido"] = pd.to_datetime(vendas["data_pedido"])
    return vendas


def _clientes_fake() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_cliente": [10, 20, 30, 40],
            "tipo": ["PF", "PJ", "PJ", "PF"],
            "estado": ["SP", "MG", "RJ", "SP"],
        }
    )


def _estoque_fake() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id_produto": [100, 101, 200, 201, 300],
            "estoque_total_rede": [10, 5, 3, 10, 2],
            "preco_venda": [50.0, 30.0, 100.0, 40.0, 20.0],
            "id_loja": [1, 1, 2, 2, 3],
            "margem_pct": [40.0, 40.0, 30.0, 45.0, 50.0],
        }
    )


# =============================================================================
# _pedidos_faturados — deduplicação do valor_total
# =============================================================================


class TestPedidosFaturados:
    def test_deduplica_valor_total_por_pedido(self) -> None:
        vendas = _vendas_fake()
        ped = _pedidos_faturados(vendas)
        assert len(ped) == vendas["id_pedido"].nunique()
        esperado = vendas.groupby("id_pedido")["valor_total"].first().values
        assert (ped["valor_total"].values == esperado).all()

    def test_soma_nao_infla_faturamento(self) -> None:
        vendas = _vendas_fake()
        ped = _pedidos_faturados(vendas)
        soma_itens = ped["valor_total"].sum()
        soma_bruta = vendas["valor_total"].sum()
        assert soma_itens < soma_bruta
        assert soma_itens == pytest.approx(620.6)


# =============================================================================
# LTV por segmento
# =============================================================================


class TestLtvSegmentos:
    def test_retorna_segmentos_validos(self) -> None:
        ltv = ltv_segmentos(_vendas_fake(), _clientes_fake())
        assert {"tipo", "canal", "clientes", "pedidos", "ltv_medio"}.issubset(
            ltv.columns
        )
        assert not ltv.empty

    def test_ticket_pj_maior_que_pf(self) -> None:
        ltv = ltv_segmentos(_vendas_fake(), _clientes_fake())
        pj_medio = ltv[ltv["tipo"] == "PJ"]["ticket_medio"].mean()
        pf_medio = ltv[ltv["tipo"] == "PF"]["ticket_medio"].mean()
        assert pj_medio > pf_medio


# =============================================================================
# RFM rotulado
# =============================================================================


class TestRfmRotulado:
    def test_classifica_todos_clientes(self) -> None:
        rfm, resumo = rfm_rotulado(_vendas_fake(), _clientes_fake())
        assert set(rfm["id_cliente"]) == {10, 20, 30, 40}
        assert {"r_score", "f_score", "m_score", "rotulo"}.issubset(rfm.columns)
        assert rfm["rotulo"].notna().all()

    def test_resumo_tem_soma_de_100(self) -> None:
        _, resumo = rfm_rotulado(_vendas_fake(), _clientes_fake())
        assert resumo["pct_clientes"].sum() == pytest.approx(100.0, abs=0.15)


# =============================================================================
# ABC / XYZ
# =============================================================================


class TestAbcXyz:
    def test_classifica_produtos(self) -> None:
        resultado = abc_xyz(_vendas_fake(), _estoque_fake())
        assert {"abc", "xyz"}.issubset(resultado.columns)
        assert set(resultado["abc"]) <= {"A", "B", "C"}
        assert set(resultado["xyz"]) <= {"X", "Y", "Z"}

    def test_produto_mais_vendido_e_classe_a(self) -> None:
        resultado = abc_xyz(_vendas_fake(), _estoque_fake())
        top = resultado.loc[resultado["receita_total"].idxmax()]
        assert top["abc"] == "A"


# =============================================================================
# Saúde de estoque
# =============================================================================


class TestSaudeEstoque:
    def test_gera_status_por_produto(self) -> None:
        resultado = saude_estoque(_estoque_fake(), _vendas_fake())
        assert len(resultado) == _estoque_fake()["id_produto"].nunique()
        assert set(resultado["alerta"]).issubset(
            {"SAUDÁVEL", "RISCO DE RUPTURA", "EXCESSO DE CAPITAL"}
        )
        assert "cobertura_dias" in resultado.columns


# =============================================================================
# Cancelamento por canal
# =============================================================================


class TestCancelamentoCanal:
    def test_taxa_entre_zero_e_cem(self, tmp_path, monkeypatch) -> None:
        from analise_bi import CAMINHO_ANALISES

        CAMINHO_ANALISES.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(
            "analise_bi.resolver_caminho_dados",
            lambda base: tmp_path,
        )
        (tmp_path / "vendas_cancelados.csv").write_text(
            "id_pedido,id_cliente,canal,data_pedido,status,valor_total,subtotal\n"
            "99,40,WhatsApp,2017-05-01,Cancelado,40.0,40.0\n",
            encoding="utf-8-sig",
        )
        resultado = cancelamento_canal(_vendas_fake())
        assert "taxa_cancelamento" in resultado.columns
        assert resultado["taxa_cancelamento"].between(0, 100).all()


# =============================================================================
# Coorte de retenção
# =============================================================================


class TestCoorteRetencao:
    def test_gera_matriz_de_retencao(self) -> None:
        from analise_bi import CAMINHO_ANALISES

        CAMINHO_ANALISES.mkdir(parents=True, exist_ok=True)
        resultado = coorte_retencao(_vendas_fake())
        assert not resultado.empty
        assert resultado.index.name == "coorte"
