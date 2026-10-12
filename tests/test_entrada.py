"""Testes de MECÂNICA da entrada (frente 1). Dados sintéticos: não validam parâmetro."""
from datetime import datetime

import pandas as pd

from app import carga, consultas
from app.transform import sk
from dados_sinteticos.gerar import D1, movimentos_d1, saldo_d1


def _fato(con, tabela):
    return con.execute(f"SELECT * FROM {tabela}").df()


# --------------------------------------------------------------------------- reconciliação (K04)

def test_reconciliacao_acusa_so_o_movimento_faltante(con_demo):
    resumo = consultas.resumo_reconciliacao(con_demo)
    d0, d1 = resumo.iloc[0], resumo.iloc[1]
    assert pd.isna(d0["excecoes"]) and d0["situacao"].startswith("não verificável")
    assert d1["excecoes"] == 1
    exc = consultas.excecoes_reconciliacao(con_demo)
    assert exc[["sku", "lote", "endereco"]].values.tolist() == [["IOG-170", "L1002", "A-01-02"]]
    assert exc["dif_reconciliacao"].iloc[0] == -48  # o retroativo (−12) é explicado; o faltante (−48) não


# --------------------------------------------------------------------------- idempotência

def test_mesmo_conteudo_e_duplicado_mesmo_em_outra_ordem(con_demo):
    antes = len(_fato(con_demo, "fato_movimento_estoque"))
    r1 = carga.registrar(con_demo, "mov_estoque", movimentos_d1(), usuario="t")
    r2 = carga.registrar(con_demo, "mov_estoque", movimentos_d1().iloc[::-1], usuario="t")
    assert (r1.status, r2.status) == ("DUPLICADA", "DUPLICADA")
    assert len(_fato(con_demo, "fato_movimento_estoque")) == antes


def test_arquivo_sobreposto_ignora_linhas_repetidas(con_demo):
    df = movimentos_d1().head(2)
    r = carga.registrar(con_demo, "mov_estoque", df, usuario="t")
    assert (r.status, r.n_novas, r.n_repetidas, r.n_correcoes) == ("ACEITA", 0, 2, 0)


def test_correcao_gera_estorno_e_nao_sobrescreve(con_demo):
    df = movimentos_d1()
    df.loc[0, "qtd"] = "-200"  # NF-5001 corrigida de −240 para −200
    r = carga.registrar(con_demo, "mov_estoque", df, usuario="t")
    assert (r.status, r.n_correcoes, r.n_repetidas) == ("ACEITA", 1, 4)
    f = _fato(con_demo, "fato_movimento_estoque")
    linhas = f[f["documento_numero"] == "NF-5001"].sort_values("carga_id")
    assert linhas["tipo_registro"].tolist() == ["NORMAL", "ESTORNO", "CORRECAO"]
    assert linhas["qtd"].tolist() == [-240, 240, -200]
    assert linhas["qtd"].sum() == -200


# --------------------------------------------------------------------------- poka-yoke

def test_tudo_ou_nada_recusa_o_arquivo_inteiro(con_demo):
    antes = len(_fato(con_demo, "fato_saldo_diario"))
    df = saldo_d1()
    df.loc[0, "qtd_bloqueada"] = "999999"
    r = carga.registrar(con_demo, "saldo_estoque", df, usuario="t")
    assert r.status == "RECUSADA"
    assert len(_fato(con_demo, "fato_saldo_diario")) == antes
    erros = consultas.erros_da_carga(con_demo, r.carga_id)
    assert "bloqueado + reservado" in erros["erros"].iloc[0]


def test_sinal_incoerente_com_tipo_de_movimento(con_demo):
    df = movimentos_d1().head(1).assign(qtd="240", documento_numero="NF-X")
    r = carga.registrar(con_demo, "mov_estoque", df, usuario="t")
    assert r.status == "RECUSADA"
    assert "sinal" in r.validacao.tabela_erros()["erro"].iloc[0]


def test_lista_fechada_e_membro_inferido(con_demo):
    ruim = movimentos_d1().head(1).assign(documento_numero="NF-Y", motivo="INVENTADO")
    assert carga.registrar(con_demo, "mov_estoque", ruim, usuario="t").status == "RECUSADA"
    novo = movimentos_d1().head(1).assign(documento_numero="NF-Z", sku="SKU-NOVO", lote="")
    assert carga.registrar(con_demo, "mov_estoque", novo, usuario="t").status == "ACEITA"
    inferido = con_demo.execute("SELECT inferido FROM dim_sku WHERE sku = 'SKU-NOVO'").fetchone()[0]
    assert inferido is True


def test_lote_conforme_cadastro_do_sku(con_demo):
    sem_lote = movimentos_d1().head(1).assign(documento_numero="NF-L1", lote="")
    com_lote = movimentos_d1().iloc[[3]].assign(documento_numero="OP-L2", lote="X1")  # CX-PAP não controla lote
    assert carga.registrar(con_demo, "mov_estoque", sem_lote, usuario="t").status == "RECUSADA"
    assert carga.registrar(con_demo, "mov_estoque", com_lote, usuario="t").status == "RECUSADA"


def test_colunas_fora_do_layout_recusam(con_demo):
    df = movimentos_d1().assign(coluna_estranha="x")
    r = carga.registrar(con_demo, "mov_estoque", df, usuario="t")
    assert r.status == "RECUSADA" and "fora do layout" in r.validacao.erros_arquivo[0]


# --------------------------------------------------------------------------- fotografia

def test_fotografia_nova_substitui_a_anterior_por_inteiro(con_demo):
    df = saldo_d1()
    df = df[df["sku"] != "CX-PAP"].assign(instante_extracao="2026-10-07 06:00:00")
    assert carga.registrar(con_demo, "saldo_estoque", df, usuario="t").status == "ACEITA"
    skus = con_demo.execute(
        "SELECT DISTINCT k.sku FROM fato_saldo_diario s JOIN dim_sku k USING (sku_sk) WHERE s.data_saldo = ?",
        [D1]).fetchall()
    assert ("CX-PAP",) not in skus
    versoes = con_demo.execute("SELECT versoes FROM cobertura_saldo WHERE data_saldo = ?", [D1]).fetchone()[0]
    assert versoes == 2


# --------------------------------------------------------------------------- contagem e investigação

def _contagem(numero, recontagem, qtd, sistema, sku="IOG-170", lote="L1001", endereco="A-01-01"):
    return pd.DataFrame([{
        "numero_contagem": numero, "numero_recontagem": str(recontagem), "endereco": endereco, "sku": sku,
        "lote": lote, "qtd_contada": str(qtd), "qtd_sistema_congelada": str(sistema),
        "instante_congelamento": "2026-10-07 08:00:00", "instante_contagem": f"2026-10-07 08:{10 + recontagem}:00",
        "matricula": "M001"}])


def test_recontagem_final_derivada_e_investigacao_atribui_etapa_ao_ajuste(con_demo):
    assert carga.registrar(con_demo, "contagem", _contagem("CNT-1", 0, 230, 240), usuario="t").status == "ACEITA"
    assert carga.registrar(con_demo, "contagem", _contagem("CNT-1", 1, 228, 240), usuario="t").status == "ACEITA"
    finais = con_demo.execute("SELECT numero_recontagem FROM fato_contagem WHERE e_final").fetchall()
    assert finais == [(1,)]
    pend = consultas.divergencias_pendentes(con_demo)
    assert pend[["numero_contagem", "diferenca"]].values.tolist() == [["CNT-1", -12]]

    inv = pd.DataFrame([{"numero_contagem": "CNT-1", "endereco": "A-01-01", "sku": "IOG-170", "lote": "L1001",
                         "motivo": "DIV_SEPARACAO", "matricula": "M002"}])
    assert carga.registrar(con_demo, "investigacao_divergencia", inv, usuario="t").status == "ACEITA"
    assert consultas.divergencias_pendentes(con_demo).empty

    ajuste = movimentos_d1().head(1).assign(
        documento_tipo="CONTAGEM", documento_numero="CNT-1", tipo_movimento="AJUSTE_NEGATIVO", qtd="-12",
        data_movimento="2026-10-07", instante_lancamento="2026-10-07 09:00:00")
    assert carga.registrar(con_demo, "mov_estoque", ajuste, usuario="t").status == "ACEITA"
    motivo = con_demo.execute(
        """SELECT m.codigo, m.etapa_origem FROM fato_movimento_estoque f JOIN dim_motivo m USING (motivo_sk)
           WHERE f.documento_numero = 'CNT-1'""").fetchone()
    assert motivo == ("DIV_SEPARACAO", "SEPARACAO")


def test_motivo_de_investigacao_so_aceita_processo_divergencia(con_demo):
    inv = pd.DataFrame([{"numero_contagem": "CNT-9", "endereco": "A-01-01", "sku": "IOG-170", "lote": "L1001",
                         "motivo": "BAIXA_AVARIA", "matricula": "M002"}])
    assert carga.registrar(con_demo, "investigacao_divergencia", inv, usuario="t").status == "RECUSADA"


def test_saldo_congelado_soma_movimentos_apos_a_extracao(con_demo):
    qtd, _ = consultas.saldo_congelado(con_demo, "A-01-01", "IOG-170", "L1001", datetime(2026, 10, 7, 12, 0))
    assert qtd == 240
    extra = movimentos_d1().head(1).assign(documento_numero="NF-6000", qtd="-40", data_movimento="2026-10-07",
                                           instante_lancamento="2026-10-07 10:00:00")
    carga.registrar(con_demo, "mov_estoque", extra, usuario="t")
    qtd, _ = consultas.saldo_congelado(con_demo, "A-01-01", "IOG-170", "L1001", datetime(2026, 10, 7, 12, 0))
    assert qtd == 200


def test_reconstrucao_e_deterministica(con_demo):
    from app import transform
    antes = _fato(con_demo, "fato_movimento_estoque").sort_values(["chave_negocio", "carga_id"]).reset_index(drop=True)
    transform.reconstruir(con_demo)
    depois = _fato(con_demo, "fato_movimento_estoque").sort_values(["chave_negocio", "carga_id"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(antes, depois)
    assert sk("DEMO", "sku", "IOG-170") == sk("DEMO", "sku", "IOG-170")


def test_usuario_obrigatorio(con):
    import pytest
    with pytest.raises(ValueError):
        carga.registrar(con, "mov_estoque", movimentos_d1(), usuario=" ")


def test_csv_e_xlsx_do_mesmo_conteudo_sao_a_mesma_carga(con_demo):
    import io
    from app.validacao import ler_arquivo
    df = movimentos_d1().assign(documento_numero=lambda d: d["documento_numero"] + "-B")
    csv = df.to_csv(sep=";", index=False).encode("utf-8")
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    r1 = carga.registrar(con_demo, "mov_estoque", ler_arquivo(csv, "m.csv"), usuario="t")
    r2 = carga.registrar(con_demo, "mov_estoque", ler_arquivo(buf.getvalue(), "m.xlsx"), usuario="t")
    assert (r1.status, r2.status) == ("ACEITA", "DUPLICADA")


def test_decimal_com_virgula_aceito_e_ambiguo_recusado(con_demo):
    ok = movimentos_d1().head(1).assign(documento_numero="NF-V1", custo_unit="1,10")
    amb = movimentos_d1().head(1).assign(documento_numero="NF-V2", custo_unit="1.100,00")
    assert carga.registrar(con_demo, "mov_estoque", ok, usuario="t").status == "ACEITA"
    assert carga.registrar(con_demo, "mov_estoque", amb, usuario="t").status == "RECUSADA"
