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
| 8 — Painel e fechamento | [docs/08-painel-e-fechamento.md](docs/08-painel-e-fechamento.md) — inclui como trocar o fictício pelo real |
| Celular (Android, com e sem Wi-Fi) | [docs/09-celular.md](docs/09-celular.md) |

## Instalar (equipe)

Baixe o pacote ZIP, descompacte numa pasta fixa e siga o [LEIA-ME_INSTALACAO.txt](LEIA-ME_INSTALACAO.txt):
no Windows, dois cliques em `instalador/instalar_windows.bat`; no Mac/Linux, `bash instalador/instalar_mac_linux.sh`.
O instalador verifica o Python (no Windows, instala se faltar), cria o ambiente, instala as bibliotecas,
cria o atalho e oferece carregar o cenário de treinamento.

## Rodar (desenvolvimento)

```
pip install -r requirements-dev.txt
python -m app.admin carregar-simulacao --usuario SEU_NOME     # cenário sintético de 8 semanas (opcional)
streamlit run streamlit_app.py
python -m app.movel.servidor                                   # app do celular (HTTPS 8443; certificado em http 8080)
python -m app.admin definir-pin --matricula M001               # PIN de quem usa o celular
python -m pytest tests                                         # 78 testes de mecânica
python semantica/validar.py                                    # consistência da camada semântica
python -m app.admin limpar-sinteticos --usuario SEU_NOME --confirmar   # antes de carregar dado real
```

![Painel](docs/painel.png)

O banco local fica em `dados/gestao.duckdb` (fora do git). Para outro caminho: variável `GESTAO_DB`.
