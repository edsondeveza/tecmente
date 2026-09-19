# -*- coding: utf-8 -*-
"""
tratador.py  —  Papel: Analista de Dados
=========================================
Recebe os arquivos CSV brutos gerados pelo extrator.py (DBA) e aplica
limpeza, normalização, mascaramento e enriquecimento antes de entregar
ao time de BI.

O que este script faz
----------------------
1. Lê os 4 CSVs brutos da pasta de extração
2. Trata cada arquivo (limpeza, tipos, cálculos, máscaras)
3. Grava os arquivos tratados em uma pasta separada
4. Gera um relatório de qualidade dos dados

O que NÃO é responsabilidade deste script
-------------------------------------------
- Conectar ao banco de dados           → extrator.py (DBA)
- Montar dashboards ou gráficos        → time de BI
- Alterar dados de origem              → nunca

Estrutura de pastas esperada
-----------------------------
extracoes/
    2025-03-17/               ← gerado pelo extrator.py
        vendas.csv
        produtos_estoque.csv
        clientes.csv
        equipe_lojas.csv
        extracao.log
    2025-03-17_tratado/       ← gerado por este script
        vendas_tratado.csv
        vendas_cancelados.csv
        produtos_estoque_tratado.csv
        clientes_tratado.csv
        equipe_lojas_tratado.csv
        relatorio_qualidade.txt

Uso
---
    # Trata a extração de hoje
    poetry run python tratador.py

    # Trata uma extração específica
    poetry run python tratador.py --data 2025-03-10

    # Define pasta raiz diferente
    poetry run python tratador.py --pasta extracoes

Pré-requisitos
--------------
    poetry add pandas
    # ou: pip install pandas

Autor: Edson Deveza — Analista de Dados
Versão: 1.0
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import ENCODING

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# =============================================================================
# CONFIGURAÇÕES
# =============================================================================

# Pasta raiz — relativa ao diretório do script
PASTA_RAIZ: Path = Path(__file__).parent / "data"


# =============================================================================
# RELATÓRIO DE QUALIDADE
# =============================================================================


class RelatorioQualidade:
    """Acumula métricas de qualidade durante o tratamento e gera o relatório.

    Registra para cada arquivo:
    - Quantas linhas tinham problema e foram corrigidas
    - Quantas linhas foram descartadas
    - Quais colunas tinham nulos e em que proporção

    Args:
        caminho: Caminho completo do arquivo .txt a ser gerado.
    """

    def __init__(self, caminho: str) -> None:
        self.caminho = caminho
        self.linhas: list[str] = []
        self._inicio = datetime.now()

    def secao(self, titulo: str) -> None:
        """Adiciona um cabeçalho de seção ao relatório."""
        self.linhas.append("")
        self.linhas.append("─" * 60)
        self.linhas.append(f"  {titulo}")
        self.linhas.append("─" * 60)

    def registro(self, descricao: str, valor: str | int | float) -> None:
        """Adiciona uma linha de métrica ao relatório."""
        self.linhas.append(f"  {descricao:<45} {valor}")

    def nulos(self, df: pd.DataFrame, nome_arquivo: str) -> None:
        """Registra a contagem de nulos por coluna de um DataFrame."""
        self.secao(f"Nulos — {nome_arquivo}")
        nulos = df.isnull().sum()
        nulos = nulos[nulos > 0]
        if len(nulos) == 0:
            self.linhas.append("  Nenhum nulo encontrado.")
        for col, n in nulos.items():
            pct = n / len(df) * 100
            self.linhas.append(f"  {col:<35} {n:>5} ({pct:.1f}%)")

    def salvar(self) -> None:
        """Grava o relatório em disco."""
        elapsed = (datetime.now() - self._inicio).total_seconds()
        cabecalho = [
            "=" * 60,
            "  TecMente — Relatório de Qualidade de Dados",
            f"  Gerado em : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Duração   : {elapsed:.1f}s",
            "=" * 60,
        ]
        with open(self.caminho, "w", encoding="utf-8") as f:
            f.write("\n".join(cabecalho + self.linhas))
        log.info("Relatório salvo: %s", os.path.basename(self.caminho))


# =============================================================================
# FUNÇÕES DE MASCARAMENTO
# (movidas do extrator.py — responsabilidade do analista, não do DBA)
# =============================================================================


def mascarar_cpf_cnpj(valor) -> str:
    """Mascara CPF ou CNPJ preservando apenas os 2 últimos dígitos.

    Trata os 3 formatos inconsistentes vindos do banco:
    pontuado (123.456.789-00), sem pontuação (12345678900)
    e com sublinhado (123_456_789_00).

    Args:
        valor: String com CPF ou CNPJ, ou NaN/None.

    Returns:
        String mascarada ou string vazia se nulo.

    Exemplos:
        >>> mascarar_cpf_cnpj('123.456.789-00')
        '***.***.***-00'
        >>> mascarar_cpf_cnpj('12345678900')
        '*********00'
    """
    # pandas pode passar NaN — trata como vazio
    if pd.isna(valor) or not str(valor).strip():
        return ""
    v = str(valor)
    # Substitui todos os dígitos por * exceto os 2 últimos
    return re.sub(r"\d", "*", v[:-2]) + v[-2:]


def mascarar_email(valor) -> str:
    """Mascara e-mail preservando a inicial e o domínio.

    Args:
        valor: String com e-mail, ou NaN/None.

    Returns:
        String mascarada ou string vazia se nulo.

    Exemplos:
        >>> mascarar_email('joao.silva@gmail.com')
        'j***@gmail.com'
        >>> mascarar_email('invalido')
        '***'
    """
    if pd.isna(valor) or not str(valor).strip():
        return ""
    v = str(valor).strip()
    if "@" not in v:
        return "***"
    local, dominio = v.rsplit("@", 1)
    return f"{local[0]}***@{dominio}"


# =============================================================================
# FUNÇÕES DE NORMALIZAÇÃO
# =============================================================================


def normalizar_cpf_cnpj(valor) -> str:
    """Remove toda pontuação do CPF/CNPJ, deixando só os dígitos.

    Padroniza os 3 formatos do banco para um único formato numérico,
    facilitando comparações e validações posteriores.

    Args:
        valor: CPF/CNPJ em qualquer formato.

    Returns:
        String contendo apenas os dígitos, ou vazio se nulo.

    Exemplos:
        >>> normalizar_cpf_cnpj('123.456.789-00')
        '12345678900'
        >>> normalizar_cpf_cnpj('123_456_789_00')
        '12345678900'
    """
    if pd.isna(valor) or not str(valor).strip():
        return ""
    return re.sub(r"[^\d]", "", str(valor))


def corrigir_email(valor) -> tuple[str, bool]:
    """Corrige typos comuns em e-mail e sinaliza se é válido.

    Correção aplicada: ``.con`` → ``.com`` (erro de digitação frequente
    gerado pelo ruído do banco simulado).

    Args:
        valor: String com o e-mail bruto.

    Returns:
        Tupla ``(email_corrigido, é_válido)`` onde ``é_válido`` indica
        se o e-mail tem formato aceitável após a correção.

    Exemplos:
        >>> corrigir_email('joao@gmail.con')
        ('joao@gmail.com', True)
        >>> corrigir_email('invalido')
        ('invalido', False)
    """
    if pd.isna(valor) or not str(valor).strip():
        return ("", False)

    email = str(valor).strip()

    # Corrige o typo .con → .com
    email = re.sub(r"\.con$", ".com", email, flags=re.IGNORECASE)

    # Valida formato mínimo: algo@algo.algo
    valido = bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", email))

    return (email, valido)


# =============================================================================
# TRATAMENTO POR ARQUIVO
# =============================================================================


def tratar_clientes(
    caminho_entrada: str,
    caminho_saida: str,
    relatorio: RelatorioQualidade,
) -> pd.DataFrame:
    """Trata o arquivo de clientes.

    Operações realizadas:
    - Converte datas para datetime
    - Normaliza CPF/CNPJ para formato numérico
    - Corrige e valida e-mails
    - Preenche sobrenome nulo com string vazia
    - Calcula idade e dias desde o cadastro
    - Mascara CPF/CNPJ e e-mail

    Args:
        caminho_entrada: Caminho do CSV bruto.
        caminho_saida:   Caminho do CSV tratado.
        relatorio:       Instância do relatório de qualidade.

    Returns:
        DataFrame tratado.
    """
    # ── 1. Leitura ─────────────────────────────────────────────────────────
    # pd.read_csv lê o arquivo e já monta o DataFrame.
    # dtype=str garante que CPF/CNPJ não perca zeros à esquerda.
    df = pd.read_csv(caminho_entrada, encoding=ENCODING, dtype=str)

    relatorio.secao("clientes.csv — estado inicial")
    relatorio.registro("Linhas lidas", len(df))
    relatorio.nulos(df, "clientes.csv (bruto)")

    linhas_inicial = len(df)

    # ── 2. Conversão de tipos de data ──────────────────────────────────────
    # O pandas lê datas como string por padrão.
    # pd.to_datetime converte; errors='coerce' transforma valores inválidos
    # em NaT (Not a Time) em vez de lançar erro — importante para dados sujos.
    df["data_cadastro"] = pd.to_datetime(df["data_cadastro"], errors="coerce")
    df["data_nascimento"] = pd.to_datetime(df["data_nascimento"], errors="coerce")

    # ── 3. Limpeza de sobrenome ─────────────────────────────────────────────
    # Sobrenome nulo é dado opcional (cliente PJ), não dado faltante.
    # fillna('') substitui NaN por string vazia.
    df["sobrenome"] = df["sobrenome"].fillna("")

    # ── 4. Normalização de CPF/CNPJ ────────────────────────────────────────
    # apply() aplica a função linha a linha na coluna.
    # Resultado: todos os documentos ficam só com dígitos.
    df["cpf_cnpj_normalizado"] = df["cpf_cnpj"].apply(normalizar_cpf_cnpj)

    # ── 5. Correção e validação de e-mail ──────────────────────────────────
    # apply() retorna uma série de tuplas (email_corrigido, válido).
    # zip(*...) desempacota as tuplas em duas listas separadas.
    resultados_email = df["email"].apply(corrigir_email)
    df["email"] = [r[0] for r in resultados_email]
    df["email_valido"] = [r[1] for r in resultados_email]

    emails_corrigidos = (
        df["email"].str.endswith(".com") & df["email"].str.contains("@")
    ).sum()

    # ── 6. Cálculos de negócio ─────────────────────────────────────────────
    # datetime.now() retorna o momento atual.
    # A subtração entre dois datetime retorna um Timedelta.
    # .dt.days extrai o número de dias do Timedelta.
    # // 365 divide inteiramente para obter anos completos.
    hoje = pd.Timestamp.now()

    df["idade"] = (
        (hoje - df["data_nascimento"]).dt.days // 365
        # where() mantém NaN onde a data é nula
    ).where(df["data_nascimento"].notna())

    df["dias_desde_cadastro"] = ((hoje - df["data_cadastro"]).dt.days).where(
        df["data_cadastro"].notna()
    )

    # ── 7. Mascaramento para entrega ao BI ─────────────────────────────────
    # Cria colunas novas com os dados mascarados.
    # As colunas originais são removidas — o BI não recebe o dado sensível.
    df["cpf_cnpj_mascarado"] = df["cpf_cnpj_normalizado"].apply(mascarar_cpf_cnpj)
    df["email_mascarado"] = df["email"].apply(mascarar_email)

    # Remove colunas originais sensíveis
    df = df.drop(columns=["cpf_cnpj", "email"])

    # ── 8. Ordenação final ─────────────────────────────────────────────────
    df = df.sort_values(["data_cadastro", "id_cliente"]).reset_index(drop=True)

    # ── 9. Gravação ────────────────────────────────────────────────────────
    # index=False evita que o pandas grave o índice interno como coluna extra.
    df.to_csv(caminho_saida, index=False, encoding=ENCODING)

    # ── 10. Métricas para o relatório ──────────────────────────────────────
    relatorio.secao("clientes.csv — resultado do tratamento")
    relatorio.registro("Linhas de entrada", linhas_inicial)
    relatorio.registro("Linhas na saída", len(df))
    relatorio.registro("E-mails corrigidos (.con→.com)", emails_corrigidos)
    relatorio.registro("E-mails inválidos (flagged)", (~df["email_valido"]).sum())
    relatorio.registro("Idades calculadas", df["idade"].notna().sum())
    relatorio.registro("Idades não calculadas (sem data)", df["idade"].isna().sum())

    log.info("clientes_tratado.csv — %d linhas", len(df))
    return df


def tratar_vendas(
    caminho_entrada: str,
    caminho_saida: str,
    caminho_cancelados: str,
    relatorio: RelatorioQualidade,
) -> pd.DataFrame:
    """Trata o arquivo de vendas.

    Operações realizadas:
    - Converte data_pedido para datetime
    - Remove colunas 100% nulas (id_funcionario, obs)
    - Calcula subtotal, lucro_bruto e margem por item
    - Extrai ano, mês, trimestre e dia da semana
    - Separa pedidos cancelados em arquivo próprio

    Args:
        caminho_entrada:    Caminho do CSV bruto.
        caminho_saida:      Caminho do CSV de pedidos ativos tratados.
        caminho_cancelados: Caminho do CSV de pedidos cancelados.
        relatorio:          Instância do relatório de qualidade.

    Returns:
        DataFrame de pedidos ativos tratados.
    """
    # ── 1. Leitura ─────────────────────────────────────────────────────────
    df = pd.read_csv(caminho_entrada, encoding=ENCODING)

    relatorio.secao("vendas.csv — estado inicial")
    relatorio.registro("Linhas lidas", len(df))
    relatorio.registro("Pedidos únicos", df["id_pedido"].nunique())
    relatorio.nulos(df, "vendas.csv (bruto)")

    linhas_inicial = len(df)

    # ── 2. Conversão de data ───────────────────────────────────────────────
    df["data_pedido"] = pd.to_datetime(df["data_pedido"], errors="coerce")

    # ── 3. Remoção de colunas 100% nulas ───────────────────────────────────
    # dropna(axis=1) opera em colunas (axis=0 seria linhas).
    # how='all' remove só se TODOS os valores são nulos.
    # Registra quais colunas foram removidas antes de remover.
    colunas_antes = set(df.columns)
    df = df.dropna(axis=1, how="all")
    colunas_removidas = colunas_antes - set(df.columns)

    relatorio.secao("vendas.csv — colunas removidas (100% nulas)")
    for col in sorted(colunas_removidas):
        relatorio.registro(col, "removida")

    # ── 4. Cálculos de negócio ─────────────────────────────────────────────
    # Operações vetorizadas — o pandas aplica em toda a coluna de uma vez,
    # muito mais eficiente do que um loop linha a linha.
    df["subtotal"] = (df["quantidade"] * df["preco_venda"]).round(2)

    # OBS: O desconto já está aplicado no valor_total do banco de dados.
    # O campo 'desconto' no pedido contém o valor absoluto em R$ do desconto
    # aplicado (3% para lojas físicas, 5% para lojas online).
    # NÃO é necessário reaplicar o desconto aqui - o valor_total já é o valor final.

    df["lucro_bruto"] = (df["subtotal"] - df["quantidade"] * df["preco_custo"]).round(2)

    # where() aplica condição: se custo > 0, calcula; caso contrário NaN.
    # Evita divisão por zero em produtos sem custo cadastrado.
    df["margem_pct"] = (
        (df["lucro_bruto"] / df["subtotal"] * 100).where(df["subtotal"] > 0).round(2)
    )

    # ── 5. Extração de componentes de data ────────────────────────────────
    # O acessor .dt expõe propriedades de datetime em uma Series.
    # day_name() retorna o nome do dia em inglês — traduzimos manualmente.
    dias_pt = {
        "Monday": "Segunda",
        "Tuesday": "Terça",
        "Wednesday": "Quarta",
        "Thursday": "Quinta",
        "Friday": "Sexta",
        "Saturday": "Sábado",
        "Sunday": "Domingo",
    }
    df["ano"] = df["data_pedido"].dt.year
    df["mes"] = df["data_pedido"].dt.month
    df["trimestre"] = df["data_pedido"].dt.quarter
    df["dia_semana"] = df["data_pedido"].dt.day_name().map(dias_pt)

    # ── 6. Separação de cancelados ─────────────────────────────────────────
    # Filtro booleano: df[condição] retorna só as linhas onde condição é True.
    # ~ é o operador NOT — inverte o booleano.
    mask_cancelado = df["status"] == "Cancelado"
    df_cancelados = df[mask_cancelado].copy()
    df_ativos = df[~mask_cancelado].copy()

    df_cancelados.to_csv(caminho_cancelados, index=False, encoding=ENCODING)
    df_ativos.to_csv(caminho_saida, index=False, encoding=ENCODING)

    # ── 7. Métricas para o relatório ──────────────────────────────────────
    relatorio.secao("vendas.csv — resultado do tratamento")
    relatorio.registro("Linhas de entrada", linhas_inicial)
    relatorio.registro("Pedidos ativos (saída)", df_ativos["id_pedido"].nunique())
    relatorio.registro("Pedidos cancelados", df_cancelados["id_pedido"].nunique())
    relatorio.registro("Itens ativos (linhas)", len(df_ativos))
    relatorio.registro("Itens cancelados (linhas)", len(df_cancelados))
    relatorio.registro(
        "Receita total (ativos)", f"R$ {df_ativos['subtotal'].sum():,.2f}"
    )
    relatorio.registro(
        "Lucro bruto total (ativos)", f"R$ {df_ativos['lucro_bruto'].sum():,.2f}"
    )
    relatorio.registro("Margem média (%)", f"{df_ativos['margem_pct'].mean():.1f}%")

    log.info(
        "vendas_tratado.csv — %d linhas (%d pedidos ativos)",
        len(df_ativos),
        df_ativos["id_pedido"].nunique(),
    )
    log.info(
        "vendas_cancelados.csv — %d linhas (%d pedidos cancelados)",
        len(df_cancelados),
        df_cancelados["id_pedido"].nunique(),
    )
    return df_ativos


def tratar_produtos_estoque(
    caminho_entrada: str,
    caminho_saida: str,
    relatorio: RelatorioQualidade,
) -> pd.DataFrame:
    """Trata o arquivo de produtos e estoque.

    Operações realizadas:
    - Converte ultima_atualizacao para datetime
    - Calcula margem bruta e percentual de margem
    - Classifica produtos por faixa de preço (ticket)
    - Calcula estoque total consolidado por produto

    Args:
        caminho_entrada: Caminho do CSV bruto.
        caminho_saida:   Caminho do CSV tratado.
        relatorio:       Instância do relatório de qualidade.

    Returns:
        DataFrame tratado.
    """
    df = pd.read_csv(caminho_entrada, encoding=ENCODING)

    relatorio.secao("produtos_estoque.csv — estado inicial")
    relatorio.registro("Linhas lidas", len(df))
    relatorio.registro("Produtos únicos", df["id_produto"].nunique())
    relatorio.nulos(df, "produtos_estoque.csv (bruto)")

    # ── Conversão de data ──────────────────────────────────────────────────
    df["ultima_atualizacao"] = pd.to_datetime(df["ultima_atualizacao"], errors="coerce")

    # ── Cálculos de margem ─────────────────────────────────────────────────
    df["margem_bruta"] = (df["preco_venda"] - df["preco_custo"]).round(2)
    df["margem_pct"] = (
        (df["margem_bruta"] / df["preco_venda"] * 100)
        .where(df["preco_venda"] > 0)
        .round(2)
    )

    # ── Classificação por faixa de preço (ticket) ─────────────────────────
    # pd.cut() divide uma coluna numérica em intervalos (bins).
    # labels define o nome de cada faixa.
    # right=True significa que o limite direito de cada intervalo é incluído.
    df["faixa_preco"] = pd.cut(
        df["preco_venda"],
        bins=[0, 50, 300, 900, float("inf")],
        labels=["LOW", "MID", "HIGH", "ULTRA"],
        right=True,
    )

    # ── Estoque total por produto (consolidado de todas as lojas) ──────────
    # groupby agrupa por produto e sum() soma as quantidades.
    # O resultado é uma Series com id_produto como índice.
    # map() usa esse resultado para criar uma nova coluna no df original.
    estoque_total = df.groupby("id_produto")["estoque_qtd"].sum()
    df["estoque_total_rede"] = df["id_produto"].map(estoque_total)

    df.to_csv(caminho_saida, index=False, encoding=ENCODING)

    relatorio.secao("produtos_estoque.csv — resultado")
    relatorio.registro("Produtos únicos", df["id_produto"].nunique())
    relatorio.registro("Sem estoque (qtd = 0)", (df["estoque_qtd"] == 0).sum())
    relatorio.registro("Margem média (%)", f"{df['margem_pct'].mean():.1f}%")
    for faixa in ["LOW", "MID", "HIGH", "ULTRA"]:
        qtd = (df["faixa_preco"] == faixa).sum()
        relatorio.registro(f"  Faixa {faixa}", f"{qtd} registros")

    log.info(
        "produtos_estoque_tratado.csv — %d linhas (%d produtos)",
        len(df),
        df["id_produto"].nunique(),
    )
    return df


def tratar_equipe_lojas(
    caminho_entrada: str,
    caminho_saida: str,
    relatorio: RelatorioQualidade,
) -> pd.DataFrame:
    """Trata o arquivo de equipe e lojas.

    Operações realizadas:
    - Converte data_admissao para datetime
    - Normaliza e mascara CPF
    - Calcula tempo de casa em anos e meses
    - Classifica faixa salarial

    Args:
        caminho_entrada: Caminho do CSV bruto.
        caminho_saida:   Caminho do CSV tratado.
        relatorio:       Instância do relatório de qualidade.

    Returns:
        DataFrame tratado.
    """
    df = pd.read_csv(caminho_entrada, encoding=ENCODING, dtype=str)

    relatorio.secao("equipe_lojas.csv — estado inicial")
    relatorio.registro("Linhas lidas", len(df))
    relatorio.nulos(df, "equipe_lojas.csv (bruto)")

    # ── Conversão de tipos ─────────────────────────────────────────────────
    df["data_admissao"] = pd.to_datetime(df["data_admissao"], errors="coerce")
    df["salario"] = pd.to_numeric(df["salario"], errors="coerce")

    # ── Normalização e mascaramento de CPF ────────────────────────────────
    df["cpf_normalizado"] = df["cpf"].apply(normalizar_cpf_cnpj)
    df["cpf_mascarado"] = df["cpf_normalizado"].apply(mascarar_cpf_cnpj)
    df = df.drop(columns=["cpf"])

    # ── Cálculos de tempo de casa ──────────────────────────────────────────
    hoje = pd.Timestamp.now()
    delta = hoje - df["data_admissao"]

    df["tempo_casa_anos"] = (delta.dt.days // 365).where(df["data_admissao"].notna())
    df["tempo_casa_meses"] = (delta.dt.days // 30).where(df["data_admissao"].notna())

    # ── Classificação de faixa salarial ───────────────────────────────────
    # pd.cut com bins numéricos e labels de texto
    df["faixa_salarial"] = pd.cut(
        df["salario"],
        bins=[0, 3000, 6000, 9000, float("inf")],
        labels=["Júnior", "Pleno", "Sênior", "Especialista"],
        right=True,
    )

    df.to_csv(caminho_saida, index=False, encoding=ENCODING)

    relatorio.secao("equipe_lojas.csv — resultado")
    relatorio.registro("Funcionários", len(df))
    relatorio.registro("Salário médio", f"R$ {df['salario'].mean():,.2f}")
    relatorio.registro(
        "Tempo médio de casa (anos)", f"{df['tempo_casa_anos'].mean():.1f}"
    )
    for faixa in ["Júnior", "Pleno", "Sênior", "Especialista"]:
        qtd = (df["faixa_salarial"] == faixa).sum()
        relatorio.registro(f"  Faixa {faixa}", f"{qtd} funcionários")

    log.info("equipe_lojas_tratado.csv — %d linhas", len(df))
    return df


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    """Orquestra o tratamento de todos os arquivos."""

    parser = argparse.ArgumentParser(
        description="Tratamento de dados brutos — TecMente (papel: Analista)"
    )
    parser.add_argument(
        "--data",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Data da extração a tratar (AAAA-MM-DD). Padrão: hoje.",
    )
    parser.add_argument(
        "--pasta",
        type=str,
        default=str(PASTA_RAIZ),
        help=f"Pasta raiz das extrações (padrão: {PASTA_RAIZ}).",
    )
    args = parser.parse_args()

    pasta_entrada = os.path.join(args.pasta, args.data)
    pasta_saida = os.path.join(args.pasta, f"{args.data}_tratado")

    # Valida pasta de entrada
    if not os.path.exists(pasta_entrada):
        log.error("ERRO: Pasta de entrada não encontrada: %s", pasta_entrada)
        log.error("Execute primeiro o extrator.py para a data %s", args.data)
        sys.exit(1)

    os.makedirs(pasta_saida, exist_ok=True)

    log.info("=" * 60)
    log.info("TecMente — Tratador de Dados v1.0  (Analista)")
    log.info("=" * 60)
    log.info("Entrada : %s", os.path.abspath(pasta_entrada))
    log.info("Saída   : %s", os.path.abspath(pasta_saida))
    log.info("-" * 60)

    relatorio = RelatorioQualidade(os.path.join(pasta_saida, "relatorio_qualidade.txt"))

    erros: list[str] = []

    # Mapa de arquivos: (arquivo_entrada, função, args_extras)
    tarefas = [
        (
            "clientes.csv",
            tratar_clientes,
            [os.path.join(pasta_saida, "clientes_tratado.csv"), relatorio],
        ),
        (
            "vendas.csv",
            tratar_vendas,
            [
                os.path.join(pasta_saida, "vendas_tratado.csv"),
                os.path.join(pasta_saida, "vendas_cancelados.csv"),
                relatorio,
            ],
        ),
        (
            "produtos_estoque.csv",
            tratar_produtos_estoque,
            [os.path.join(pasta_saida, "produtos_estoque_tratado.csv"), relatorio],
        ),
        (
            "equipe_lojas.csv",
            tratar_equipe_lojas,
            [os.path.join(pasta_saida, "equipe_lojas_tratado.csv"), relatorio],
        ),
    ]

    for nome_arquivo, funcao, args_extras in tarefas:
        caminho_entrada = os.path.join(pasta_entrada, nome_arquivo)
        if not os.path.exists(caminho_entrada):
            msg = f"Arquivo não encontrado: {nome_arquivo}"
            log.warning("AVISO: %s", msg)
            erros.append(msg)
            continue
        try:
            funcao(caminho_entrada, *args_extras)

        except pd.errors.EmptyDataError:
            msg = f"Arquivo vazio ou sem dados: {nome_arquivo}"
            log.error("ERRO: %s", msg)
            erros.append(msg)

        except pd.errors.ParserError as e:
            msg = f"Arquivo corrompido ou mal formatado ({nome_arquivo}): {e}"
            log.error("ERRO: %s", msg)
            erros.append(msg)

        except KeyError as e:
            msg = f"Coluna esperada não encontrada em {nome_arquivo}: {e}"
            log.error("ERRO: %s", msg)
            erros.append(msg)

        except OSError as e:
            msg = f"Erro de leitura/gravação em {nome_arquivo}: {e}"
            log.error("ERRO: %s", msg)
            erros.append(msg)

        except Exception as e:
            # Captura qualquer outro erro inesperado não previsto acima
            msg = f"Erro inesperado em {nome_arquivo}: {e}"
            log.error("ERRO: %s", msg)
            erros.append(msg)

    relatorio.salvar()

    log.info("-" * 60)
    if erros:
        log.warning("Concluído com %d aviso(s)/erro(s):", len(erros))
        for e in erros:
            log.warning("  %s", e)
    else:
        log.info("Tratamento concluído com sucesso.")
        log.info("Próximo passo: entregar pasta _tratado ao time de BI.")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
