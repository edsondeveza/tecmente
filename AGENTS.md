# AGENTS.md

Projeto de estudos — TecMente: pipeline BI/DS com dados sintéticos (MySQL + CSVs). Scripts planos na raiz (um por papel) + pacote `src/tecmente` instalado em modo editável via Poetry. Documentação rica está em `README.md` (fluxo, papéis, exemplos) — consulte antes de supor.

## Executar (mudanças recentes importantes)

- **Sempre `poetry run`** e a partir da raiz do repo. `python <script>` do sistema falha por causa dos imports de `tecmente.*`.
- `poetry install` é obrigatório após clonar/mudar `pyproject.toml` — registra o pacote `src/tecmente` e o entry point `tecmente`.
- Pipeline completo: `poetry run python pipeline.py [--prever] [--bi]` (`--dias` default 3650 ≈ janela toda; a janela do gerador é `ANOS_HISTORICO`).
- CLI unificado (dispara os scripts da raiz via subprocess): `poetry run tecmente <gerar|extrair|tratar|visualizar|interativo|prever|bi|validar|pipeline> [args]`. Flags do script alvo passam direto (`prever --dias_prever 3`).
- Previsor: `--backtest N` avalia N blocos de `--teste_dias` e compara com o baseline sazonal (mediana mês × dia da semana); o relatório sempre separa erro **diário** (MAE/RMSE/MAPE/WAPE) de erro do **horizonte** (soma do período). São leituras diferentes — não pegar só o MAPE.
- Gerador roda em 2 passos obrigatórios e separados (`--clientes` e `--pedidos` são mutuamente exclusivos): primeiro `poetry run python gerador_mestre.py --clientes`, depois `--pedidos`. Gera 100k pedidos / 154 produtos / 10k clientes.
- **Estoque é gerado no passo `--pedidos`**, não no `--clientes`: o saldo nasce da demanda real dos pedidos, então rodar só `--clientes` deixa a tabela `estoque` vazia por design (o passo avisa isso). Rodar `--clientes` limpa as tabelas — não use para "atualizar" o estoque.
- Visualizadores: `poetry run python visualizador.py [--fonte csv|sql] [--dados <dir>]` (e `visualizador_interativo.py`) — override sem editar código; default é CSV mais recente em `data/`.

## Verificação

- Lint/format: `poetry run ruff check .` e `poetry run ruff format .`
- Testes: `poetry run pytest` (143 testes; `[tool.pytest.ini_options]` injeta `--cov` com gate `--cov-fail-under=55`). Um teste só: `poetry run pytest tests/test_previsor.py -k Nome`. A cobertura **agrega `gerador_mestre` (29%)**, que só é testável nas funções puras (`_datas_snapshot`, `_demanda_janela`, `_nivel_estoque` em `tests/test_estoque.py`) porque o resto exige MySQL vivo — os módulos com lógica real ficam entre 64% e 96%.
- Checklist do usuário (19 verificações de coerência: 18 automáticas no MySQL + "pipeline executa", que confere os artefatos em `data/*_tratado/`): `poetry run python validador_coerencia.py`. **Não apagar/renomear este script.**
- Sequência sugerida: `ruff check` → `ruff format` → `pytest`.

## Arquitetura

- Fluxo: `gerador_mestre.py` → `extrator.py` → `tratador.py` → `visualizador.py` / `visualizador_interativo.py`, com `previsor.py` e `analise_bi.py` opcionais via `pipeline.py`. Views analíticas ficam em `sql/tecmente_schema.sql`.
- **Fonte única de configuração de dados**: `src/tecmente/dados.py` expõe `FONTE`, `CAMINHO_BASE`, `configurar(fonte, base)`, `resolver_caminho_dados(base)`, `carregar_dados(nome_csv, query_sql)` e `fonte_atual()`. Todo novo código deve ler daqui, nunca hard-codear caminho/fonte.
- Gotcha: `from tecmente.dados import FONTE` congela o valor no momento do import; para ler a configuração **ativa** em runtime use `fonte_atual()` (o header de log dos visualizadores usa isso).
- `src/tecmente/tecmente_cli.py` mapeia comandos → scripts da raiz. `tests/conftest.py` redireciona `analise_bi.CAMINHO_*` para `tmp_path` (autouse) — não remover: sem ele os testes sobrescrevem `output/analises/` com dados fake.

## Pendências conhecidas (verificadas em 2026-09-25, não corrigidas)

Duas falhas reais encontradas na auditoria. **Nenhuma foi corrigida** — foram
confirmadas com medição contra o banco e estão aqui para retomar.

### 1. `validador_coerencia.py` — sub-check "par faltando" é vacuo

`validar_19_estoque_temporal_coerente` (linha 378) tem 5 sub-checks. O terceiro é:

```sql
SELECT COUNT(*) FROM estoque WHERE data = (SELECT MAX(data) FROM estoque)
  AND id_produto NOT IN (SELECT e2.id_produto FROM estoque e2 WHERE e2.data = (SELECT MAX(data) FROM estoque))
```

O `NOT IN` seleciona exatamente o mesmo conjunto que a linha de fora — logo a
condição é uma contradição e **sempre vale 0**. Provado: apaguei 159 linhas da
data corrente dentro de transação e o valor continuou 0 (rollback restaurou as
924 linhas). O check de duplicados (`HAVING COUNT(*) > 1`) é real e funciona; só a
metade "sem par faltando" não é verificada, apesar de o docstring (linha 385)
prometer isso.

Isso importa porque par produto × loja ausente é justamente a falha que o modelo
temporal introduziu: se o gerador pulasse um produto, o `ROW_NUMBER()` do extrator
produziria 5 lojas em vez de 6 sem nenhum sinal.

**Correção sugerida:** comparar `COUNT(*)` de pares distintos em `data = MAX(data)`
contra `(SELECT COUNT(*) FROM produto) * (SELECT COUNT(*) FROM loja)`, que hoje dá
924 = 154 × 6. Considerar também um teste de regressão que apague um par e exija
que a validação falhe.

### 2. `gerador_mestre._demanda_janela` — soma meses inteiros, não a janela

`gerador_mestre.py:2200`. O docstring promete "soma as unidades vendidas na janela
`[inicio, inicio + dias)`", mas a implementação (linhas 2219-2234) soma os **meses
inteiros** que a janela toca. Medido para (loja 1, produto 1):

| Início da janela | Demanda real 30d | `_demanda_janela` | Razão |
| ---------------- | ---------------- | ----------------- | ----- |
| 1º dia do mês     | 30 / 15 / 57 …   | idem              | 1.00x |
| Meio do mês (15, 20) | 53 / 40      | 90 / 68           | 1.70x |

- **Snapshots mensais (dia 1): corretos** — o `break` cai certo, razão 1.00x.
- **Snapshot corrente (2026-09-25, dia 25): inflado ~1,7x** — soma setembro
  inteiro + outubro (≈0).

Efeito no snapshot corrente, que é o que o `extrator.py` lê e o que alimenta os
KPIs de `analise_bi.py`: cobertura mediana de **122 dias** onde o alvo de projeto é
~69 (`60 × fator médio 1.15`) — razão 1,77x, consistente com o 1,70x medido.
Logo os números **139 saudáveis / 9 ruptura / 5 excesso / 1 sem demanda** que o
README reporta estão enviesados para cima e devem ser recalculados após a correção.

**Pergunta de design antes de corrigir:** o snapshot corrente deveria usar janela
**retrospectiva** (30 dias atrás) em vez da `[inicio, inicio+30)` prevista no
código. A janela "à frente" não tem dado — o banco só vai até hoje, então a demanda
real de 30 dias à frente é 0, e a função só "funciona" porque a agregação por mês
puxa setembro para dentro. Isso é decisão de produto, não bug óbvio: confirmar com
o usuário antes de mudar.

Depois de corrigir os dois: regerar com os 2 passos, reextrair, `pytest`,
`validador_coerencia.py` e atualizar os números de cobertura/alertas no README.

## Estado em 2026-09-25 (fim da sessão)

- Fases 1–6 concluídas: higiene de docs, correções de bug, 143 testes, previsão
  com métricas de horizonte + baseline + backtest, estoque temporal, extrator
  fail-fast. `README.md` reconciliado com o código (5 afirmações erradas
  corrigidas, seções de CLI/fonte/testes criadas, versões sincronizadas).
- **Nada commitado.** Working tree com 5 modificados (`README.md`, `analise_bi.py`,
  `extrator.py`, `gerador_mestre.py`, `previsor.py`) — o restante das mudanças das
  fases anteriores já está no histórico ou foi descartado. Aguardando o usuário
  pedir commit.
- Última verificação verde: `ruff check` limpo, `ruff format --check` 23 arquivos,
  `pytest` 143 passando com 55,15% de cobertura, `validador_coerencia.py` 19/19,
  `pipeline.py --prever --bi` 6 etapas em 172,8 s.
- Estado do banco: 111.804 snapshots de estoque, 121 datas de 2016-10-01 a
  2026-09-25, 154 produtos × 6 lojas = 924 pares na data corrente, nenhum saldo
  negativo. Sem seed fixo — cada `--clientes`/`--pedidos` regenera números
  diferentes, então não espere reproduzir as métricas acima exatamente.
- **Antes de começar a próxima sessão:** leia "Pendências conhecidas" acima. São
  dois bugs medidos e não corrigidos, ambos com o caminho de correção sugerido.
  O primeiro é mecânico; o segundo exige decisão de produto do usuário.
- Pendência externa: Power BI / service account Daxus (fora do escopo do repo).

## Gotchas do ambiente

- Requer MySQL local (DB `tecmente`, credenciais via `.env`/ambiente). O modo sombra `FONTE="sql"` consulta views; o CSV lê `data/*_tratado/`.
- UTF-8: ao inspecionar logs com Bash em Windows use `grep -a` (mojibake via pipe) ou redirecione para arquivo.
- `poetry run python -c` pode não imprimir/suprimir saída (MySQL/subprocess): prefira um script `.py` temporário na raiz e o remova ao final.
- `data/` e `output/` são gitignored (CSVs de dados, PNGs, relatórios não vão ao repo).
- `id_funcionario` no CSV tratado é Int64 nullable (nulos em branco, sem ".0"); `dia_semana` é texto PT em CSV e nas views.
- Commits: conventional commits em português (`fix(bi): ...`, `feat: ...`) — seguir o histórico. Só commitar quando o usuário pedir.
