"""Testes da lógica temporal de estoque do gerador (funções puras)."""

from __future__ import annotations

from datetime import date

import pytest

from gerador_mestre import (
    DIAS_COBERTURA_ALVO,
    JANELA_REPOSICAO,
    _datas_snapshot,
    _demanda_janela,
    _nivel_estoque,
)


class TestDatasSnapshot:
    def test_comeca_no_mes_seguinte_ao_inicio(self) -> None:
        datas = _datas_snapshot(date(2020, 3, 15), date(2020, 6, 10))
        assert datas[0] == date(2020, 4, 1)

    def test_termina_sempre_na_data_fim(self) -> None:
        fim = date(2020, 6, 10)
        assert _datas_snapshot(date(2020, 3, 15), fim)[-1] == fim

    def test_nao_duplica_quando_fim_ja_e_primeiro_do_mes(self) -> None:
        fim = date(2020, 5, 1)
        datas = _datas_snapshot(date(2020, 3, 15), fim)
        assert datas[-1] == date(2020, 5, 1)
        assert len(datas) == len(set(datas))

    def test_datas_sao_crescentes(self) -> None:
        datas = _datas_snapshot(date(2016, 9, 25), date(2026, 9, 25))
        assert datas == sorted(datas)
        assert len(datas) == 121  # 10 anos de meses + o snapshot corrente

    def test_vira_o_ano_corretamente(self) -> None:
        datas = _datas_snapshot(date(2020, 11, 15), date(2021, 2, 5))
        assert date(2020, 12, 1) in datas
        assert date(2021, 1, 1) in datas
        assert date(2021, 2, 1) in datas


class TestDemandaJanela:
    def test_soma_meses_dentro_da_janela(self) -> None:
        vendas = {
            (1, 7, 2024, 1): 10,  # dentro
            (1, 7, 2024, 2): 5,  # dentro (30 dias cobre jan+fev)
            (1, 7, 2024, 3): 99,  # fora
        }
        total = _demanda_janela(vendas, 1, 7, date(2024, 1, 15), 30)
        assert total == 15

    def test_ignora_outro_produto_ou_loja(self) -> None:
        vendas = {
            (1, 7, 2024, 1): 10,
            (1, 8, 2024, 1): 100,  # outro produto
            (2, 7, 2024, 1): 100,  # outra loja
        }
        assert _demanda_janela(vendas, 1, 7, date(2024, 1, 1), 30) == 10

    def test_janela_vazia_retorna_zero(self) -> None:
        assert _demanda_janela({}, 1, 7, date(2024, 1, 1), 30) == 0

    def test_nao_conta_mes_que_so_comeca_apos_o_fim(self) -> None:
        """Janela de 30 dias ending em 20/02 não pode puxar março inteiro."""
        vendas = {
            (1, 7, 2024, 1): 4,
            (1, 7, 2024, 2): 4,
            (1, 7, 2024, 3): 4,
        }
        total = _demanda_janela(vendas, 1, 7, date(2024, 1, 22), 30)
        assert total == 8  # só janeiro e fevereiro


class TestNivelEstoque:
    def test_escala_com_a_demanda(self) -> None:
        assert _nivel_estoque(60, 1.0) > _nivel_estoque(10, 1.0)

    def test_fator_1_aponta_para_a_meta_de_cobertura(self) -> None:
        """Com fator 1.0 o saldo deve cobrir DIAS_COBERTURA_ALVO dias."""
        n = _nivel_estoque(30, 1.0)
        cobertura = n / (30 / JANELA_REPOSICAO)
        assert cobertura == pytest.approx(DIAS_COBERTURA_ALVO, abs=3)

    def test_fator_alto_compra_mais_que_fator_baixo(self) -> None:
        assert _nivel_estoque(30, 1.8) > _nivel_estoque(30, 0.5)

    def test_nunca_retorna_negativo(self) -> None:
        assert _nivel_estoque(0, 0.1) == 0
        assert _nivel_estoque(0, 1.0) == 0

    def test_sem_demanda_gera_zerado(self) -> None:
        assert _nivel_estoque(0, 1.5) == 0
