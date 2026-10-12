"""Ponte entre o celular e a ferramenta, rodando no computador (dono do banco).

O servidor do celular NÃO abre o banco: o DuckDB aceita um só processo gravando, e o app principal
já o mantém aberto. A troca é por arquivos, robusta a queda de rede e a reinício:
- `referencias.json`: o que o celular precisa saber (endereços, SKUs, lotes, matrículas, divergências,
  ações), exportado pelo app principal a cada mudança;
- `fila/<id>.json`: cada contagem ou investigação feita no celular, um arquivo por item;
- `resultados/<id>.json`: o que aconteceu com cada item, devolvido ao celular.
Toda validação é a de sempre (carga.registrar → layouts.yaml): o celular só coleta.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
from datetime import date, datetime, timedelta

import pandas as pd

from app import carga, consultas, metricas, transform
from app.movel import caminhos

FUNCOES_CONTAGEM = ("INVENTARIANTE", "CONFERENTE", "SUPERVISOR")


def _gravar_json(caminho, dados) -> None:
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, caminho)  # troca atômica: o servidor nunca lê arquivo pela metade


def exportar_referencias(con) -> dict:
    q = lambda sql, p=None: con.execute(sql, p or []).fetchall()  # noqa: E731
    lotes: dict[str, list] = {}
    for sku, lote, val in q("SELECT sku, lote, data_validade FROM dim_lote WHERE lote_sk > 0 "
                            "ORDER BY sku, data_validade NULLS LAST, lote"):
        lotes.setdefault(sku, []).append({"lote": lote, "validade": None if val is None else str(val)})
    pend = consultas.divergencias_pendentes(con)
    lim = con.execute("SELECT min(data_saldo), max(data_saldo), bool_or(sintetico) FROM cobertura_saldo").fetchone()
    acoes = []
    if lim[1] is not None:
        inicio = max(lim[0], lim[1] - timedelta(days=30))
        g = metricas.gatilhos(con, metricas.Filtros(inicio, lim[1]))
        acoes = g.drop(columns=["valor"]).head(100).to_dict(orient="records")
    ref = {
        "gerado_em": datetime.now().isoformat(timespec="seconds"),
        "sintetico": bool(lim[2]) if lim[2] is not None else False,
        "enderecos": [{"endereco": e, "site": s, "tipo": t} for e, s, t in q(
            "SELECT endereco, site, tipo FROM dim_local WHERE local_sk > 0 AND NOT inferido AND tipo != 'QUARENTENA' ORDER BY 1")],
        "skus": [{"sku": s, "descricao": d, "codigo_barras": b, "controla_lote": c, "unidade_base": u} for s, d, b, c, u in q(
            "SELECT sku, descricao, codigo_barras, controla_lote, unidade_base FROM dim_sku "
            "WHERE sku_sk > 0 AND NOT inferido ORDER BY 1")],
        "lotes": lotes,
        "colaboradores": [{"matricula": m, "funcao": f} for m, f in q(
            "SELECT matricula, funcao FROM dim_colaborador WHERE colaborador_sk > 0 ORDER BY 1")],
        "motivos_divergencia": [{"codigo": c, "descricao": d} for c, d in q(
            "SELECT codigo, descricao FROM dim_motivo WHERE processo = 'DIVERGENCIA' ORDER BY codigo")],
        # a diferença só é entregue a supervisores (o servidor filtra): quem reconta não pode vê-la
        "divergencias": [{"numero_contagem": r["numero_contagem"], "endereco": r["endereco"], "sku": r["sku"],
                          "lote": r["lote"], "diferenca": float(r["diferenca"])} for r in pend.to_dict(orient="records")],
        "acoes": acoes,
        "ultima_carga": con.execute("SELECT max(carga_id) FROM bruto_carga").fetchone()[0],
    }
    _gravar_json(caminhos.referencias(), ref)
    return ref


def _resultado(id_cliente: str, status: str, mensagem: str, erros: list[str] | None = None) -> dict:
    r = {"id_cliente": id_cliente, "status": status, "mensagem": mensagem, "erros": erros or [],
         "processado_em": datetime.now().isoformat(timespec="seconds")}
    _gravar_json(caminhos.resultados() / f"{id_cliente}.json", r)
    return r


def _arquivar(arquivo) -> None:
    destino = caminhos.raiz() / "processados"
    destino.mkdir(exist_ok=True)
    shutil.move(str(arquivo), destino / arquivo.name)


def processar_fila(con) -> list[dict]:
    """Registra no bruto cada item vindo do celular (validação de sempre) e reconstrói o modelo uma vez."""
    arquivos = sorted(caminhos.fila().glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not arquivos:
        return []
    saida, aceitou = [], False
    recontagens: dict[tuple, int] = {}
    for arq in arquivos:
        try:
            item = json.loads(arq.read_text(encoding="utf-8"))
            id_cliente, tipo, matricula, d = item["id_cliente"], item["tipo"], item["matricula"], item["dados"]
        except (ValueError, KeyError) as exc:
            _arquivar(arq)
            saida.append({"arquivo": arq.name, "status": "ERRO", "mensagem": f"arquivo ilegível: {exc}"})
            continue
        nome = f"celular:{id_cliente}"
        ja = con.execute("SELECT status FROM bruto_carga WHERE nome_arquivo = ? ORDER BY carga_id DESC LIMIT 1",
                         [nome]).fetchone()
        if ja is not None:  # reprocessamento após queda: o bruto já tem; só devolve o resultado
            saida.append(_resultado(id_cliente, ja[0], "já registrado anteriormente"))
            _arquivar(arq)
            continue
        try:
            if tipo == "contagem":
                r = _contagem(con, id_cliente, matricula, d, nome, recontagens)
            elif tipo == "investigacao":
                linha = {"numero_contagem": d["numero_contagem"], "endereco": d["endereco"], "sku": d["sku"],
                         "lote": d.get("lote") or "", "motivo": d["motivo"], "matricula": matricula}
                res = carga.registrar(con, "investigacao_divergencia", pd.DataFrame([linha]), usuario=matricula,
                                      fonte="FORMULARIO", nome_arquivo=nome, reconstruir=False)
                r = _resultado(id_cliente, res.status, res.mensagem, res.validacao.tabela_erros()["erro"].tolist())
            else:
                r = _resultado(id_cliente, "ERRO", f"tipo desconhecido: {tipo}")
        except Exception as exc:  # noqa: BLE001 — um item ruim não trava a fila
            r = _resultado(id_cliente, "ERRO", f"falha ao registrar: {exc}")
        aceitou |= r["status"] == "ACEITA"
        saida.append(r)
        _arquivar(arq)
    if aceitou:
        transform.reconstruir(con)
    exportar_referencias(con)
    return saida


def _contagem(con, id_cliente, matricula, d, nome, recontagens) -> dict:
    lote = d.get("lote") or None
    instante = datetime.fromisoformat(d["instante_congelamento"])
    congelado = consultas.saldo_congelado(con, d["endereco"], d["sku"], lote, instante)
    if congelado is None:
        return _resultado(id_cliente, "RECUSADA", "O site do endereço não tinha fotografia de saldo nesse instante.",
                          ["sem fotografia de saldo para comparar"])
    if d.get("recontagem_de"):
        numero = d["recontagem_de"]
        k = (numero, d["endereco"], d["sku"], lote or "")
        prox = max(consultas.proximo_numero_recontagem(con, numero, d["endereco"], d["sku"], lote),
                   recontagens.get(k, -1) + 1)
        recontagens[k] = prox
    else:
        numero, prox = d["numero_contagem"], 0
    linha = {"numero_contagem": numero, "numero_recontagem": str(prox), "endereco": d["endereco"], "sku": d["sku"],
             "lote": lote or "", "qtd_contada": str(d["qtd_contada"]), "qtd_sistema_congelada": str(congelado[0]),
             "instante_congelamento": instante.strftime("%Y-%m-%d %H:%M:%S"),
             "instante_contagem": datetime.fromisoformat(d["instante_contagem"]).strftime("%Y-%m-%d %H:%M:%S"),
             "matricula": matricula}
    res = carga.registrar(con, "contagem", pd.DataFrame([linha]), usuario=matricula, fonte="FORMULARIO",
                          nome_arquivo=nome, reconstruir=False)
    # contagem cega: a resposta ao celular nunca diz se houve diferença
    msg = "Contagem registrada." if res.status == "ACEITA" else res.mensagem
    return _resultado(id_cliente, res.status, msg, res.validacao.tabela_erros()["erro"].tolist())


# ----------------------------------------------------------------------------- vigia no app principal

_vigia_iniciado = False


def iniciar_vigia(base_con, intervalo_s: int = 15) -> None:
    """Thread do app principal: processa a fila do celular e reexporta referências quando o banco muda."""
    global _vigia_iniciado
    if _vigia_iniciado:
        return
    _vigia_iniciado = True

    def laco():
        ultima = None
        while True:
            try:
                c = base_con.cursor()
                atual = c.execute("SELECT max(carga_id) FROM bruto_carga").fetchone()[0]
                if any(caminhos.fila().glob("*.json")):
                    processar_fila(c)
                    ultima = c.execute("SELECT max(carga_id) FROM bruto_carga").fetchone()[0]
                elif atual != ultima or not caminhos.referencias().exists():
                    exportar_referencias(c)
                    ultima = atual
            except Exception:  # noqa: BLE001 — banco ocupado ou modelo em reconstrução: tenta no próximo ciclo
                pass
            time.sleep(intervalo_s)

    threading.Thread(target=laco, name="vigia-celular", daemon=True).start()
