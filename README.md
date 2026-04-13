# TecMente — Pipeline de Dados para Estudo de Análise

Projeto de estudo construído do zero que simula um ambiente real de dados de um e-commerce de informática.

O pipeline cobre todas as etapas do fluxo de dados — da geração de dados sintéticos com ruído realista, passando pela extração controlada pelo DBA, tratamento pelo analista de dados, até a entrega final para consumo em BI.

O foco do projeto é reproduzir desafios reais de qualidade de dados e organização de processos encontrados em ambientes corporativos.

---

## Contexto

A **TecMente** é uma empresa fictícia de e-commerce de informática criada exclusivamente como ambiente de estudo. O objetivo é praticar SQL, Python e ferramentas de BI em um cenário realista, com dados que simulam os problemas encontrados em bases reais — CPFs com formatação inconsistente, e-mails com typo, telefones nulos, datas faltando.

---

## Tecnologias

| Camada                 | Tecnologia             |
| ---------------------- | ---------------------- |
| Banco de dados         | MySQL / MariaDB        |
| Linguagem              | Python 3.12            |
| Gerenciador de pacotes | Poetry 2.1.4           |
| Query e administração  | Azure Data Studio      |
| Manipulação de dados   | pandas                 |
| Geração de dados       | Faker                  |
| Conexão com banco      | mysql-connector-python |
| Visualização (Fase 1)  | matplotlib, seaborn    |
| Visualização (Fase 2)  | Plotly (planejado)     |

---

## Estrutura do projeto

```
tecmente/
├── gerador_mestre.py             ← popula o banco completo
├── extrator.py                   ← extração semanal de dados brutos (DBA)
├── tratador.py                   ← tratamento dos dados brutos (Analista)
├── vizualizador.py               ← geração de dashboards e gráficos (BI)
├── pyproject.toml                ← dependências do Poetry
├── sql/
│   └── tecmente_schema.sql    ← schema do banco (DBA executa primeiro)
├── data/
│   └── AAAA-MM-DD_tratado/       ← pasta gerada pelo tratador.py
│       ├── vendas_tratado.csv
│       ├── vendas_cancelados.csv
│       ├── produtos_estoque_tratado.csv
│       ├── clientes_tratado.csv
│       ├── equipe_lojas_tratado.csv
│       └── relatorio_qualidade.txt
└── output/
    ├── graficos/                 ← PNGs gerados pelo vizualizador.py
    └── relatorios/               ← HTML interativo (Fase 2 — Plotly)
```

> **Nota:** o `vizualizador.py` encontra automaticamente a pasta `_tratado`
> mais recente dentro de `data/`. Não é necessário alterar nenhum caminho
> no código entre execuções semanais.

---

## Fluxo do pipeline

```
tecmente_schema.sql
        ↓ DBA cria o banco
gerador_mestre.py
        ↓ DBA popula com dados sintéticos
extrator.py
        ↓ DBA extrai dados brutos semanalmente → data/AAAA-MM-DD/
tratador.py
        ↓ Analista trata e entrega ao BI → data/AAAA-MM-DD_tratado/
vizualizador.py
        ↓ BI gera dashboards → output/graficos/
```

---

## Separação de responsabilidades

### DBA

- Cria e mantém o schema do banco
- Popula o banco via `gerador_mestre.py`
- Executa a extração semanal via `extrator.py`
- Não realiza transformações nos dados — entrega o dado bruto

### Analista de Dados

- Recebe os CSVs brutos gerados pelo extrator
- Não tem acesso direto ao banco de produção
- Aplica limpeza, normalização, mascaramento e cálculos via `tratador.py`
- Entrega os dados tratados ao time de BI

### Time de BI

- Recebe os dados tratados e confiáveis
- Gera dashboards e relatórios via `vizualizador.py`
- Não se preocupa com origem ou qualidade dos dados

---

## Banco de dados

### Tabelas

| Tabela         | Descrição                                |
| -------------- | ---------------------------------------- |
| `categoria`    | Hierarquia de categorias de produtos     |
| `fornecedor`   | 40 distribuidoras reais do setor de TI   |
| `loja`         | 6 lojas da rede (físicas e online)       |
| `departamento` | Departamentos da empresa                 |
| `produto`      | 154 produtos com descrição por template  |
| `estoque`      | Quantidade por produto por loja          |
| `funcionario`  | 80 funcionários distribuídos nas lojas   |
| `cliente`      | 1.500 clientes PF e PJ                   |
| `pedido`       | 35.000 pedidos com sazonalidade e canais |
| `pedido_item`  | Itens de cada pedido                     |

### Views analíticas

| View                    | Descrição                                      |
| ----------------------- | ---------------------------------------------- |
| `vw_faturamento_mensal` | Receita bruta, líquida e cancelamentos por mês |
| `vw_ranking_produtos`   | Unidades, receita e lucro bruto por produto    |
| `vw_rfm`                | Recência, Frequência e Valor por cliente       |
| `vw_vendas_canal`       | Receita e ticket médio por canal e loja        |
| `vw_categorias`         | Performance por grupo de categoria             |

---

## Dados sintéticos — características

O `gerador_mestre.py` gera dados com **ruído realista intencional** para exercitar limpeza e qualidade de dados:

- CPF/CNPJ em 3 formatos diferentes (`123.456.789-00`, `12345678900`, `123_456_789_00`)
- ~3% de e-mails com typo no domínio (`.con` em vez de `.com`)
- ~8% de clientes sem telefone cadastrado
- ~12% de clientes sem data de nascimento
- ~4% de clientes compartilhando e-mail (compras em família)
- Sazonalidade de vendas: Black Friday (+80%), Natal (+50%), Volta às aulas (+30%)
- Distribuição de Pareto: 20% dos produtos respondem por ~60% das vendas
- Clientes segmentados: 8% super-ativos, 22% inativos, 70% normais

---

## Instalação

```bash
# 1. Clone o repositório
git clone https://github.com/edsondeveza/tecmente.git

)
cd tecmente

# 2. Instale as dependências
poetry install

# 3. Crie o banco de dados
# Execute tecmente_schema_v2.sql no Azure Data Studio ou HeidiSQL

# 4. Configure a senha do banco nos scripts
# Edite DB_CONFIG em cada script Python
```

---

## Uso

```bash
# Popula o banco completo
poetry run python gerador_mestre.py

# Extração semanal (todo o histórico)
poetry run python extrator.py

# Extração dos últimos 7 dias (teste)
poetry run python extrator.py --dias 7

# Tratamento dos dados de hoje
poetry run python tratador.py

# Tratamento de uma data específica
poetry run python tratador.py --data 2026-03-17

# Geração dos dashboards
poetry run python vizualizador.py
```

---

## Scripts

### `gerador_mestre.py`

Popula todas as tabelas do banco sem dependência de arquivo externo. Produtos, categorias, fornecedores, clientes, funcionários e pedidos são gerados internamente com templates por categoria.

**Limitação conhecida:** `random.seed(42)` fixo para reprodutibilidade. Remova o seed para gerar dados diferentes a cada execução.

**Status v1.0:** `DB_CONFIG['database']` corrigido para `'tecmente'`. ✅

### `extrator.py`

Responsabilidade exclusiva do DBA. Conecta ao banco, executa as queries e grava os CSVs exatamente como os dados estão armazenados — sem transformações, cálculos ou mascaramento.

Tratamento de erros por tipo dentro da função `_executar_e_gravar`:

- `mysql.connector.Error` — erros de banco (query inválida, timeout, conexão perdida)
- `OSError` — erros de arquivo (disco cheio, sem permissão de escrita)
- `logger.exception()` no `main()` — grava o traceback completo no log automaticamente

Códigos de saída documentados:

- `0` → sucesso
- `1` → execução com erros em uma ou mais etapas
- `2` → falha na conexão com o banco

### `tratador.py`

Responsabilidade do analista de dados. Recebe os CSVs brutos e aplica:

- Conversão de tipos (`str` → `datetime`, `str` → `float`)
- Normalização de CPF/CNPJ para formato numérico único
- Correção de e-mails com typo (`.con` → `.com`)
- Mascaramento de dados sensíveis (CPF, CNPJ, e-mail)
- Cálculos de negócio (subtotal, lucro bruto, margem %)
- Extração de componentes de data (ano, mês, trimestre, dia da semana)
- Classificação por faixa de preço e faixa salarial
- Separação de pedidos cancelados em arquivo próprio
- Relatório de qualidade (`relatorio_qualidade.txt`)

Tratamento de erros por tipo no `main()`:

- `pd.errors.EmptyDataError` — CSV vazio
- `pd.errors.ParserError` — CSV corrompido ou mal formatado
- `KeyError` — coluna esperada não encontrada (ex: DBA alterou nome de coluna)
- `OSError` — erro de leitura/gravação de arquivo
- `Exception` — rede de segurança para erros não previstos

**Status v1.0:** Pré-requisitos na docstring corrigidos. ✅

### `vizualizador.py`

Responsabilidade do time de BI. Lê os CSVs tratados (ou consulta as views do banco via chaveamento `FONTE = "csv" | "sql"`) e gera os dashboards em PNG.

O caminho dos dados é resolvido automaticamente — sempre aponta para a pasta `_tratado` mais recente em `data/`, sem necessidade de alterar o código entre execuções semanais.

Dashboards gerados (Fase 1 — Matplotlib/Seaborn):

| Arquivo                             | Descrição                                         |
| ----------------------------------- | ------------------------------------------------- |
| `d01_faturamento_por_loja.png`      | % de participação e valor absoluto por loja       |
| `d02_total_por_unidade.png`         | Faturamento, pedidos e ticket médio por unidade   |
| `d03_top_vendedores.png`            | Top 5 vendedores por loja em faturamento          |
| `d04_faturamento_mensal.png`        | Série temporal com bruto, líquido e cancelamentos |
| `d05_faturamento_por_categoria.png` | Faturamento por categoria com curva de Pareto     |
| `d06_produtos_ticket_medio.png`     | Top 20 produtos por receita e ticket médio        |
| `d07_rfm_scatter.png`               | Dispersão RFM — Recência × Frequência × Valor     |
| `d07_rfm_heatmap.png`               | Heatmap RFM — valor total por segmento R × F      |

**Status v2.0:** Todos os 7 dashboards implementados e validados. ✅

---

## Exemplos visuais

### 📊 Faturamento por Categoria (Pareto)

Análise baseada no princípio de Pareto, destacando as categorias responsáveis por maior parte da receita.

![Faturamento por Categoria](docs/imagens/d05_faturamento_por_categoria.png)

---

### 📈 Top Produtos — Faturamento e Ticket Médio

Comparação entre faturamento total e ticket médio por produto, destacando itens acima e abaixo da média.

![Top Produtos](docs/imagens/d06_produtos_ticket_medio.png)

## 📊 Insights dos Dashboards

### 🟠 Faturamento por Loja

- O faturamento está **bem distribuído entre as lojas**, sem grande concentração em uma única unidade.
- A variação entre a loja com maior e menor faturamento é relativamente pequena, indicando **equilíbrio operacional**.
- A Loja Campinas apresenta o maior faturamento, mas com diferença pouco significativa em relação às demais.
- O CD Osasco possui o menor faturamento, o que pode indicar seu papel mais logístico do que comercial.
- Esse cenário sugere uma operação madura, com boa distribuição de vendas e menor risco de dependência de uma única unidade.

---

### 🟡 Total por Unidade

- Diferença relevante entre unidades sugere assimetria na distribuição de vendas.
- Possível desalinhamento entre estoque e demanda em determinadas regiões.
- Rebalanceamento logístico pode aumentar eficiência e reduzir ruptura.

---

### 🟢 Top Vendedores

- Pequeno grupo de vendedores concentra grande parte do faturamento.
- Indício de alta performance individual, mas baixa padronização do time.
- Oportunidade de criar playbook comercial baseado nos top performers.

---

### 🔵 Faturamento Mensal

- Presença de sazonalidade nas vendas, indicando períodos de maior e menor demanda.
- Possibilidade de campanhas estratégicas em meses de baixa performance.
- Crescimento consistente pode indicar maturidade operacional ou expansão da base de clientes.

---

### 🟣 Faturamento por Categoria (Pareto)

- Aplicação do princípio de Pareto: poucas categorias concentram a maior parte do faturamento.
- Categorias como Hardware e Periféricos dominam a receita.
- Estratégias recomendadas:
  - Priorizar estoque e disponibilidade dessas categorias
  - Criar campanhas de upsell e cross-sell
- Categorias de baixo desempenho podem ser revistas ou reposicionadas.

---

### 🟤 Produtos por Ticket Médio

- Produtos com alto faturamento nem sempre possuem alto ticket médio.
- Identificação de produtos premium vs produtos de volume.
- Estratégias possíveis:
  - Aumentar ticket médio com combos e kits
  - Incentivar venda de produtos de maior valor agregado
- Produtos acima da média representam oportunidades de maior margem.

---

### ⚫ RFM (Recência, Frequência e Valor) _(em desenvolvimento)_

- Segmentação de clientes baseada em comportamento de compra.
- Permitirá identificar:
  - Clientes fiéis
  - Clientes em risco
  - Clientes de alto valor
- Base para campanhas personalizadas e estratégias de retenção.

---

## 💡 Resumo Executivo

A análise evidencia concentração de receita em categorias, produtos e vendedores específicos, reforçando a importância de estratégias focadas em Pareto, otimização comercial e gestão de mix de produtos para maximizar resultados.

## Padrões adotados

- **PEP 8** — estilo de código (snake_case, 79 caracteres, imports organizados)
- **PEP 257** — docstrings com `Args:`, `Returns:` e `Raises:`
- **PEP 484** — type hints em todas as funções

---

## Status do pipeline

| Etapa               | Script                   | Status       | Validado em |
| ------------------- | ------------------------ | ------------ | ----------- |
| Schema do banco     | `tecmente_schema_v2.sql` | ✅ Concluído | 2026-03-19  |
| Geração de dados    | `gerador_mestre.py`      | ✅ Concluído | 2026-03-19  |
| Extração DBA        | `extrator.py`            | ✅ Concluído | 2026-03-19  |
| Tratamento Analista | `tratador.py`            | ✅ Concluído | 2026-03-19  |
| Entrega ao BI       | `vizualizador.py`        | ✅ Concluído | 2026-03-25  |

**Resultado da última execução validada (2026-03-25):**

```
extrator.py     → 106.729 linhas extraídas em 4.7s — 0 erros
tratador.py     → 100.614 linhas ativas (33.773 pedidos) + 3.617 cancelados
vizualizador.py → 8 PNGs gerados — 0 erros
```

---

## Próximos passos

### Evoluções planejadas

- [x] Entrega ao BI — Python (matplotlib / seaborn)
- [x] Visualizações estáticas — 7 dashboards em PNG
- [ ] Visualizações interativas — Plotly (Fase 2)
- [ ] Power BI — após conclusão da formação Daxus
- [ ] Análise preditiva de vendas (Machine Learning)
- [ ] Automatização da extração via agendamento (Task Scheduler / cron)

---

## Observações

Este projeto foi desenvolvido com fins exclusivamente educacionais. Todos os dados são sintéticos e gerados automaticamente — nenhum dado real de pessoas ou empresas foi utilizado. Os CNPJs dos fornecedores são fictícios gerados pela biblioteca Faker.
