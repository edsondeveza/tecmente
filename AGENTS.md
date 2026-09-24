# AGENTS.md

Projeto de estudos — TecMente: pipeline BI/DS com dados sintéticos (MySQL + CSVs). Scripts planos na raiz (um por papel) + pacote `src/tecmente` instalado em modo editável via Poetry. Documentação rica está em `README.md` (fluxo, papéis, exemplos) — consulte antes de supor.

## Executar (mudanças recentes importantes)

- **Sempre `poetry run`** e a partir da raiz do repo. `python <script>` do sistema falha por causa dos imports de `tecmente.*`.
- `poetry install` é obrigatório após clonar/mudar `pyproject.toml` — registra o pacote `src/tecmente` e o entry point `tecmente`.
- Pipeline completo: `poetry run python pipeline.py [--prever] [--bi]` (`--dias` default 3650 ≈ janela toda; a janela do gerador é `ANOS_HISTORICO`).
- CLI unificado (dispara os scripts da raiz via subprocess): `poetry run tecmente <gerar|extrair|tratar|visualizar|interativo|prever|bi|validar|pipeline> [args]`.
- Gerador roda em 2 passos obrigatórios e separados (`--clientes` e `--pedidos` são mutuamente exclusivos): primeiro `poetry run python gerador_mestre.py --clientes`, depois `--pedidos`. Gera 100k pedidos / 154 produtos / 10k clientes.
- Visualizadores: `poetry run python visualizador.py [--fonte csv|sql] [--dados <dir>]` (e `visualizador_interativo.py`) — override sem editar código; default é CSV mais recente em `data/`.

## Verificação

- Lint/format: `poetry run ruff check .` e `poetry run ruff format .`
- Testes: `poetry run pytest` (49 testes; `[tool.pytest.ini_options]` já injeta `--cov` com gate `--cov-fail-under=40`). Um teste só: `poetry run pytest tests/test_previsor.py -k Nome`.
- Checklist do usuário (17 validações de coerência no MySQL — rode antes de encerrar): `poetry run python validador_coerencia.py`. **Não apagar/renomear este script.**
- Sequência sugerida: `ruff check` → `ruff format` → `pytest`.

## Arquitetura

- Fluxo: `gerador_mestre.py` → `extrator.py` → `tratador.py` → `visualizador.py` / `visualizador_interativo.py`, com `previsor.py` e `analise_bi.py` opcionais via `pipeline.py`. Views analíticas ficam em `sql/tecmente_schema.sql`.
- **Fonte única de configuração de dados**: `src/tecmente/dados.py` expõe `FONTE`, `CAMINHO_BASE`, `configurar(fonte, base)`, `carregar_dados(nome_csv, query_sql)` e `fonte_atual()`. Todo novo código deve ler daqui, nunca hard-codear caminho/fonte.
- Gotcha: `from tecmente.dados import FONTE` congela o valor no momento do import; para ler a configuração **ativa** em runtime use `fonte_atual()` (o header de log dos visualizadores usa isso).
- `src/tecmente/tecmente_cli.py` mapeia comandos → scripts da raiz. `tests/conftest.py` redireciona `analise_bi.CAMINHO_*` para `tmp_path` (autouse) — não remover: sem ele os testes sobrescrevem `output/analises/` com dados fake.

## Gotchas do ambiente

- Requer MySQL local (DB `tecmente`, credenciais via `.env`/ambiente). O modo sombra `FONTE="sql"` consulta views; o CSV lê `data/*_tratado/`.
- UTF-8: ao inspecionar logs com Bash em Windows use `grep -a` (mojibake via pipe) ou redirecione para arquivo.
- `poetry run python -c` pode não imprimir/suprimir saída (MySQL/subprocess): prefira um script `.py` temporário na raiz e o remova ao final.
- `data/` e `output/` são gitignored (CSVs de dados, PNGs, relatórios não vão ao repo).
- `id_funcionario` no CSV tratado é Int64 nullable (nulos em branco, sem ".0"); `dia_semana` é texto PT em CSV e nas views.
- Commits: conventional commits em português (`fix(bi): ...`, `feat: ...`) — seguir o histórico. Só commitar quando o usuário pedir.
