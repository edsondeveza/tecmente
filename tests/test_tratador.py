# -*- coding: utf-8 -*-
"""Testes unitários para funções puras de tratamento de dados do tratador.py.

Executar com:
    poetry run pytest
"""

from __future__ import annotations

import pandas as pd
import pytest

from tratador import (
    corrigir_email,
    mascarar_cpf_cnpj,
    mascarar_email,
    normalizar_cpf_cnpj,
)


# =============================================================================
# mascarar_cpf_cnpj
# =============================================================================

class TestMascararCpfCnpj:
    def test_formato_pontuado(self) -> None:
        assert mascarar_cpf_cnpj("123.456.789-00") == "***.***.***-00"

    def test_formato_numerico(self) -> None:
        assert mascarar_cpf_cnpj("12345678900") == "*********00"

    def test_formato_sublinhado(self) -> None:
        assert mascarar_cpf_cnpj("123_456_789_00") == "***_***_***_00"

    def test_cnpj(self) -> None:
        assert mascarar_cpf_cnpj("12.345.678/0001-99") == "**.***.***/****-99"

    def test_valor_nulo(self) -> None:
        assert mascarar_cpf_cnpj(None) == ""
        assert mascarar_cpf_cnpj(pd.NA) == ""
        assert mascarar_cpf_cnpj("") == ""


# =============================================================================
# mascarar_email
# =============================================================================

class TestMascararEmail:
    def test_email_normal(self) -> None:
        assert mascarar_email("joao.silva@gmail.com") == "j***@gmail.com"

    def test_email_curto(self) -> None:
        assert mascarar_email("a@b.com") == "a***@b.com"

    def test_sem_arroba(self) -> None:
        assert mascarar_email("invalido") == "***"

    def test_valor_nulo(self) -> None:
        assert mascarar_email(None) == ""
        assert mascarar_email(pd.NA) == ""


# =============================================================================
# normalizar_cpf_cnpj
# =============================================================================

class TestNormalizarCpfCnpj:
    def test_pontuado(self) -> None:
        assert normalizar_cpf_cnpj("123.456.789-00") == "12345678900"

    def test_sublinhado(self) -> None:
        assert normalizar_cpf_cnpj("123_456_789_00") == "12345678900"

    def test_sem_pontuacao(self) -> None:
        assert normalizar_cpf_cnpj("12345678900") == "12345678900"

    def test_valor_nulo(self) -> None:
        assert normalizar_cpf_cnpj(None) == ""


# =============================================================================
# corrigir_email
# =============================================================================

class TestCorrigirEmail:
    def test_typo_con_para_com(self) -> None:
        assert corrigir_email("joao@gmail.con") == ("joao@gmail.com", True)

    def test_email_valido_inalterado(self) -> None:
        assert corrigir_email("joao@gmail.com") == ("joao@gmail.com", True)

    def test_email_invalido(self) -> None:
        assert corrigir_email("invalido") == ("invalido", False)

    def test_capitular_typo(self) -> None:
        assert corrigir_email("joao@gmail.CON") == ("joao@gmail.com", True)

    def test_valor_nulo(self) -> None:
        assert corrigir_email(None) == ("", False)
        assert corrigir_email(pd.NA) == ("", False)