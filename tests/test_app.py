"""Fumaça das telas: cada página roda sem exceção, num banco vazio e com o cenário sintético carregado."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
PAGINAS = ["pagina_painel", "pagina_upload", "pagina_contagem", "pagina_investigacao", "pagina_cargas", "pagina_layouts"]


def _rodar(pagina: str) -> AppTest:
    at = AppTest.from_string(
        f"import sys; sys.path.insert(0, {str(RAIZ)!r})\nfrom app import telas\ntelas.{pagina}()", default_timeout=120)
    at.session_state["usuario"] = "teste"
    return at.run()


@pytest.fixture
def banco_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("GESTAO_DB", str(tmp_path / "teste.duckdb"))


@pytest.mark.parametrize("pagina", PAGINAS)
def test_pagina_roda_em_banco_vazio(banco_tmp, pagina):
    at = _rodar(pagina)
    assert not at.exception, at.exception


def test_demo_pela_tela_e_paginas_com_dados(banco_tmp):
    at = _rodar("pagina_cargas")
    botao = next(b for b in at.button if b.label == "Carregar cenário sintético")
    at = botao.click().run()
    assert not at.exception, at.exception
    assert any("carga(s) aceita(s)" in m.value for m in at.markdown)
    for pagina in PAGINAS:
        assert not _rodar(pagina).exception, pagina


def test_entrada_principal_roda(banco_tmp):
    at = AppTest.from_file(str(RAIZ / "streamlit_app.py"), default_timeout=120).run()
    assert not at.exception, at.exception
