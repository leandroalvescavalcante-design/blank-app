"""Dimensões e fatos das frentes 2 (planejamento) e 3 (ciclo do pedido), reconstruídos do bruto."""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from app.transform import (NAO_SE_APLICA, _data_sk, _vazio_para_none, linhas_aceitas, sk, versionar,
                           versoes_atuais)


def _proc(fonte: str) -> int:
    return sk("proc", fonte)


def _comuns(r: dict) -> dict:
    return {"empresa": r["empresa"], "procedencia_sk": _proc(r["fonte"]), "carga_id": r["carga_id"],
            "bruto_num_linha": r["num_linha"], "chave_negocio": r["chave_negocio"], "hash_linha": r["hash_linha"],
            "tipo_registro": r["tipo_registro"], "sinal": r["sinal"], "sintetico": bool(r["sintetico"])}


def construir(con, empresa: str, refs: dict) -> dict[str, pd.DataFrame]:
    t: dict[str, pd.DataFrame] = {}
    S = lambda *p: sk(empresa, *p)  # noqa: E731
    lote_sk = lambda s, l: NAO_SE_APLICA if _vazio_para_none(l) is None else S("lote", s, l)  # noqa: E731
    motivo_sk = lambda m: NAO_SE_APLICA if _vazio_para_none(m) is None else S("motivo", m)  # noqa: E731

    # ------------------------------------------------------------- dimensões
    t["dim_cliente"] = pd.DataFrame([
        {"cliente_sk": S("cliente", c), "empresa": empresa, "cliente": c, "nome": r["nome"], "municipio": r["municipio"],
         "uf": r["uf"], "latitude": r["latitude"], "longitude": r["longitude"], "janela_inicio": r["janela_inicio"],
         "janela_fim": r["janela_fim"], "prioridade": r["prioridade"],
         "validade_minima_dias": _vazio_para_none(r["validade_minima_dias"])}
        for c, r in refs.get("cad_cliente", {}).items()])
    t["dim_parceiro"] = pd.DataFrame([
        {"parceiro_sk": S("parceiro", c), "empresa": empresa, "cnpj": c, "razao_social": r["razao_social"],
         "e_fornecedor": r["e_fornecedor"], "e_transportadora": r["e_transportadora"]}
        for c, r in refs.get("cad_parceiro", {}).items()])
    t["parceiro_sku"] = pd.DataFrame([
        {"parceiro_sk": S("parceiro", r["cnpj"]), "sku_sk": S("sku", r["sku"]), "lote_minimo": r["lote_minimo"],
         "multiplo_compra": r["multiplo_compra"], "lead_time_contratado_dias": r["lead_time_contratado_dias"]}
        for r in versoes_atuais(con, "cad_parceiro_sku").to_dict(orient="records")])
    t["dim_veiculo"] = pd.DataFrame([
        {"veiculo_sk": S("veiculo", p), "empresa": empresa, "placa": p, "tipo": r["tipo"], "cap_kg": r["cap_kg"],
         "cap_m3": r["cap_m3"], "classe_temperatura": r["classe_temperatura"], "propria": r["propria"],
         "parceiro_sk": S("parceiro", r["transportadora_cnpj"]) if _vazio_para_none(r["transportadora_cnpj"]) else NAO_SE_APLICA}
        for p, r in refs.get("cad_veiculo", {}).items()])
    t["dim_recurso"] = pd.DataFrame([
        {"recurso_sk": S("recurso", c), "empresa": empresa, "recurso": c, "descricao": r["descricao"], "site": r["site"],
         "tipo": r["tipo"], "e_restritivo": r["e_restritivo"]} for c, r in refs.get("cad_recurso", {}).items()])
    t["dim_turno"] = pd.DataFrame([
        {"turno_sk": S("turno", c), "empresa": empresa, "turno": c, "site": r["site"], "inicio": r["inicio"],
         "fim": r["fim"], "horas_disponiveis": r["horas_disponiveis"]} for c, r in refs.get("cad_turno", {}).items()])
    t["matriz_setup"] = pd.DataFrame([
        {"recurso_sk": S("recurso", r["recurso"]), "familia_origem": r["familia_origem"],
         "familia_destino": r["familia_destino"], "minutos": r["minutos"]}
        for r in versoes_atuais(con, "cad_setup").to_dict(orient="records")])
    t["acordo_validade"] = pd.DataFrame([
        {"cliente_sk": S("cliente", r["cliente"]), "sku_sk": S("sku", r["sku"]),
         "validade_minima_dias": r["validade_minima_dias"]}
        for r in versoes_atuais(con, "cad_acordo_validade").to_dict(orient="records")])
    t["parametro_sku_local"] = pd.DataFrame([
        {"sku_sk": S("sku", r["sku"]), "site": r["site"], "nivel_servico": r["nivel_servico"],
         "dias_parados": r["dias_parados"], "transito_dias": r["transito_dias"], "custo_pedido": r["custo_pedido"],
         "taxa_manter_ano": r["taxa_manter_ano"], "lead_time_reposicao_dias": _vazio_para_none(r["lead_time_reposicao_dias"]),
         "tolerancia_contagem_pct": _vazio_para_none(r["tolerancia_contagem_pct"])}
        for r in versoes_atuais(con, "parametro_sku_local").to_dict(orient="records")])
    pe_todas = linhas_aceitas(con, "parametro_empresa")
    pe = pe_todas.drop_duplicates("chave_negocio", keep="last")
    t["parametro_empresa"] = pd.DataFrame([
        {**{k: r[k] for k in ("empresa", "otif_tolerancia_pct", "limiar_ocupacao", "limiar_k02b", "n_min_observacoes",
                              "janela_demanda_dias", "janela_lead_time_dias", "janela_clientes_dias", "apto_n_contagens",
                              "apto_janela_dias", "apto_limiar", "horizonte_projecao_dias")},
         "versao": int((pe_todas["empresa"] == r["empresa"]).sum())}
        for r in pe.to_dict(orient="records")])

    # ------------------------------------------------------------- F01 recebimento
    rec = linhas_aceitas(con, "recebimento")
    t["fato_recebimento"] = pd.DataFrame([{
        **_comuns(r), "data": r["instante_conferencia"].date(), "data_sk": _data_sk(r["instante_conferencia"].date()),
        "instante_conferencia": r["instante_conferencia"], "sku_sk": S("sku", r["sku"]),
        "lote_sk": lote_sk(r["sku"], r["lote"]), "local_sk": S("local", r["endereco"]),
        "parceiro_sk": S("parceiro", r["fornecedor_cnpj"]), "colaborador_sk": S("colab", r["matricula_conferente"]),
        "motivo_sk": motivo_sk(r["motivo"]), "numero_recebimento": r["numero_recebimento"], "item": r["item"],
        "numero_pc": _vazio_para_none(r["numero_pc"]), "item_pc": _vazio_para_none(r["item_pc"]),
        "chave_nf_entrada": _vazio_para_none(r["chave_nf_entrada"]), "qtd_esperada": r["qtd_esperada"],
        "qtd_recebida": r["qtd_recebida"], "qtd_recusada": r["qtd_recusada"]}
        for r in versionar(rec, ["qtd_esperada", "qtd_recebida", "qtd_recusada"]).to_dict(orient="records")])

    # ------------------------------------------------------------- F05 pedido de compra (acumulado)
    pce = versoes_atuais(con, "pedido_compra_evento")
    rec_atual = rec.drop_duplicates("chave_negocio", keep="last") if not rec.empty else rec
    linhas = []
    if not pce.empty:
        for (pc, item), g in pce.sort_values(["numero_evento"]).groupby(["numero_pc", "item"], sort=False):
            g = g.sort_values("numero_evento")
            emissao = g.iloc[0]
            pedida = float(g["delta_qtd"].clip(lower=0).sum())
            cancelada = float(-g.loc[g["tipo_evento"] == "CANCELAMENTO", "delta_qtd"].sum())
            receb = rec_atual[(rec_atual["numero_pc"] == pc) & (rec_atual["item_pc"] == item)] if not rec_atual.empty else rec_atual
            recebida = float(receb["qtd_recebida"].sum()) if not receb.empty else 0.0
            datas_rec = sorted(i.date() for i in receb["instante_conferencia"]) if not receb.empty else []
            liquida = pedida - cancelada
            if liquida <= 0:
                status, enc = "CANCELADO", g.iloc[-1]["instante_evento"].date()
            elif recebida + float(receb["qtd_recusada"].sum() if not receb.empty else 0) >= liquida - 1e-9:
                status, enc = "ENCERRADO", datas_rec[-1] if datas_rec else None
            else:
                status, enc = ("PARCIAL" if recebida > 0 else "ABERTO"), None
            motivo = next((m for m in reversed(g["motivo"].tolist()) if _vazio_para_none(m)), None)
            linhas.append({
                "empresa": emissao["empresa"], "procedencia_sk": _proc(emissao["fonte"]),
                "sintetico": bool(g["sintetico"].any()), "numero_pc": pc, "item": item,
                "sku_sk": S("sku", emissao["sku"]), "site": emissao["site"],
                "parceiro_sk": S("parceiro", emissao["fornecedor_cnpj"]), "motivo_sk": motivo_sk(motivo),
                "data_emissao": emissao["instante_evento"].date(), "data_prevista_original": emissao["data_prevista"],
                "data_prevista_atual": g.iloc[-1]["data_prevista"],
                "data_primeiro_receb": datas_rec[0] if datas_rec else None,
                "data_ultimo_receb": datas_rec[-1] if datas_rec else None, "data_encerramento": enc,
                "qtd_pedida": pedida, "qtd_recebida_acum": recebida, "qtd_cancelada": cancelada, "status": status})
    t["fato_pedido_compra_linha"] = pd.DataFrame(linhas)

    # ------------------------------------------------------------- F06a / F06b
    prog = linhas_aceitas(con, "programacao_op")
    t["fato_programacao_op"] = pd.DataFrame([{
        **_comuns(r), "data": r["data"], "data_sk": _data_sk(r["data"]), "turno_sk": S("turno", r["turno"]),
        "recurso_sk": S("recurso", r["recurso"]), "sku_sk": S("sku", r["sku"]), "numero_op": r["numero_op"],
        "versao": r["versao"], "sequencia": r["sequencia"], "congelada": r["congelada"] == "S",
        "qtd_programada": r["qtd_programada"], "tempo_padrao_min_un": r["tempo_padrao_min_un"], "setup_min": r["setup_min"]}
        for r in versionar(prog, ["qtd_programada", "setup_min"]).to_dict(orient="records")])
    apo = linhas_aceitas(con, "apontamento")
    t["fato_apontamento"] = pd.DataFrame([{
        **_comuns(r), "data": r["instante_apontamento"].date(), "data_sk": _data_sk(r["instante_apontamento"].date()),
        "instante_apontamento": r["instante_apontamento"], "turno_sk": S("turno", r["turno"]),
        "recurso_sk": S("recurso", r["recurso"]), "sku_sk": S("sku", r["sku"]), "lote_sk": lote_sk(r["sku"], r["lote"]),
        "colaborador_sk": -1, "motivo_sk": motivo_sk(r["motivo_refugo"]), "numero_op": r["numero_op"],
        "numero_apontamento": r["numero_apontamento"], "qtd_boa": r["qtd_boa"], "qtd_refugo": r["qtd_refugo"]}
        for r in versionar(apo, ["qtd_boa", "qtd_refugo"]).to_dict(orient="records")])

    # ------------------------------------------------------------- F07 eventos de pedido de venda
    pve = linhas_aceitas(con, "pedido_venda_evento")
    t["fato_evento_pedido_venda"] = pd.DataFrame([{
        **_comuns(r), "data_evento": r["instante_evento"].date(), "data_desejada": r["data_desejada"],
        "data_sk": _data_sk(r["data_desejada"]), "instante_evento": r["instante_evento"],
        "cliente_sk": S("cliente", r["cliente"]), "sku_sk": S("sku", r["sku"]), "site": r["site"],
        "motivo_sk": motivo_sk(r["motivo"]), "numero_pedido": r["numero_pedido"], "item": r["item"],
        "numero_evento": r["numero_evento"], "tipo_evento": r["tipo_evento"], "delta_qtd": r["delta_qtd"]}
        for r in versionar(pve, ["delta_qtd"]).to_dict(orient="records")])
    pve_atual = pve.drop_duplicates("chave_negocio", keep="last") if not pve.empty else pve
    cliente_do_pedido = dict(zip(pve_atual.get("numero_pedido", []), pve_atual.get("cliente", [])))

    # ------------------------------------------------------------- F08 separação
    sep = linhas_aceitas(con, "separacao")
    t["fato_separacao"] = pd.DataFrame([{
        **_comuns(r), "data": r["instante_separacao"].date(), "data_sk": _data_sk(r["instante_separacao"].date()),
        "instante_separacao": r["instante_separacao"], "instante_conferencia": r["instante_conferencia"],
        "sku_sk": S("sku", r["sku"]), "lote_sk": lote_sk(r["sku"], r["lote"]), "local_sk": S("local", r["endereco"]),
        "cliente_sk": S("cliente", cliente_do_pedido[r["numero_pedido"]]) if r["numero_pedido"] in cliente_do_pedido else -1,
        "colaborador_separador_sk": S("colab", r["matricula_separador"]),
        "colaborador_conferente_sk": S("colab", r["matricula_conferente"]), "motivo_sk": motivo_sk(r["motivo"]),
        "numero_tarefa": r["numero_tarefa"], "remessa": r["ordem_separacao"], "numero_pedido": r["numero_pedido"],
        "item": r["item"], "qtd_solicitada": r["qtd_solicitada"], "qtd_separada": r["qtd_separada"],
        "qtd_conferida": r["qtd_conferida"]}
        for r in versionar(sep, ["qtd_solicitada", "qtd_separada", "qtd_conferida"]).to_dict(orient="records")])

    # ------------------------------------------------------------- F09 faturamento (remessa = ordem; sem ordem, a NF)
    fat = linhas_aceitas(con, "faturamento")
    t["fato_faturamento"] = pd.DataFrame([{
        **_comuns(r), "data": r["instante_emissao"].date(), "data_sk": _data_sk(r["instante_emissao"].date()),
        "instante_emissao": r["instante_emissao"], "cliente_sk": S("cliente", r["cliente"]), "sku_sk": S("sku", r["sku"]),
        "site": r["site"], "chave_nf": r["chave_nf"], "item_nf": r["item_nf"], "numero_pedido": r["numero_pedido"],
        "item_pedido": r["item_pedido"], "remessa": _vazio_para_none(r["ordem_separacao"]) or r["chave_nf"],
        "qtd": r["qtd"], "valor_mercadoria": r["valor_mercadoria"]}
        for r in versionar(fat, ["qtd", "valor_mercadoria"]).to_dict(orient="records")])

    # ------------------------------------------------------------- F10b entrega
    ent = linhas_aceitas(con, "entrega")
    ent_atual = ent.drop_duplicates("chave_negocio", keep="last") if not ent.empty else ent
    ultima = set()
    if not ent_atual.empty:
        idx = ent_atual.groupby("remessa")["numero_tentativa"].idxmax()
        ultima = set(ent_atual.loc[idx, "chave_negocio"])
    t["fato_entrega"] = pd.DataFrame([{
        **_comuns(r), "data": r["instante_chegada"].date(), "data_sk": _data_sk(r["instante_chegada"].date()),
        "instante_chegada": r["instante_chegada"], "instante_conclusao": r["instante_conclusao"],
        "cliente_sk": S("cliente", r["cliente"]), "motivo_sk": motivo_sk(r["motivo"]), "numero_viagem": r["numero_viagem"],
        "remessa": r["remessa"], "numero_tentativa": r["numero_tentativa"], "status": r["status"],
        "e_ultima_tentativa": r["chave_negocio"] in ultima}
        for r in versionar(ent, []).to_dict(orient="records")])

    # ------------------------------------------------------------- F10a viagem (peso/volume pelas remessas da viagem)
    via = linhas_aceitas(con, "viagem")
    fat_atual = fat.drop_duplicates("chave_negocio", keep="last") if not fat.empty else fat
    skus = refs.get("cad_sku", {})
    carga_remessa: dict[str, tuple[float, float]] = {}
    for r in fat_atual.to_dict(orient="records"):
        rem = _vazio_para_none(r["ordem_separacao"]) or r["chave_nf"]
        s = skus.get(r["sku"], {})
        p, v = carga_remessa.get(rem, (0.0, 0.0))
        carga_remessa[rem] = (p + r["qtd"] * float(s.get("peso_bruto_kg_un_base") or 0),
                              v + r["qtd"] * float(s.get("volume_m3_un_base") or 0))
    por_viagem: dict[str, list] = {}
    for r in ent_atual.to_dict(orient="records"):
        por_viagem.setdefault(r["numero_viagem"], []).append(r)
    veic = refs.get("cad_veiculo", {})
    linhas = []
    for r in versionar(via, ["custo_viagem"]).to_dict(orient="records"):
        ents = por_viagem.get(r["numero_viagem"], [])
        peso = sum(carga_remessa.get(e["remessa"], (0, 0))[0] for e in ents)
        vol = sum(carga_remessa.get(e["remessa"], (0, 0))[1] for e in ents)
        sinal = -1 if r["tipo_registro"] == "ESTORNO" else 1
        transp = _vazio_para_none(veic.get(r["placa"], {}).get("transportadora_cnpj"))
        linhas.append({
            **_comuns(r), "data": r["instante_saida"].date(), "data_sk": _data_sk(r["instante_saida"].date()),
            "instante_saida": r["instante_saida"], "instante_retorno": r["instante_retorno"],
            "veiculo_sk": S("veiculo", r["placa"]), "colaborador_sk": S("colab", r["matricula_motorista"]),
            "parceiro_sk": S("parceiro", transp) if transp else NAO_SE_APLICA, "site": r["site"],
            "numero_viagem": r["numero_viagem"], "peso_kg": sinal * peso, "volume_m3": sinal * vol,
            "custo_viagem": r["custo_viagem"], "qtd_remessas": sinal * len(ents),
            "qtd_paradas": sinal * len({e["cliente"] for e in ents})})
    t["fato_viagem"] = pd.DataFrame(linhas)

    # ------------------------------------------------------------- F11 ciclo do pedido
    t["fato_ciclo_pedido"] = _ciclo(pve_atual, sep, fat_atual, ent_atual, via, t["parametro_empresa"], S, motivo_sk)
    return t


def _ciclo(pve, sep, fat, ent, via, pe, S, motivo_sk) -> pd.DataFrame:
    if pve.empty:
        return pd.DataFrame()
    tol = float(pe["otif_tolerancia_pct"].iloc[0]) if not pe.empty else 0.0
    versao = int(pe["versao"].iloc[0]) if not pe.empty else 0
    sep_a = sep.drop_duplicates("chave_negocio", keep="last") if not sep.empty else sep
    via_a = via.drop_duplicates("chave_negocio", keep="last") if not via.empty else via
    saida_viagem = dict(zip(via_a.get("numero_viagem", []), via_a.get("instante_saida", [])))
    placa_viagem = dict(zip(via_a.get("numero_viagem", []), via_a.get("placa", [])))
    sint = bool(pve["sintetico"].any())
    fim_dados = max([pve["instante_evento"].max()] + ([sep_a["instante_conferencia"].max()] if not sep_a.empty else [])).date()

    sep_g = {}
    for r in sep_a.to_dict(orient="records"):
        k = (r["numero_pedido"], r["item"], r["ordem_separacao"])
        q, i = sep_g.get(k, (0.0, None))
        sep_g[k] = (q + r["qtd_conferida"], max(i, r["instante_conferencia"]) if i else r["instante_conferencia"])
    fat_g = {}
    for r in fat.to_dict(orient="records"):
        rem = _vazio_para_none(r["ordem_separacao"]) or r["chave_nf"]
        k = (r["numero_pedido"], r["item_pedido"], rem)
        q, i = fat_g.get(k, (0.0, None))
        fat_g[k] = (q + r["qtd"], min(i, r["instante_emissao"]) if i else r["instante_emissao"])
    ent_g = {}
    for rem, g in (ent.groupby("remessa") if not ent.empty else []):
        g = g.sort_values("numero_tentativa")
        ent_g[rem] = {"status": g.iloc[-1]["status"], "fim": g.iloc[-1]["instante_conclusao"],
                      "motivo": g.iloc[-1]["motivo"], "viagem_1": g.iloc[0]["numero_viagem"],
                      "viagem_ult": g.iloc[-1]["numero_viagem"]}

    linhas = []
    for (ped, item), g in pve.sort_values("numero_evento").groupby(["numero_pedido", "item"], sort=False):
        criacao = g.iloc[0]
        ultimo = g.iloc[-1]
        liquida = float(g["delta_qtd"].sum())
        base = {"empresa": criacao["empresa"], "procedencia_sk": sk_proc(), "sintetico": sint,
                "numero_pedido": ped, "item": item, "cliente_sk": S("cliente", criacao["cliente"]),
                "sku_sk": S("sku", criacao["sku"]), "site": criacao["site"],
                "data_pedido": criacao["instante_evento"].date(), "data_prometida": ultimo["data_desejada"],
                "instante_pedido": criacao["instante_evento"], "qtd_pedida_linha": liquida, "versao_regra_otif": versao}
        vazio = {"remessa": None, "veiculo_sk": NAO_SE_APLICA, "motivo_sk": NAO_SE_APLICA, "data_separacao": None,
                 "data_faturamento": None, "data_carregamento": None, "data_entrega": None, "instante_separacao": None,
                 "instante_faturamento": None, "instante_carregamento": None, "instante_entrega": None,
                 "carregamento_estimado": False, "qtd_alocada": 0.0, "qtd_entregue": 0.0, "no_prazo": False,
                 "completo": False, "otif": False}
        if liquida <= 1e-9 and (g["tipo_evento"] == "CANCELAMENTO").any():
            motivo = next((m for m in reversed(g["motivo"].tolist()) if _vazio_para_none(m)), "CANC_CLIENTE")
            linhas.append({**base, **vazio, "remessa": "CANCELADA", "status_final": "cancelada_cliente",
                           "motivo_sk": motivo_sk(motivo), "qtd_alocada": float(criacao["delta_qtd"])})
            continue
        remessas = sorted({k[2] for k in sep_g if k[:2] == (ped, item)} | {k[2] for k in fat_g if k[:2] == (ped, item)})
        linha_rows = []
        for rem in remessas:
            q_sep, i_sep = sep_g.get((ped, item, rem), (0.0, None))
            q_fat, i_fat = fat_g.get((ped, item, rem), (0.0, None))
            alocada = q_fat if q_fat > 0 else q_sep
            if alocada <= 0:
                continue
            e = ent_g.get(rem)
            carreg = saida_viagem.get(e["viagem_1"]) if e else None
            entregue = e is not None and e["status"] in ("ENTREGUE", "PARCIAL")
            fim = e["fim"] if entregue else None
            linha_rows.append({**base, **vazio, "remessa": rem,
                               "veiculo_sk": S("veiculo", placa_viagem[e["viagem_ult"]]) if e and e["viagem_ult"] in placa_viagem else NAO_SE_APLICA,
                               "motivo_sk": motivo_sk(e["motivo"]) if e else NAO_SE_APLICA,
                               "data_separacao": i_sep.date() if i_sep else None,
                               "data_faturamento": i_fat.date() if i_fat else None,
                               "data_carregamento": carreg.date() if carreg is not None else None,
                               "data_entrega": fim.date() if fim is not None else None,
                               "instante_separacao": i_sep, "instante_faturamento": i_fat,
                               "instante_carregamento": carreg, "instante_entrega": fim,
                               "carregamento_estimado": carreg is not None, "qtd_alocada": alocada,
                               "qtd_entregue": alocada if entregue else 0.0,
                               "status_final": "entregue" if entregue else "em_aberto",
                               "no_prazo": bool(entregue and fim.date() <= base["data_prometida"])})
        alocado = sum(r["qtd_alocada"] for r in linha_rows)
        resto = liquida - alocado
        if resto > 1e-9:
            if linha_rows or base["data_prometida"] < fim_dados:
                linha_rows.append({**base, **vazio, "remessa": "CORTE", "status_final": "cortada",
                                   "motivo_sk": motivo_sk("CORTE_FALTA_SALDO"), "qtd_alocada": resto})
            else:
                linha_rows.append({**base, **vazio, "remessa": "PENDENTE", "status_final": "em_aberto",
                                   "qtd_alocada": resto})
        entregue_total = sum(r["qtd_entregue"] for r in linha_rows)
        completo = entregue_total >= liquida * (1 - tol) - 1e-9
        for r in linha_rows:
            r["completo"] = completo
            r["otif"] = bool(r["status_final"] == "entregue" and r["no_prazo"] and completo)
        linhas.extend(linha_rows)
    return pd.DataFrame(linhas)


def sk_proc() -> int:
    return sk("proc", "DERIVADO")
