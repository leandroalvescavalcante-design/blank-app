"""Testes de MECÂNICA da ferramenta inteira sobre a simulação sintética de 8 semanas.

Sintético valida fórmula, fluxo e somatório — não parâmetro. Os valores esperados aqui são consequências
lógicas do cenário (ex.: 2 movimentos omitidos → 2 exceções), não "números bons".
"""
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml

from app import admin, carga, metricas, planejamento
from app.db import conectar
from dados_sinteticos import simulacao

RAIZ = Path(__file__).resolve().parent.parent
F = metricas.Filtros(simulacao.INICIO, simulacao.INICIO + timedelta(days=simulacao.DIAS - 1))


@pytest.fixture(scope="module")
def banco(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("sim") / "sim.duckdb"
    con = conectar(caminho)
    carga.garantir_modelo(con)
    res = simulacao.carregar(con, "teste")
    assert all(r.status == "ACEITA" for _, r in res), [(n, r.validacao.tabela_erros()) for n, r in res if r.status != "ACEITA"]
    yield con, caminho
    con.close()


@pytest.fixture
def con(banco):
    return banco[0]


# --------------------------------------------------------------------------- simulação e integridade

def test_simulacao_e_deterministica():
    a = simulacao.gerar().arquivos()
    b = simulacao.gerar().arquivos()
    assert [n for n, _ in a] == [n for n, _ in b]
    assert all(x.equals(y) for (_, x), (_, y) in zip(a, b))


def test_reconciliacao_acusa_exatamente_os_movimentos_omitidos(con):
    exc = con.execute("SELECT DISTINCT data FROM vm_reconciliacao WHERE excecao = 1 ORDER BY 1").fetchall()
    assert [d[0] for d in exc] == sorted(simulacao.DIAS_OMITIDOS)
    assert metricas.calcular(con, "K04", F).valor == 2


def test_k04_nao_verificavel_sem_vespera(con):
    vespera = simulacao.INICIO - timedelta(days=1)
    r = metricas.calcular(con, "K04", metricas.Filtros(vespera, vespera))
    assert r.valor is None and r.motivo_nulo.startswith("não verificável")


# --------------------------------------------------------------------------- ciclo do pedido (F11)

def test_ciclo_conserva_quantidade_por_linha(con):
    df = con.execute("""SELECT numero_pedido, item, max(qtd_pedida_linha) AS pedida, sum(qtd_alocada) AS alocada
                        FROM fato_ciclo_pedido WHERE status_final != 'cancelada_cliente' GROUP BY ALL""").df()
    assert (abs(df["pedida"] - df["alocada"]) < 1e-6).all()


def test_otif_e_por_linha_e_corte_reprova(con):
    linhas_com_corte = con.execute("""SELECT count(*) FROM vm_ciclo_linha l
        WHERE num = 1 AND EXISTS (SELECT 1 FROM fato_ciclo_pedido f WHERE f.numero_pedido = l.numero_pedido
                                  AND f.item = l.item AND f.status_final = 'cortada')""").fetchone()[0]
    assert linhas_com_corte == 0


def test_demanda_nao_inclui_corte_proprio(con):
    # F07 só tem eventos do cliente: soma líquida = quantidade pedida das linhas no ciclo
    f07 = con.execute("SELECT sum(delta_qtd) FROM fato_evento_pedido_venda").fetchone()[0]
    f11 = con.execute("""SELECT sum(p) FROM (SELECT max(qtd_pedida_linha) p FROM fato_ciclo_pedido
                         WHERE status_final != 'cancelada_cliente' GROUP BY numero_pedido, item)""").fetchone()[0]
    assert abs(f07 - f11) < 1e-6


# --------------------------------------------------------------------------- planejamento (F12)

def test_ponto_de_pedido_nulo_sem_acuracidade(con):
    df = con.execute("SELECT apto_reposicao, ss, motivo_nulo FROM fato_planejamento_sku").df()
    assert df.loc[~df["apto_reposicao"], "ss"].isna().all()
    assert df.loc[~df["apto_reposicao"], "motivo_nulo"].str.startswith("acuracidade").all()


def test_teto_de_vida_util_e_alerta_de_lote_inviavel(con):
    r = con.execute("""SELECT p.teto_lote, p.lote_minimo, p.alerta_lote_inviavel, u.fator_para_base
                       FROM fato_planejamento_sku p JOIN dim_sku s USING (sku_sk)
                       JOIN sku_unidade u ON u.sku_sk = p.sku_sk AND u.e_unidade_palete = 'S'
                       WHERE s.sku = 'LEITE-L' AND p.data = (SELECT max(data) FROM fato_planejamento_sku)""").fetchone()
    teto, minimo, alerta, palete = r
    assert teto % palete == 0           # teto arredondado PARA BAIXO a múltiplo de palete
    assert alerta and teto < minimo     # lote mínimo do fornecedor acima do que a vida útil comporta


def test_tudo_no_sintetico_e_provisorio(con):
    assert con.execute("SELECT bool_and(provisorio) FROM fato_planejamento_sku").fetchone()[0]


def test_classificacao_syntetos_boylan():
    assert planejamento._padrao(1.0, 0.2) == "SUAVE"
    assert planejamento._padrao(1.0, 0.8) == "ERRATICA"
    assert planejamento._padrao(2.0, 0.2) == "INTERMITENTE"
    assert planejamento._padrao(2.0, 0.8) == "IRREGULAR"


def test_classe_abc_pareto():
    c = planejamento._classe_abc({"a": 70, "b": 15, "c": 10, "d": 5})
    assert c == {"a": "A", "b": "A", "c": "B", "d": "C"}


# --------------------------------------------------------------------------- camada semântica

def test_registro_e_yaml_tem_as_mesmas_metricas():
    yaml_ids = set(yaml.safe_load((RAIZ / "semantica" / "metricas.yaml").read_text())["metricas"])
    assert yaml_ids == set(metricas.REGISTRO)


def test_toda_dimensao_permitida_existe_na_visao(con):
    for kid, ex in metricas.REGISTRO.items():
        cols = metricas._colunas(con, ex.visao)
        faltam = [d for d in metricas.permitidas(kid) if metricas.COLUNA[d] not in cols]
        assert not faltam, (kid, faltam)


@pytest.mark.parametrize("kid", list(metricas.REGISTRO))
def test_metrica_calcula_e_abre_por_toda_dimensao(con, kid):
    r = metricas.calcular(con, kid, F)
    assert r.valor is not None or r.motivo_nulo
    assert r.provisorio  # sintético
    for d in metricas.permitidas(kid) + ["data"]:
        metricas.drill(con, kid, F, d)


def test_razao_e_razao_das_somas_no_drill(con):
    total = metricas.calcular(con, "K01", F).valor
    df = con.execute("SELECT sum(num) / sum(den) * 100 FROM vm_contagem WHERE data BETWEEN ? AND ?",
                     [F.inicio, F.fim]).fetchone()[0]
    assert abs(total - df) < 1e-9


def test_nulo_com_motivo_sem_dados(con):
    vazio = metricas.Filtros(date(2020, 1, 1), date(2020, 1, 31))
    r = metricas.calcular(con, "K01", vazio)
    assert r.valor is None and r.motivo_nulo == "sem dados no período"


def test_filtro_que_nao_se_aplica_e_declarado(con):
    r = metricas.calcular(con, "K08", metricas.Filtros(F.inicio, F.fim, cliente="C01"))
    assert "cliente" in r.filtros_ignorados


def test_gatilhos_listam_decisao_e_dono(con):
    g = metricas.gatilhos(con, F)
    assert set(g["métrica"]) >= {"K04", "K10"}
    assert g["dono"].notna().all() and g["decisão"].notna().all()


# --------------------------------------------------------------------------- expurgo do sintético

def test_expurgo_apaga_so_sintetico_e_registra(tmp_path):
    con = conectar(tmp_path / "expurgo.duckdb")
    carga.garantir_modelo(con)
    from dados_sinteticos.gerar import cadastros
    real = carga.registrar(con, "cad_site", cadastros()["cad_site"].assign(site="REAL1"), usuario="gestor")
    assert real.status == "ACEITA"
    for nome, df in list(simulacao.gerar().cadastros().items())[:3]:
        carga.registrar(con, nome, df, usuario="t", sintetico=True)
    assert admin.resumo_sinteticos(con)[0] == 3
    admin.limpar_sinteticos(con, "gestor")
    assert admin.resumo_sinteticos(con) == (0, 0)
    assert con.execute("SELECT count(*) FROM bruto_carga WHERE NOT sintetico").fetchone()[0] == 1
    assert con.execute("SELECT site FROM dim_site WHERE site_sk > 0").fetchall() == [("REAL1",)]
    assert con.execute("SELECT n_cargas FROM bruto_expurgo").fetchone()[0] == 3


# --------------------------------------------------------------------------- painel

def test_painel_roda_com_dados(banco, monkeypatch):
    from streamlit.testing.v1 import AppTest
    _, caminho = banco
    monkeypatch.setenv("GESTAO_DB", str(caminho))
    at = AppTest.from_string(
        f"import sys; sys.path.insert(0, {str(RAIZ)!r})\nfrom app import telas\ntelas.pagina_painel()", default_timeout=180)
    at.run()
    assert not at.exception, at.exception
    assert any("Ações disparadas" in h.value for h in at.subheader)
