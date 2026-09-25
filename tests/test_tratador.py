# -*- coding: utf-8 -*-
"""Testes unitários do tratador.py.

Cobre as funções puras de mascaramento e as quatro rotinas de tratamento
(tratar_clientes, tratar_vendas, tratar_produtos_estoque, tratar_equipe_lojas),
que antes não tinham nenhum teste — apesar de concentrarem as regras de
negócio do projeto.

Executar com:
    poetry run pytest
"""

from __future__ import annotations

import pandas as pd

from tratador import (
    RelatorioQualidade,
    corrigir_email,
    mascarar_cpf_cnpj,
    mascarar_email,
    normalizar_cpf_cnpj,
    tratar_clientes,
    tratar_equipe_lojas,
    tratar_produtos_estoque,
    tratar_vendas,
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


# =============================================================================
# RelatorioQualidade
# =============================================================================


class TestRelatorioQualidade:
    def test_nulos_registra_percentual(self, tmp_path) -> None:
        df = pd.DataFrame({"a": [1, None, 3, None]})
        rel = RelatorioQualidade(str(tmp_path / "r.txt"))
        rel.nulos(df, "teste.csv")
        assert any("50.0%" in linha for linha in rel.linhas)

    def test_nulos_sem_colunas_nulas_avisa(self, tmp_path) -> None:
        rel = RelatorioQualidade(str(tmp_path / "r.txt"))
        rel.nulos(pd.DataFrame({"a": [1, 2]}), "limpo.csv")
        assert any("Nenhum nulo encontrado." in linha for linha in rel.linhas)

    def test_salvar_gera_arquivo_com_cabecalho(self, tmp_path) -> None:
        destino = tmp_path / "rel.txt"
        rel = RelatorioQualidade(str(destino))
        rel.registro("Linhas lidas", 42)
        rel.salvar()
        conteudo = destino.read_text(encoding="utf-8")
        assert "Relatório de Qualidade de Dados" in conteudo
        assert "Linhas lidas" in conteudo
        assert "42" in conteudo


# =============================================================================
# Helpers
# =============================================================================


def _csv(df: pd.DataFrame, caminho) -> str:
    df.to_csv(caminho, index=False, encoding="utf-8")
    return str(caminho)


def _relatorio(tmp_path) -> RelatorioQualidade:
    return RelatorioQualidade(str(tmp_path / "relatorio.txt"))


# =============================================================================
# tratar_clientes
# =============================================================================


class TestTratarClientes:
    def _bruto(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id_cliente": [1, 2, 3],
                "sobrenome": ["Silva", None, "Souza"],
                "cpf_cnpj": ["123.456.789-00", "11.222.333/0001-81", "999"],
                "email": ["joao@gmail.con", "ana@empresa.com", "invalido"],
                "data_cadastro": ["2020-01-15", "2021-06-01", "2022-03-10"],
                "data_nascimento": ["1990-05-20", "", "1985-01-01"],
            }
        )

    def test_corrige_email_con_para_com(self, tmp_path) -> None:
        entrada = _csv(self._bruto(), tmp_path / "clientes.csv")
        df = tratar_clientes(entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path))
        # O e-mail em claro é removido da entrega (só fica o mascarado), mas a
        # coluna email_valido preserva o resultado da correção e da validação.
        linha = df[df["id_cliente"] == "1"].iloc[0]
        assert bool(linha["email_valido"]) is True
        assert linha["email_mascarado"].endswith("@gmail.com")

    def test_conta_emails_corrigidos_no_relatorio(self, tmp_path) -> None:
        bruto = self._bruto()
        relatorio = _relatorio(tmp_path)
        entrada = _csv(bruto, tmp_path / "clientes.csv")
        tratar_clientes(entrada, str(tmp_path / "out.csv"), relatorio)
        # 1 correção (.con -> .com) e 1 e-mail inválido no fixture.
        assert any(
            "1" in linha and "E-mails corrigidos" in linha for linha in relatorio.linhas
        )
        assert any("E-mails inválidos" in linha for linha in relatorio.linhas)

    def test_remove_colunas_sensiveis_originais(self, tmp_path) -> None:
        entrada = _csv(self._bruto(), tmp_path / "clientes.csv")
        df = tratar_clientes(entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path))
        assert "cpf_cnpj" not in df.columns
        assert "email" not in df.columns
        assert "cpf_cnpj_mascarado" in df.columns
        assert "email_mascarado" in df.columns

    def test_idade_nula_quando_nascimento_ausente(self, tmp_path) -> None:
        entrada = _csv(self._bruto(), tmp_path / "clientes.csv")
        df = tratar_clientes(entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path))
        assert pd.isna(df[df["id_cliente"] == "2"].iloc[0]["idade"])
        assert pd.notna(df[df["id_cliente"] == "1"].iloc[0]["idade"])

    def test_sobrenome_nulo_vira_string_vazia(self, tmp_path) -> None:
        entrada = _csv(self._bruto(), tmp_path / "clientes.csv")
        df = tratar_clientes(entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path))
        assert df[df["id_cliente"] == "2"].iloc[0]["sobrenome"] == ""

    def test_data_invalida_vira_nat_sem_explodir(self, tmp_path) -> None:
        bruto = self._bruto()
        bruto.loc[0, "data_cadastro"] = "31/02/2020"
        entrada = _csv(bruto, tmp_path / "clientes.csv")
        df = tratar_clientes(entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path))
        assert pd.isna(df[df["id_cliente"] == "1"].iloc[0]["data_cadastro"])

    def test_email_invalido_marcado(self, tmp_path) -> None:
        entrada = _csv(self._bruto(), tmp_path / "clientes.csv")
        df = tratar_clientes(entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path))
        assert bool(df[df["id_cliente"] == "3"].iloc[0]["email_valido"]) is False

    def test_ordena_por_data_de_cadastro(self, tmp_path) -> None:
        entrada = _csv(self._bruto(), tmp_path / "clientes.csv")
        df = tratar_clientes(entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path))
        cad = pd.to_datetime(df["data_cadastro"])
        assert cad.is_monotonic_increasing


# =============================================================================
# tratar_vendas
# =============================================================================


class TestTratarVendas:
    def _bruto(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id_pedido": [1, 1, 2, 3],
                "id_cliente": [10, 10, 20, 30],
                "id_produto": [100, 101, 100, 200],
                "quantidade": [2, 1, 3, 0],
                "preco_venda": [50.0, 30.0, 50.0, 40.0],
                "preco_custo": [30.0, 20.0, 30.0, 25.0],
                "status": ["Concluído", "Concluído", "Cancelado", "Concluído"],
                "data_pedido": [
                    "2026-03-23",
                    "2026-03-23",
                    "2026-03-24",
                    "2026-03-29",
                ],
                "id_funcionario": [7.0, 7.0, None, 9.0],
                "obs": [None, None, None, None],
            }
        )

    def _tratar(self, tmp_path, bruto=None):
        bruto = self._bruto() if bruto is None else bruto
        entrada = _csv(bruto, tmp_path / "vendas.csv")
        return tratar_vendas(
            entrada,
            str(tmp_path / "ativos.csv"),
            str(tmp_path / "cancelados.csv"),
            _relatorio(tmp_path),
        )

    def test_separa_cancelados_em_arquivo_proprio(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        assert "Cancelado" not in set(df["status"])
        cancelados = pd.read_csv(tmp_path / "cancelados.csv")
        assert set(cancelados["status"]) == {"Cancelado"}
        assert len(cancelados) == 1

    def test_id_funcionario_vira_int64_nullable(self, tmp_path) -> None:
        self._tratar(tmp_path)
        # Gotcha documentado no AGENTS.md: Int64 nullable, sem ".0" no CSV.
        ativos = pd.read_csv(tmp_path / "ativos.csv")
        assert "7.0" not in ativos["id_funcionario"].astype(str).tolist()
        assert ativos["id_funcionario"].isna().sum() >= 0

    def test_margem_pct_nan_quando_subtotal_zero(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        linha = df[df["id_pedido"] == 3].iloc[0]
        assert linha["subtotal"] == 0.0
        assert pd.isna(linha["margem_pct"])

    def test_margem_calculada_em_pct(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        linha = df[df["id_pedido"] == 1].iloc[0]  # 2 x 50 = 100, custo 2x30 = 60
        assert linha["subtotal"] == 100.0
        assert linha["lucro_bruto"] == 40.0
        assert linha["margem_pct"] == 40.0

    def test_dia_semana_em_portugues(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        # 2026-03-23 é segunda-feira.
        assert df[df["id_pedido"] == 1].iloc[0]["dia_semana"] == "Segunda"
        # 2026-03-29 é domingo.
        assert df[df["id_pedido"] == 3].iloc[0]["dia_semana"] == "Domingo"

    def test_deriva_ano_mes_trimestre(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        linha = df[df["id_pedido"] == 1].iloc[0]
        assert linha["ano"] == 2026
        assert linha["mes"] == 3
        assert linha["trimestre"] == 1

    def test_remove_coluna_totalmente_nula(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        assert "obs" not in df.columns

    def test_preserva_coluna_parcialmente_nula(self, tmp_path) -> None:
        bruto = self._bruto()
        bruto.loc[0, "obs"] = "entrega urgente"
        df = self._tratar(tmp_path, bruto)
        assert "obs" in df.columns

    def test_remove_coluna_inteiramente_nula_apos_leitura(self, tmp_path) -> None:
        bruto = self._bruto().drop(columns=["obs"])
        df = self._tratar(tmp_path, bruto)
        assert "obs" not in df.columns


# =============================================================================
# tratar_produtos_estoque
# =============================================================================


class TestTratarProdutosEstoque:
    def _bruto(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id_produto": [1, 1, 2, 3],
                "id_loja": [10, 11, 10, 10],
                "preco_venda": [49.99, 49.99, 50.0, 900.0],
                "preco_custo": [30.0, 30.0, 25.0, 500.0],
                "estoque_qtd": [10, 5, 3, 2],
                "estoque_data": ["2026-09-01"] * 4,
            }
        )

    def _tratar(self, tmp_path, bruto=None):
        bruto = self._bruto() if bruto is None else bruto
        entrada = _csv(bruto, tmp_path / "prod.csv")
        return tratar_produtos_estoque(
            entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path)
        )

    def test_faixa_preco_respeita_fronteiras(self, tmp_path) -> None:
        # pd.cut com right=True fecha o intervalo pela DIREITA: o limite de
        # cada faixa pertence à faixa inferior. 50.00 é LOW, não MID.
        df = self._tratar(tmp_path)
        faixas = dict(zip(df["preco_venda"], df["faixa_preco"]))
        assert faixas[49.99] == "LOW"
        assert faixas[50.0] == "LOW"
        assert faixas[900.0] == "HIGH"

    def test_estoque_total_rede_soma_por_produto(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        produto1 = df[df["id_produto"] == 1]["estoque_total_rede"].unique()
        assert list(produto1) == [15]

    def test_margem_pct_nan_quando_preco_venda_zero(self, tmp_path) -> None:
        bruto = self._bruto()
        bruto.loc[0, "preco_venda"] = 0.0
        df = self._tratar(tmp_path, bruto)
        assert pd.isna(df[df["id_produto"] == 1].iloc[0]["margem_pct"])


# =============================================================================
# tratar_equipe_lojas
# =============================================================================


class TestTratarEquipeLojas:
    def _bruto(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id_funcionario": [1, 2, 3, 4],
                "cpf": ["123.456.789-00", "987.654.321-00", "111.222.333-44", "555"],
                "salario": ["2999", "3000", "9000", "9500"],
                "data_admissao": ["2020-01-01", "2022-01-01", "2024-01-01", ""],
                "id_loja": [10, 10, 11, 11],
            }
        )

    def _tratar(self, tmp_path, bruto=None):
        bruto = self._bruto() if bruto is None else bruto
        entrada = _csv(bruto, tmp_path / "equipe.csv")
        return tratar_equipe_lojas(
            entrada, str(tmp_path / "out.csv"), _relatorio(tmp_path)
        )

    def test_faixa_salarial_respeita_fronteiras(self, tmp_path) -> None:
        # right=True: 3000 fecha a faixa Júnior, 9000 fecha a Sênior.
        df = self._tratar(tmp_path)
        faixas = dict(zip(df["salario"], df["faixa_salarial"]))
        assert faixas[2999] == "Júnior"
        assert faixas[3000] == "Júnior"
        assert faixas[9000] == "Sênior"

    def test_remove_cpf_original_e_normaliza(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        assert "cpf" not in df.columns
        assert "cpf_normalizado" in df.columns
        # Ler com dtype=str torna id_funcionario textual.
        assert (
            df[df["id_funcionario"] == "1"].iloc[0]["cpf_normalizado"] == "12345678900"
        )

    def test_tempo_casa_nulo_quando_sem_admissao(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        linha = df[df["id_funcionario"] == "4"].iloc[0]
        assert pd.isna(linha["tempo_casa_anos"])
        assert pd.isna(linha["tempo_casa_meses"])

    def test_tempo_casa_calculado(self, tmp_path) -> None:
        df = self._tratar(tmp_path)
        linha = df[df["id_funcionario"] == "1"].iloc[0]
        assert pd.notna(linha["tempo_casa_anos"])
        assert linha["tempo_casa_anos"] >= 5
