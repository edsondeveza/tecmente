# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

TecMente is a study project: a data pipeline for a fictional electronics e-commerce, covering data generation (synthetic with realistic noise), extraction (DBA), cleaning/masking (Analyst), BI dashboards, and — the part this file focuses on — **ML sales forecasting** (`previsor.py`) plus its automation and CI.

The full project scope is documented in [README.md](README.md). This file covers the ML layer added in Fase D, which is not described in README in code-touching detail.

## Development commands

The project uses **Poetry** (Python 3.12). Use the `.venv` at the repo root (Windows) or `poetry run`.

```bash
poetry install                          # install deps into the environment
poetry run ruff check --exclude .venv . # lint (E, F, I rules)
poetry run ruff format --exclude .venv . # format (double-quote style)
poetry run pytest -q                    # all tests
poetry run pytest tests/test_pipeline.py -q   # single test file
poetry run pytest tests/test_pipeline.py::TestResolverCaminhoDados -q  # single class
```

CI [.github/workflows/ci.yml](.github/workflows/ci.yml) runs ruff check + ruff format --check + pytest on `main`/PRs. Keep formatting in line with `[tool.ruff]` in [pyproject.toml](pyproject.toml): line length 88, double quotes, `E501` ignored only in `gerador_mestre.py` and `pipeline.py`.

## Running the ML pipeline

```bash
poetry run python previsor.py                  # full forecast: 14 days ahead, 30 test days
poetry run python previsor.py --dias_prever 7  # forecast next week
poetry run python previsor.py --teste_dias 60  # more validation days
poetry run python pipeline.py --prever         # entire ETL→dashboards→ML flow
```

`previsor.py` is the optional final stage of [pipeline.py](pipeline.py), invoked with `--prever`; otherwise the pipeline stops at the Plotly dashboards.

## ML architecture (`previsor.py`)

Daily revenue forecasting using **Random Forest regression** (scikit-learn), designed didactically as an ordered series of pure, testable functions:

1. **Load latest treated data** — `resolver_pasta_tratada()` delegates to `visualizador.resolver_caminho_dados()` to find the newest `data/AAAA-MM-DD_tratado/` folder. It reads `vendas_tratado.csv`.
2. **Aggregate daily revenue** — `agregar_diario()` sums `subtotal` per `data_pedido` date → a `(data, receita)` series.
3. **Feature engineering** — `construir_features()` adds calendar features (`dia_semana`, `mes`, `dia_mes`, `semana_ano`) plus **lag features** of revenue at `LAGS = (1, 7, 14)` days (captures trend + weekly seasonality). Rows with incomplete lags are dropped.
4. **Temporal split** — `dividir_treino_teste()` takes the last N days as test **without shuffling** (time order is respected, critical for time series).
5. **Train** — `treinar_modelo()`: `RandomForestRegressor(n_estimators=300, max_depth=10, random_state=42, n_jobs=-1)`.
6. **Recursive forecast** — `prever_futuro()` predicts day by day, feeding back its own previous predictions into the lag features when no real observation exists (multi-step recursive prediction).
7. **Evaluate + report** — `avaliar_modelo()` computes **MAE, RMSE, MAPE** on the test set; `gerar_relatorio()` writes metrics to a text file; `gerar_grafico()` produces an interactive Plotly chart.

### Key module-level contracts

- `LAGS: tuple[int, ...]` — lag windows; changing it changes feature count.
- `COLUNAS_FEATURES: list[str]` — exact feature column order. Must stay in sync with feature construction so sklearn aligns features at predict time (avoids the "X does not have valid feature names" warning).
- Function signatures use type hints (`tuple[pd.DataFrame, pd.Series, ...]`, `pd.DataFrame`, `list[float]`); keep them on any change.

### Integration points with `visualizador.py`

`previsor.py` imports `CAMINHO_BASE`, `CAMINHO_GRAFICOS`, `PALETA`, and `resolver_caminho_dados` from [visualizador.py](visualizador.py). Reuses the same data-folder lookup and color palette so the forecast chart matches the other dashboards. Changing those names/values in `visualizador.py` affects the ML module.

### Outputs

- `output/predicoes/previsao_vendas.csv` — forecast rows (data, previsao)
- `output/predicoes/relatorio_previsao.txt` — metrics + summary
- `output/graficos/previsao_vendas.html` — interactive Plotly chart

## Tests

Tests live in [tests/](tests/). **`previsor.py` has no dedicated test file yet** — existing tests cover `tratador.py` data-cleaning functions and `pipeline.py`/`visualizador.py` folder resolution. The ML functions (`agregar_diario`, `construir_features`, `dividir_treino_teste`, `avaliar_modelo`) are pure and well-suited to tests; the pattern to follow is in [tests/test_tratador.py](tests/test_tratador.py) (class-based `TestXxx` groups, `pytest.raises`, no DB required).

## Configuration

DB credentials come from environment variables via [config.py](config.py) (loaded from a root `.env`, not committed). See [.env.example](.env.example). `DB_NAME` defaults to `tecmente`. `previsor.py` itself reads processed CSVs, not the DB, so it does not require running MySQL.