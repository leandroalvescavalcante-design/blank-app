"""Versão celular: acesso por PIN, API (fila idempotente, contagem cega por papel) e integração com o bruto."""
import json
import time

import pytest
from starlette.testclient import TestClient

from app.movel import acesso, caminhos, integracao, servidor

CONG = "2026-10-07T10:00:00"   # depois da última fotografia do cenário demo (extraída 2026-10-07 00:30)


@pytest.fixture(autouse=True)
def pasta_isolada(tmp_path, monkeypatch):
    monkeypatch.setenv("GESTAO_DB", str(tmp_path / "gestao.duckdb"))
    acesso._falhas.clear()
    yield


@pytest.fixture
def cliente(con_demo):
    integracao.exportar_referencias(con_demo)
    acesso.definir_pin("M001", "4826")
    acesso.definir_pin("M002", "7391")
    return TestClient(servidor.app_https())


def _token(c, matricula, pin):
    r = c.post("/api/login", json={"matricula": matricula, "pin": pin})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _contagem(idc, qtd, **extra):
    d = {"numero_contagem": f"CEL-M001-{idc[:6]}", "endereco": "A-01-01", "sku": "IOG-170", "lote": "L1001",
         "qtd_contada": qtd, "instante_congelamento": CONG, "instante_contagem": "2026-10-07T10:05:00"}
    d.update(extra)
    return {"id_cliente": idc, "tipo": "contagem", "dados": d, "criado_em": "2026-10-07T10:05:00"}


# ----------------------------------------------------------------------------- acesso

def test_pin_fraco_recusado():
    for pin in ("123", "1111", "1234", "9876", "12a4", "123456789"):
        with pytest.raises(ValueError):
            acesso.definir_pin("M001", pin)


def test_pin_guardado_so_como_hash():
    acesso.definir_pin("M001", "4826")
    texto = caminhos.acessos().read_text()
    assert "4826" not in texto and "hash" in texto


def test_token_valido_adulterado_expirado_revogado():
    acesso.definir_pin("M001", "4826")
    t = acesso.entrar("M001", "4826")
    assert acesso.validar_token(t) == "M001"
    corpo, sig = t.split(".")
    assert acesso.validar_token(corpo + "." + "0" * len(sig)) is None
    assert acesso.validar_token(acesso.emitir_token("M001", validade_s=-1)) is None
    acesso.remover("M001")
    assert acesso.validar_token(t) is None  # revogar vale na hora, mesmo com token dentro da validade


def test_bloqueio_apos_cinco_falhas():
    acesso.definir_pin("M001", "4826")
    for _ in range(5):
        assert acesso.entrar("M001", "0000") is None
    assert acesso.bloqueada("M001")
    assert acesso.entrar("M001", "4826") is None  # nem o PIN certo passa durante o bloqueio
    assert not acesso.bloqueada("M001", agora=time.time() + acesso.BLOQUEIO_S + 1)


# ----------------------------------------------------------------------------- API

def test_api_exige_sessao(cliente):
    assert cliente.get("/api/referencias").status_code == 401
    assert cliente.post("/api/enviar", json={"itens": []}).status_code == 401
    assert cliente.post("/api/login", json={"matricula": "M001", "pin": "0000"}).status_code == 401


def test_referencias_sem_saldo_e_sem_quarentena(cliente):
    ref = cliente.get("/api/referencias", headers=_token(cliente, "M001", "4826")).json()
    assert ref["funcao"] == "INVENTARIANTE" and ref["sintetico"] is True
    assert "Q-01" not in {e["endereco"] for e in ref["enderecos"]}
    assert [l["lote"] for l in ref["lotes"]["IOG-170"]] == ["L1001", "L1002", "L1003"]  # FEFO
    assert ref["acoes"] == []  # o K05 traz a quantidade do lote: entregar a quem conta quebraria a contagem cega
    assert not any("qtd" in k or "saldo" in k for e in ref["skus"] + ref["enderecos"] for k in e)
    sup = cliente.get("/api/referencias", headers=_token(cliente, "M002", "7391")).json()
    assert sup["acoes"]


def test_enfileirar_idempotente_e_matricula_vem_do_token(cliente):
    h = _token(cliente, "M001", "4826")
    item = _contagem("a1b2c3d4-0001", 240)
    item["dados"]["matricula"] = "M002"          # tentativa de se passar por outro: campo é descartado
    item["dados"]["qtd_sistema_congelada"] = 1   # o celular não manda saldo
    for _ in range(3):
        r = cliente.post("/api/enviar", json={"itens": [item]}, headers=h)
        assert r.json()["recebidos"] == ["a1b2c3d4-0001"]
    arqs = list(caminhos.fila().glob("*.json"))
    assert len(arqs) == 1
    salvo = json.loads(arqs[0].read_text())
    assert salvo["matricula"] == "M001"
    assert "matricula" not in salvo["dados"] and "qtd_sistema_congelada" not in salvo["dados"]


def test_envio_malformado_e_investigacao_de_nao_supervisor(cliente):
    h = _token(cliente, "M001", "4826")
    r = cliente.post("/api/enviar", headers=h, json={"itens": [
        {"id_cliente": "../../x", "tipo": "contagem", "dados": {}},
        {"id_cliente": "abcdefgh-1", "tipo": "investigacao", "dados": {"motivo": "DIV_SEPARACAO"}},
    ]}).json()
    assert r["recebidos"] == [] and len(r["recusados"]) == 2
    assert cliente.post("/api/enviar", headers=h, json={"itens": [{}] * 201}).status_code == 400


# ----------------------------------------------------------------------------- integração com o bruto

def _enviar_e_processar(cliente, con, h, itens):
    cliente.post("/api/enviar", json={"itens": itens}, headers=h)
    return integracao.processar_fila(con)


def test_contagem_offline_congela_no_instante_e_reconta_cego(cliente, con_demo):
    h1 = _token(cliente, "M001", "4826")
    res = _enviar_e_processar(cliente, con_demo, h1, [_contagem("cont-00000001", 230)])
    assert res[0]["status"] == "ACEITA" and res[0]["mensagem"] == "Contagem registrada."
    linha = con_demo.execute("SELECT qtd_sistema_congelada, numero_recontagem FROM fato_contagem fc "
                             "WHERE numero_contagem = 'CEL-M001-cont-0'").fetchone()
    assert linha == (240, 0)  # saldo calculado no computador para o instante do congelamento

    # quem reconta não recebe a diferença; o supervisor recebe
    div = cliente.get("/api/referencias", headers=h1).json()["divergencias"]
    assert len(div) == 1 and "diferenca" not in div[0]
    h2 = _token(cliente, "M002", "7391")
    assert cliente.get("/api/referencias", headers=h2).json()["divergencias"][0]["diferenca"] == -10

    # duas recontagens feitas offline no mesmo lote: numeradas 1 e 2 na ordem de chegada
    rec = [_contagem(f"rec-0000000{i}", 230, recontagem_de="CEL-M001-cont-0") for i in (1, 2)]
    res = _enviar_e_processar(cliente, con_demo, h1, rec)
    assert [r["status"] for r in res] == ["ACEITA", "ACEITA"]
    nums = con_demo.execute("SELECT numero_recontagem FROM fato_contagem WHERE numero_contagem = 'CEL-M001-cont-0' "
                            "ORDER BY 1").fetchall()
    assert [n[0] for n in nums] == [0, 1, 2]

    # status devolvido ao celular
    st = cliente.get("/api/status?ids=rec-00000001,rec-00000002,nao-existe-1", headers=h1).json()
    assert st["rec-00000001"]["status"] == "ACEITA" and st["nao-existe-1"] is None


def test_reprocessar_nao_duplica(cliente, con_demo):
    h = _token(cliente, "M001", "4826")
    _enviar_e_processar(cliente, con_demo, h, [_contagem("dup-00000001", 240)])
    # simula queda: o arquivo volta para a fila depois de já gravado no bruto
    proc = caminhos.raiz() / "processados" / "dup-00000001.json"
    proc.rename(caminhos.fila() / proc.name)
    res = integracao.processar_fila(con_demo)
    assert res[0]["mensagem"] == "já registrado anteriormente"
    n = con_demo.execute("SELECT count(*) FROM bruto_carga WHERE nome_arquivo = 'celular:dup-00000001'").fetchone()[0]
    assert n == 1


def test_contagem_invalida_volta_recusada_com_erro(cliente, con_demo):
    h = _token(cliente, "M001", "4826")
    ruim = _contagem("ruim-0000001", 5, instante_contagem="2026-10-07T09:00:00")  # antes do congelamento
    res = _enviar_e_processar(cliente, con_demo, h, [ruim])
    assert res[0]["status"] == "RECUSADA" and any("congelamento" in e for e in res[0]["erros"])
    sem_foto = _contagem("ruim-0000002", 5, instante_congelamento="2026-10-01T10:00:00",
                         instante_contagem="2026-10-01T10:05:00")
    res = _enviar_e_processar(cliente, con_demo, h, [sem_foto])
    assert res[0]["status"] == "RECUSADA"


def test_investigacao_pelo_celular(cliente, con_demo):
    h1, h2 = _token(cliente, "M001", "4826"), _token(cliente, "M002", "7391")
    _enviar_e_processar(cliente, con_demo, h1, [_contagem("inv-00000001", 230)])
    inv = {"id_cliente": "inv-00000002", "tipo": "investigacao",
           "dados": {"numero_contagem": "CEL-M001-inv-00", "endereco": "A-01-01", "sku": "IOG-170", "lote": "L1001",
                     "motivo": "DIV_SEPARACAO"}}
    res = _enviar_e_processar(cliente, con_demo, h2, [inv])
    assert res[0]["status"] == "ACEITA", res
    assert cliente.get("/api/referencias", headers=h2).json()["divergencias"] == []


def test_pagina_do_certificado():
    from app.movel import certificado
    certificado.garantir_ca()
    ips = certificado.gerar_servidor(["127.0.0.1", "192.168.0.10"])
    assert "192.168.0.10" in ips
    c = TestClient(servidor.app_http())
    assert "Instalar certificado" in c.get("/").text
    assert c.get("/ca.crt").content.startswith(b"-----BEGIN CERTIFICATE-----")


def test_app_estatico_servido(cliente):
    assert "app.js" in cliente.get("/").text
    assert cliente.get("/sw.js").status_code == 200
    assert cliente.get("/manifest.webmanifest").json()["display"] == "standalone"
