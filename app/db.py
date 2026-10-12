from pathlib import Path

import duckdb

from app.config import ARQ_BRUTO_SQL, caminho_banco


def conectar(caminho: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Abre o banco e garante a camada bruta. caminho=':memory:' para testes."""
    caminho = str(caminho or caminho_banco())
    if caminho != ":memory:":
        Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(caminho)
    con.execute(ARQ_BRUTO_SQL.read_text(encoding="utf-8"))
    return con
