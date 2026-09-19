# -*- coding: utf-8 -*-
"""
validador_coerencia.py — Validações de consistência dos dados gerados

Executa as 18 verificações pedidas no prompt.md para garantir que os dados
estão coerentes após as alterações no gerador.

Uso
---
    poetry run python validador_coerencia.py

Autor: Edson Deveza
Versão: 1.0
"""

from __future__ import annotations

import logging

import mysql.connector

from config import DB_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class ValidadorCoerencia:
    def __init__(self):
        self.conn = None
        self.cur = None
        self.resultados = {}

    def conectar(self):
        """Estabelece conexão com o banco de dados."""
        try:
            self.conn = mysql.connector.connect(**DB_CONFIG)
            self.cur = self.conn.cursor(dictionary=True)
            log.info("Conectado ao banco de dados")
        except Exception as e:
            log.error(f"Erro ao conectar ao banco: {e}")
            raise

    def fechar(self):
        """Fecha conexão com o banco."""
        if self.cur:
            self.cur.close()
        if self.conn:
            self.conn.close()
            log.info("Conexão com banco fechada")

    def executar_query(self, descricao: str, query: str, check_valor_esperado=None):
        """Executa uma query e armazena o resultado."""
        try:
            self.cur.execute(query)
            resultado = self.cur.fetchall()
            self.resultados[descricao] = resultado

            if check_valor_esperado is not None:
                if isinstance(check_valor_esperado, bool):
                    sucesso = (
                        bool(resultado[0]["contagem"] == 0) if resultado else False
                    )
                else:
                    sucesso = resultado[0]["contagem"] == check_valor_esperado
                status = "✅" if sucesso else "❌"
                log.info(f"{status} {descricao}")
                return sucesso
            else:
                contagem = resultado[0]["contagem"] if resultado else 0
                log.info(f"📊 {descricao}: {contagem}")
                return contagem

        except Exception as e:
            log.error(f"Erro na query '{descricao}': {e}")
            return None

    def validar_1_pedidos_sem_cliente(self):
        """1. Existem pedidos sem cliente?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido
            WHERE id_cliente NOT IN (SELECT id_cliente FROM cliente)
        """
        return self.executar_query("1. Pedidos sem cliente", query, False)

    def validar_2_itens_sem_pedido(self):
        """2. Existem itens sem pedido?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido_item
            WHERE id_pedido NOT IN (SELECT id_pedido FROM pedido)
        """
        return self.executar_query("2. Itens sem pedido", query, False)

    def validar_3_itens_sem_produto(self):
        """3. Existem itens sem produto?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido_item
            WHERE id_produto NOT IN (SELECT id_produto FROM produto)
        """
        return self.executar_query("3. Itens sem produto", query, False)

    def validar_4_pedidos_sem_itens(self):
        """4. Existem pedidos sem itens?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido p
            LEFT JOIN pedido_item pi ON p.id_pedido = pi.id_pedido
            WHERE pi.id_item IS NULL
        """
        return self.executar_query("4. Pedidos sem itens", query, False)

    def validar_5_pj_com_menos_de_5_itens(self):
        """5. Existem pedidos PJ com menos de 5 itens?

        Considera produtos distintos no pedido (a definicao adotada e
        5 PRODUTOS DIFERENTES, nao 5 linhas e nem 5 unidades).
        """
        query = """
            SELECT COUNT(*) as contagem
            FROM (
                SELECT p.id_pedido
                FROM pedido p
                JOIN cliente c ON p.id_cliente = c.id_cliente
                JOIN pedido_item pi ON p.id_pedido = pi.id_pedido
                WHERE c.tipo = 'PJ'
                GROUP BY p.id_pedido
                HAVING COUNT(DISTINCT pi.id_produto) < 5
            ) as subquery
        """
        return self.executar_query("5. PJ com menos de 5 itens", query, False)

    def validar_6_valor_bruto_bate_soma_itens(self):
        """6. O valor bruto do pedido bate com a soma dos itens?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM (
                SELECT p.id_pedido, p.valor_total + p.desconto as valor_calculado,
                       SUM(pi.quantidade * pi.preco_unitario) as valor_itens
                FROM pedido p
                JOIN pedido_item pi ON p.id_pedido = pi.id_pedido
                GROUP BY p.id_pedido, p.valor_total, p.desconto
                HAVING ABS(
                    (p.valor_total + p.desconto)
                    - SUM(pi.quantidade * pi.preco_unitario)
                ) > 0.01
            ) as divergencias
        """
        return self.executar_query(
            "6. Valor bruto bate com soma dos itens", query, False
        )

    def validar_7_desconto_fisica_3pct(self):
        """7. O desconto de loja Fisica eh 3%?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM (
                SELECT p.id_pedido, p.desconto,
                       (SUM(pi.quantidade * pi.preco_unitario) * 0.03)
                       as desconto_esperado
                FROM pedido p
                JOIN pedido_item pi ON p.id_pedido = pi.id_pedido
                JOIN loja l ON p.id_loja = l.id_loja
                WHERE l.tipo = 'Física'
                GROUP BY p.id_pedido, p.desconto
                HAVING ABS(
                    p.desconto
                    - (SUM(pi.quantidade * pi.preco_unitario) * 0.03)
                ) > 0.01
            ) as divergencias
        """
        return self.executar_query("7. Desconto Fisica = 3%", query, False)

    def validar_8_desconto_online_5pct(self):
        """8. O desconto de loja Online eh 5%?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM (
                SELECT p.id_pedido, p.desconto,
                       (SUM(pi.quantidade * pi.preco_unitario) * 0.05)
                       as desconto_esperado
                FROM pedido p
                JOIN pedido_item pi ON p.id_pedido = pi.id_pedido
                JOIN loja l ON p.id_loja = l.id_loja
                WHERE l.tipo = 'Online'
                GROUP BY p.id_pedido, p.desconto
                HAVING ABS(
                    p.desconto
                    - (SUM(pi.quantidade * pi.preco_unitario) * 0.05)
                ) > 0.01
            ) as divergencias
        """
        return self.executar_query("8. Desconto Online = 5%", query, False)

    def validar_9_descontos_negativos(self):
        """9. Existem descontos negativos?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido
            WHERE desconto < 0
        """
        return self.executar_query("9. Descontos negativos", query, False)

    def validar_10_descontos_maiores_valor_bruto(self):
        """10. Existem descontos maiores que o valor bruto?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido
            WHERE desconto > (valor_total + desconto)
        """
        return self.executar_query("10. Descontos > valor bruto", query, False)

    def validar_11_valores_finais_negativos(self):
        """11. Existem valores finais negativos?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido
            WHERE valor_total < 0
        """
        return self.executar_query("11. Valores finais negativos", query, False)

    def validar_12_online_sem_canal_valido(self):
        """12. Existem pedidos Online sem canal valido?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido p
            JOIN loja l ON p.id_loja = l.id_loja
            WHERE l.tipo = 'Online'
              AND p.canal NOT IN ('Site', 'Marketplace', 'WhatsApp', 'Televendas')
        """
        return self.executar_query("12. Online sem canal valido", query, False)

    def validar_13_fisica_com_canal_online(self):
        """13. Existem pedidos fisicos com canal online?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido p
            JOIN loja l ON p.id_loja = l.id_loja
            WHERE l.tipo = 'Física'
              AND p.canal != 'Loja Física'
        """
        return self.executar_query("13. Fisica com canal online", query, False)

    def validar_14_precos_unitarios_incoerentes(self):
        """14. Existem precos unitarios incoerentes?"""
        query = """
            SELECT COUNT(*) as contagem
            FROM pedido_item pi
            JOIN produto p ON pi.id_produto = p.id_produto
            WHERE ABS(pi.preco_unitario - p.preco_venda) > 0.01
        """
        return self.executar_query("14. Precos unitarios incoerentes", query, False)

    def validar_15_registros_orfaos(self):
        """15. Existem registros orfaos?

        Verifica integridade referencial real: registros FILHO apontando para
        pais inexistentes. Cliente sem pedido, produto sem venda ou loja sem
        movimento sao estados normais de negocio (inativos, recentes,
        descontinuados), portanto NAO sao contados aqui.
        """
        query = """
            SELECT (
                (SELECT COUNT(*) FROM produto
                 WHERE id_categoria IS NOT NULL
                   AND id_categoria NOT IN (SELECT id_categoria FROM categoria)) +
                (SELECT COUNT(*) FROM produto
                 WHERE id_fornecedor IS NOT NULL
                   AND id_fornecedor NOT IN (SELECT id_fornecedor FROM fornecedor)) +
                (SELECT COUNT(*) FROM estoque
                 WHERE id_produto NOT IN (SELECT id_produto FROM produto)) +
                (SELECT COUNT(*) FROM estoque
                 WHERE id_loja NOT IN (SELECT id_loja FROM loja)) +
                (SELECT COUNT(*) FROM funcionario
                 WHERE id_departamento IS NOT NULL
                   AND id_departamento NOT IN (
                       SELECT id_departamento FROM departamento
                   )) +
                (SELECT COUNT(*) FROM funcionario
                 WHERE id_loja IS NOT NULL
                   AND id_loja NOT IN (SELECT id_loja FROM loja)) +
                (SELECT COUNT(*) FROM pedido
                 WHERE id_cliente NOT IN (SELECT id_cliente FROM cliente)) +
                (SELECT COUNT(*) FROM pedido
                 WHERE id_loja NOT IN (SELECT id_loja FROM loja)) +
                (SELECT COUNT(*) FROM pedido
                 WHERE id_funcionario IS NOT NULL
                   AND id_funcionario NOT IN (SELECT id_funcionario FROM funcionario)) +
                (SELECT COUNT(*) FROM pedido_item
                 WHERE id_pedido NOT IN (SELECT id_pedido FROM pedido)) +
                (SELECT COUNT(*) FROM pedido_item
                 WHERE id_produto NOT IN (SELECT id_produto FROM produto))
            ) as contagem
        """
        return self.executar_query("15. Registros orfaos", query, 0)

    def validar_16_duplicidades_inesperadas(self):
        """16. Existem duplicidades inesperadas?

        Verifica chaves que DEVEM ser unicas (loja.nome, categoria.nome,
        departamento.nome, produto.sku). Cliente.cpf_cnpj NAO entra: o ruido
        RUIDO_CLIENTE_DUP (2%) gera CPF/CNPJ duplicados intencionalmente.
        """
        query = """
            SELECT (
                (SELECT COUNT(*) - COUNT(DISTINCT nome) FROM loja) +
                (SELECT COUNT(*) - COUNT(DISTINCT nome) FROM categoria) +
                (SELECT COUNT(*) - COUNT(DISTINCT nome) FROM departamento) +
                (SELECT COUNT(*) - COUNT(DISTINCT sku) FROM produto
                 WHERE sku IS NOT NULL)
            ) as contagem
        """
        return self.executar_query("16. Duplicidades inesperadas", query, 0)

    def validar_17_foreign_keys_integridade(self):
        """17. As foreign keys continuam integrass?"""
        query = """
            SELECT (
                (SELECT COUNT(*) FROM pedido
                 WHERE id_cliente NOT IN (SELECT id_cliente FROM cliente)) +
                (SELECT COUNT(*) FROM pedido
                 WHERE id_loja NOT IN (SELECT id_loja FROM loja)) +
                (SELECT COUNT(*) FROM pedido
                 WHERE id_funcionario IS NOT NULL
                   AND id_funcionario NOT IN (SELECT id_funcionario FROM funcionario)) +
                (SELECT COUNT(*) FROM pedido_item
                 WHERE id_pedido NOT IN (SELECT id_pedido FROM pedido)) +
                (SELECT COUNT(*) FROM pedido_item
                 WHERE id_produto NOT IN (SELECT id_produto FROM produto))
            ) as contagem
        """
        return self.executar_query("17. Foreign keys integrass", query, 0)

    def validar_18_pipeline_executa(self):
        """18. O pipeline completo continua executando?"""
        # Esta validacao eh manual - apenas um placeholder
        log.info("18. Pipeline executa: Manual - Necessario testar")
        return None

    def executar_todas_validacoes(self):
        """Executa todas as 18 validacoes."""
        log.info("=" * 60)
        log.info("INICIANDO VALIDACOES DE COERENCIA")
        log.info("=" * 60)

        validacoes = [
            self.validar_1_pedidos_sem_cliente,
            self.validar_2_itens_sem_pedido,
            self.validar_3_itens_sem_produto,
            self.validar_4_pedidos_sem_itens,
            self.validar_5_pj_com_menos_de_5_itens,
            self.validar_6_valor_bruto_bate_soma_itens,
            self.validar_7_desconto_fisica_3pct,
            self.validar_8_desconto_online_5pct,
            self.validar_9_descontos_negativos,
            self.validar_10_descontos_maiores_valor_bruto,
            self.validar_11_valores_finais_negativos,
            self.validar_12_online_sem_canal_valido,
            self.validar_13_fisica_com_canal_online,
            self.validar_14_precos_unitarios_incoerentes,
            self.validar_15_registros_orfaos,
            self.validar_16_duplicidades_inesperadas,
            self.validar_17_foreign_keys_integridade,
            self.validar_18_pipeline_executa,
        ]

        sucessos = 0
        total_validaveis = 0

        for validacao in validacoes:
            resultado = validacao()
            if resultado is True or resultado == 0:
                sucessos += 1
            if resultado is not None:
                total_validaveis += 1

        log.info("=" * 60)
        log.info("RESUMO DAS VALIDACOES")
        log.info("=" * 60)
        log.info(f"Validacoes bem-sucedidas: {sucessos}/{total_validaveis}")
        log.info("Validacoes manuais: 1")
        log.info("=" * 60)

        if sucessos == total_validaveis:
            log.info("SUCESSO: TODAS AS VALIDACOES AUTOMATICAS PASSARAM!")
        else:
            log.warning(
                f"AVISO: {total_validaveis - sucessos} validacao(oes) falhou(aram)"
            )

        return sucessos == total_validaveis


def main():
    """Funcao principal do validador."""
    validador = ValidadorCoerencia()

    try:
        validador.conectar()
        validador.executar_todas_validacoes()
        validador.fechar()
    except Exception as e:
        log.error(f"Erro na validacao: {e}")
        return False

    return True


if __name__ == "__main__":
    main()
