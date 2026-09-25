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

    def test_campeoes_alcancavel_apos_inverter_recencia(self) -> None:
        """Regressão: rfm_total deve somar o r_score JÁ invertido para que
        um cliente excelente (frequência alta, recência baixa, alto valor)
        atinja o rótulo Campeões (rfm_total 15)."""
        rng = pd.date_range("2016-09-25", "2026-09-22", freq="40D")
        linhas: list[dict] = []
        n_pedido = 0
        # Campeão (cliente 40): 60 pedidos recentes e de alto valor.
        for k in range(60):
            n_pedido += 1
            linhas.append(
                {
                    "id_pedido": n_pedido,
                    "id_cliente": 40,
                    "id_produto": 1,
                    "quantidade": 5,
                    "preco_venda": 20.0,
                    "subtotal": 100.0,
                    "valor_total": 97.0,
                    "status": "Concluído",
                    "canal": "Site",
                    "data_pedido": "2026-09-10",
                }
            )
        # Demais clientes com frequência/valor/recência variados.
        for cli in range(1, 40):
            freq = (cli * 3) % 18 + 1
            for k in range(freq):
                n_pedido += 1
                linhas.append(
                    {
                        "id_pedido": n_pedido,
                        "id_cliente": cli,
                        "id_produto": 1,
                        "quantidade": 1,
                        "preco_venda": 10.0,
                        "subtotal": 10.0,
                        "valor_total": 9.7,
                        "status": "Concluído",
                        "canal": "Site",
                        "data_pedido": rng[cli % len(rng)],
                    }
                )
        vendas = pd.DataFrame(linhas)
        vendas["data_pedido"] = pd.to_datetime(vendas["data_pedido"])
        clientes = pd.DataFrame(
            {
                "id_cliente": list(range(1, 41)),
                "tipo": ["PF"] * 40,
                "estado": ["SP"] * 40,
            }
        )
        rfm, _ = rfm_rotulado(vendas, clientes)
        campeao = rfm[rfm["id_cliente"] == 40].iloc[0]
        assert campeao["rfm_total"] == 15
        assert campeao["rotulo"] == "Campeões"


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
    def _vendas_estoque(
        self, produtos: dict[int, int], ref: str = "2026-09-20"
    ) -> pd.DataFrame:
        """Vendas de um dia dentro da janela de giro, uma linha por produto.

        ``produtos`` mapeia id_produto -> quantidade vendida no dia da
        ``ref``. A data é fixada para que a janela de 90 dias da função
        seja sempre determinística.
        """
        return pd.DataFrame(
            {
                "id_pedido": range(1, len(produtos) + 1),
                "id_cliente": [10] * len(produtos),
                "id_produto": list(produtos),
                "quantidade": list(produtos.values()),
                "preco_venda": [50.0] * len(produtos),
                "subtotal": [50.0 * q for q in produtos.values()],
                "status": ["Concluído"] * len(produtos),
                "canal": ["Site"] * len(produtos),
                "data_pedido": pd.to_datetime([ref] * len(produtos)),
            }
        )

    def _estoque(self, produtos: dict[int, int]) -> pd.DataFrame:
        """Estoque com uma linha por produto, com estoque_total_rede."""
        return pd.DataFrame(
            {
                "id_produto": list(produtos),
                "estoque_total_rede": list(produtos.values()),
                "preco_venda": [50.0] * len(produtos),
                "id_loja": [1] * len(produtos),
                "margem_pct": [40.0] * len(produtos),
            }
        )

    def test_gera_status_por_produto(self) -> None:
        resultado = saude_estoque(_estoque_fake(), _vendas_fake())
        assert len(resultado) == _estoque_fake()["id_produto"].nunique()
        assert set(resultado["alerta"]).issubset(
            {"SAUDÁVEL", "RISCO DE RUPTURA", "EXCESSO DE CAPITAL", "SEM DEMANDA"}
        )
        assert "cobertura_dias" in resultado.columns

    def test_produto_sem_venda_na_janela_vira_sem_demanda(self) -> None:
        """Regressão: giro 0 produz cobertura NaN, que caía no default do
        np.select e recebia "SAUDÁVEL" — o oposto do alerta correto."""
        # Produto 1 vende 5/dia na janela de 90 dias => giro 5/90, e com
        # estoque 1 a cobertura fica em 18 dias (abaixo do limiar de 60).
        # Produto 2 não vende nada e tem estoque 10 => cobertura NaN.
        estoque = self._estoque({1: 1, 2: 10})
        vendas = self._vendas_estoque({1: 5})
        resultado = saude_estoque(estoque, vendas).set_index("id_produto")
        assert resultado.loc[1, "alerta"] == "RISCO DE RUPTURA"
        assert resultado.loc[2, "alerta"] == "SEM DEMANDA"

    def test_limiar_de_ruptura_dispara(self) -> None:
        """Cobertura abaixo do limiar tem de virar RISCO DE RUPTURA.

        Com a janela fixa em 90 dias, 5 unidades vendidas dão giro 5/90:
        estoque 10 => 180 dias (excesso, o topo da escala); estoque 1 =>
        18 dias (ruptura).
        """
        estoque = self._estoque({1: 10, 2: 1})
        vendas = self._vendas_estoque({1: 5, 2: 5})
        resultado = saude_estoque(estoque, vendas).set_index("id_produto")
        assert resultado.loc[1, "cobertura_dias"] == 180.0
        assert resultado.loc[1, "alerta"] == "EXCESSO DE CAPITAL"
        assert resultado.loc[2, "cobertura_dias"] == 18.0
        assert resultado.loc[2, "alerta"] == "RISCO DE RUPTURA"

    def test_limiares_sao_limites_inclusivos_e_exclusivos(self) -> None:
        """Regressão: os dois limiares vivem em dias, então as fronteiras
        precisam ficar explícitas — 60 dias ainda é ruptura, 61 é saudável;
        180 dias já é excesso, 179 ainda é saudável.

        90 unidades em 90 dias dão giro de 1/dia, então a cobertura em dias é
        exatamente o estoque — as fronteiras ficam testáveis sem arredondar.
        """
        estoque = self._estoque({1: 60, 2: 61, 3: 180, 4: 179})
        vendas = self._vendas_estoque({1: 90, 2: 90, 3: 90, 4: 90})
        resultado = saude_estoque(estoque, vendas).set_index("id_produto")
        assert resultado.loc[1, "cobertura_dias"] == 60.0
        assert resultado.loc[1, "alerta"] == "RISCO DE RUPTURA"
        assert resultado.loc[2, "alerta"] == "SAUDÁVEL"
        assert resultado.loc[3, "cobertura_dias"] == 180.0
        assert resultado.loc[3, "alerta"] == "EXCESSO DE CAPITAL"
        assert resultado.loc[4, "alerta"] == "SAUDÁVEL"

    def test_janela_de_giro_e_fixa_em_90_dias(self) -> None:
        """Regressão do divisor: a janela é a constante de 90 dias, não o
        span observado entre a primeira e a última venda da janela."""
        vendas_a = self._vendas_estoque({1: 90}, ref="2026-09-20")
        vendas_b = self._vendas_estoque({1: 90}, ref="2026-09-18")
        combine = pd.concat([vendas_a, vendas_b])
        resultado = saude_estoque(self._estoque({1: 90}), combine)
        # 180 unidades em 90 dias = giro 2/dia => cobertura 45 dias.
        assert resultado.loc[0, "cobertura_dias"] == 45.0

    def test_excesso_detectado_acima_do_limiar_de_dias(self) -> None:
        """Cobertura muito acima do limiar de dias vira EXCESSO DE CAPITAL."""
        estoque = self._estoque({1: 100, 2: 100, 3: 100_000})
        vendas = self._vendas_estoque({1: 10, 2: 10, 3: 10})
        resultado = saude_estoque(estoque, vendas).set_index("id_produto")
        assert resultado.loc[3, "alerta"] == "EXCESSO DE CAPITAL"


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
