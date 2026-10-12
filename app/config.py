import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQ_LAYOUTS = RAIZ / "entrada" / "layouts.yaml"
ARQ_BRUTO_SQL = RAIZ / "sql" / "bruto.sql"
ARQ_MODELO_SQL = RAIZ / "sql" / "modelo.sql"
ARQ_VISOES_SQL = RAIZ / "sql" / "visoes.sql"
ARQ_METRICAS = RAIZ / "semantica" / "metricas.yaml"
def caminho_banco() -> Path:
    """Lido a cada conexão (não na importação), para que GESTAO_DB valha também em testes."""
    return Path(os.environ.get("GESTAO_DB", RAIZ / "dados" / "gestao.duckdb"))

# Protótipo monoempresa: a coluna existe em toda tabela, o isolamento real (login, permissão por tenant) vem com a migração para PostgreSQL.
EMPRESA_PADRAO = "DEMO"

# Confiabilidade por fonte (Etapa 4, regra aprovada). Formulário web não distingue leitura de código
# de digitação, então fica "MEDIA" até haver integração com leitor.
CONFIABILIDADE = {"ERP": "ALTA", "UPLOAD": "MEDIA", "FORMULARIO": "MEDIA", "ESTIMADO": "BAIXA", "DERIVADO": None}
