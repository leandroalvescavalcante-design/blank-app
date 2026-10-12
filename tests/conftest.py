import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import carga  # noqa: E402
from app.db import conectar  # noqa: E402
from dados_sinteticos.gerar import sequencia_demo  # noqa: E402


@pytest.fixture
def con():
    c = conectar(":memory:")
    carga.garantir_modelo(c)
    return c


@pytest.fixture
def con_demo(con):
    for nome, df in sequencia_demo():
        r = carga.registrar(con, nome, df, usuario="teste", sintetico=True, nome_arquivo=nome)
        assert r.status == "ACEITA", (nome, r.validacao.tabela_erros())
    return con
