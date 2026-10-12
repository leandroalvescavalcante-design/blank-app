# Sistema de gestão industrial e logística — protótipo

Produto genérico (multiempresa por desenho), construído na sequência: decisões → matriz de barramento → KPIs →
grão → dimensões → fatos → camada semântica → telas de entrada → dashboard. Sem dado real de empresa: o dado
sintético incluído valida só a mecânica.

## Documentação por etapa

| Etapa | Documento |
|---|---|
| 0 — Inventário de decisões | [docs/00-inventario-decisoes.md](docs/00-inventario-decisoes.md) |
| 1 — Matriz de barramento | [docs/01-matriz-barramento.md](docs/01-matriz-barramento.md) |
| 2 — KPIs e fórmulas | [docs/02-kpis-formulas.md](docs/02-kpis-formulas.md) |
| 3 — Grão | [docs/03-grao.md](docs/03-grao.md) |
| 4 — Dimensões | [docs/04-dimensoes.md](docs/04-dimensoes.md) |
| 5 — Tabelas fato | [docs/05-tabelas-fato.md](docs/05-tabelas-fato.md) |
| 6 — Camada semântica | [docs/06-camada-semantica.md](docs/06-camada-semantica.md) · [semantica/metricas.yaml](semantica/metricas.yaml) |
| 7 — Telas de entrada | [docs/07-telas-entrada.md](docs/07-telas-entrada.md) · [entrada/layouts.yaml](entrada/layouts.yaml) |

## Rodar

```
pip install -r requirements-dev.txt
streamlit run streamlit_app.py
python -m pytest tests
python semantica/validar.py
```

O banco local fica em `dados/gestao.duckdb` (fora do git). Para outro caminho: variável `GESTAO_DB`.
