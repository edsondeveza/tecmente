"""Testes dos helpers de geração de pedidos do gerador mestre."""

from __future__ import annotations

from datetime import date

from gerador_mestre import (
    _compor_itens,
    _escolher_cliente,
    _indice_por_ticket,
)


class TestIndicePorTicket:
    def test_agrupa_por_faixa_de_preco(self) -> None:
        prods = [
            (1, 15.0, 8.0),
            (2, 80.0, 40.0),
            (3, 500.0, 250.0),
            (4, 3000.0, 1500.0),
        ]
        idx = _indice_por_ticket(prods)
        assert {k for k, v in idx.items() if v} == {"LOW", "MID", "HIGH", "ULTRA"}


class TestEscolherCliente:
    def test_cliente_normal_quando_faixas_nao_disparam(self, monkeypatch) -> None:
        # r=0.5 → nem super-ativo (r<0.40) nem inativo (r<0.43) → normal.
        monkeypatch.setattr("gerador_mestre.random.random", lambda: 0.5)
        resultado = _escolher_cliente(
            super_ativos={1},
            inativos={2},
            normais=[3],
            pj_ids=[3],
            recentes={},
        )
        assert resultado == (3, True, False)

    def test_anomalia_usa_cliente_recente(self, monkeypatch) -> None:
        # random.random() primeiro chamada 0.01 (< RUIDO_PEDIDO_ANTES_CADASTRO)
        seq = iter([0.01])
        monkeypatch.setattr("gerador_mestre.random.random", lambda: next(seq))
        monkeypatch.setattr("gerador_mestre.random.choice", lambda valores: valores[0])
        resultado = _escolher_cliente(
            super_ativos={1},
            inativos={2},
            normais=[3],
            pj_ids=[1],
            recentes={9: date(2026, 9, 1)},
        )
        assert resultado == (9, False, True)

    def test_retorna_none_sem_clientes_elegiveis(self, monkeypatch) -> None:
        # r=0.41: não atinge super (r<0.40) nem inativo não vazio; normais vazio.
        seq = iter([0.5, 0.41])
        monkeypatch.setattr("gerador_mestre.random.random", lambda: next(seq))
        assert (
            _escolher_cliente(
                super_ativos=set(),
                inativos=set(),
                normais=[],
                pj_ids=[],
                recentes={},
            )
            is None
        )


class TestComporItens:
    def test_pj_monta_itens_sem_repeticao(self, monkeypatch) -> None:
        prods = [
            (1, 10.0, 5.0),
            (2, 80.0, 25.0),
            (3, 500.0, 100.0),
            (4, 2000.0, 1000.0),
        ]
        por_ticket = _indice_por_ticket(prods)

        # tickets fixos: um de cada faixa; escolhe sempre o primeiro candidato;
        # qtd sempre 7 (exceto ULTRA, que é 1 por construção).
        monkeypatch.setattr(
            "gerador_mestre.random.choices",
            lambda seq, weights, k: ["LOW", "MID", "HIGH", "ULTRA"],
        )
        monkeypatch.setattr("gerador_mestre.random.choice", lambda valores: valores[0])
        monkeypatch.setattr("gerador_mestre.random.randint", lambda a, b: 7)
        monkeypatch.setattr("gerador_mestre.random.random", lambda: 0.0)

        itens, total = _compor_itens(
            por_ticket, prods, populares=set(), pj=True, escolhidos=set()
        )

        ids = [it[0] for it in itens]
        assert len(itens) == 4
        assert len(set(ids)) == 4
        # total = 7*10 (LOW) + 7*80 (MID) + 7*500 (HIGH) + 1*2000 (ULTRA fixo 1)
        assert total == 70 + 560 + 3500 + 2000

    def test_pj_seleciona_populares_quando_disponiveis(self, monkeypatch) -> None:
        prods = [(1, 10.0, 5.0), (2, 50.0, 25.0), (3, 200.0, 100.0)]
        por_ticket = _indice_por_ticket(prods)
        monkeypatch.setattr(
            "gerador_mestre.random.choices",
            lambda seq, weights, k: ["LOW", "MID", "HIGH"],
        )
        monkeypatch.setattr("gerador_mestre.random.randint", lambda a, b: 1)
        # random < 0.60 → troca o pool para só produtos populares
        monkeypatch.setattr("gerador_mestre.random.random", lambda: 0.0)

        itens, _ = _compor_itens(
            por_ticket, prods, populares={2}, pj=True, escolhidos=set()
        )
        escolhidos = {it[0] for it in itens}
        # Alta probabilidade de conter o popular nos MID/HIGH disponíveis
        assert 2 in escolhidos
