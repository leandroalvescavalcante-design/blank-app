"""F12 (estado de planejamento por SKU × site × dia) e F12b (risco de vencimento por lote).

Fórmulas: semantica/metricas.yaml (K05, K07, K09, K10, K14). Cada dia é calculado só com o que se sabia
até aquele dia, para que F12 responda "com que número a decisão daquele dia foi tomada" (Etapa 3).

Escolhas por benchmark (docs/08-painel-e-fechamento.md):
- padrão de demanda pela classificação de Syntetos-Boylan (ADI 1,32; CV² 0,49);
- demanda não suave → estoque de segurança pelo quantil empírico da demanda no lead time (bootstrap),
  em vez da fórmula normal, que superestima ou subestima com muitos dias zero;
- tolerância de contagem padrão por classe ABC: A 0%, B 2%, C 5% (quando o tenant não informa).
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np
import pandas as pd

ADI_CORTE, CV2_CORTE = 1.32, 0.49
TOLERANCIA_ABC = {"A": 0.0, "B": 0.02, "C": 0.05}
DIAS_UTEIS_ANO = 312          # segunda a sábado; o calendário operacional define o dia útil
AMOSTRAS_BOOTSTRAP = 2000
PADRAO_EMPRESA = dict(otif_tolerancia_pct=0.0, limiar_ocupacao=0.6, limiar_k02b=0.3, n_min_observacoes=20,
                      janela_demanda_dias=28, janela_lead_time_dias=56, janela_clientes_dias=28, apto_n_contagens=2,
                      apto_janela_dias=30, apto_limiar=0.9, horizonte_projecao_dias=21)


def _atual(df: pd.DataFrame) -> pd.DataFrame:
    """Versão vigente de cada chave de negócio (descarta estornos e versões substituídas)."""
    if df.empty:
        return df
    vivos = df[df["tipo_registro"] != "ESTORNO"].sort_values(["carga_id", "bruto_num_linha"])
    return vivos.drop_duplicates("chave_negocio", keep="last")


def _padrao(adi: float, cv2: float) -> str:
    if adi <= ADI_CORTE:
        return "SUAVE" if cv2 <= CV2_CORTE else "ERRATICA"
    return "INTERMITENTE" if cv2 <= CV2_CORTE else "IRREGULAR"


def parametros_empresa(t: dict) -> dict:
    pe = t.get("parametro_empresa", pd.DataFrame())
    if pe.empty:
        return dict(PADRAO_EMPRESA, _padrao=True)
    return dict(pe.iloc[0].to_dict(), _padrao=False)


def construir(t: dict, empresa: str) -> dict[str, pd.DataFrame]:
    cob = t["cobertura_saldo"]
    if cob.empty:
        return {"fato_planejamento_sku": pd.DataFrame(), "fato_risco_validade": pd.DataFrame()}
    P = parametros_empresa(t)
    skus = t["dim_sku"][t["dim_sku"]["sku_sk"] > 0].set_index("sku_sk")
    locais = t["dim_local"].set_index("local_sk")
    lotes = t["dim_lote"].set_index("lote_sk")
    cal = t["dim_calendario_operacional"]
    util = set(cal.loc[cal["dia_util"], "data"]) if not cal.empty else None
    param = t["parametro_sku_local"].set_index(["sku_sk", "site"]) if not t["parametro_sku_local"].empty else None
    sintetico = bool(cob["sintetico"].any())

    saldo = t["fato_saldo_diario"].copy()
    if not saldo.empty:
        saldo["site"] = saldo["local_sk"].map(locais["site"])
        saldo["tipo_local"] = saldo["local_sk"].map(locais["tipo"])
    pv = t["fato_evento_pedido_venda"]
    mov = t["fato_movimento_estoque"]
    tipos = t["dim_tipo_movimento"].set_index("tipo_movimento_sk")["codigo"]
    consumo = mov[mov["tipo_movimento_sk"].map(tipos) == "SAIDA_CONSUMO"] if not mov.empty else mov
    cont = _atual(t["fato_contagem"])
    cont = cont[cont["e_final"]] if not cont.empty else cont
    rec = _atual(t["fato_recebimento"])
    pc = t["fato_pedido_compra_linha"]
    prog = _atual(t["fato_programacao_op"])
    prog = prog[prog["congelada"]] if not prog.empty else prog
    psku = t["parceiro_sku"]
    unid = t["sku_unidade"]
    clientes = t["dim_cliente"].set_index("cliente_sk") if not t["dim_cliente"].empty else pd.DataFrame()
    acordo = {(r.cliente_sk, r.sku_sk): r.validade_minima_dias for r in t["acordo_validade"].itertuples()} \
        if not t["acordo_validade"].empty else {}

    # lead time realizado por recebimento (dias corridos), ligado à emissão do PC
    lt_obs = pd.DataFrame()
    if not rec.empty and not pc.empty:
        pcs = pc[["numero_pc", "item", "data_emissao"]].rename(columns={"item": "item_pc"})
        lt_obs = rec[["numero_pc", "item_pc", "data", "qtd_recebida", "sku_sk"]].merge(pcs, on=["numero_pc", "item_pc"])
        lt_obs["lt"] = [(a - b).days for a, b in zip(lt_obs["data"], lt_obs["data_emissao"])]

    linhas, riscos = [], []
    for site, dias_site in cob.groupby("site")["data_saldo"]:
        dias_site = sorted(dias_site)
        inicio = dias_site[0]
        skus_site = set(saldo.loc[saldo["site"] == site, "sku_sk"]) if not saldo.empty else set()
        if param is not None:
            skus_site |= {s for s, st in param.index if st == site}
        series = {s: _serie_demanda(s, skus.loc[s, "tipo"] if s in skus.index else None, pv, consumo, locais, site)
                  for s in skus_site if s in skus.index}
        for D in dias_site:
            util_janela = [inicio + timedelta(days=i) for i in range((D - inicio).days + 1)]
            util_janela = [x for x in util_janela if (util is None or x in util) and x > D - timedelta(days=P["janela_demanda_dias"])]
            estado = {}
            for s in series:
                dem = np.array([series[s].get(x, 0.0) for x in util_janela], dtype=float)
                estado[s] = dem
            valor = {s: (estado[s].mean() if len(estado[s]) else 0.0) * _custo(s, saldo, mov) for s in estado}
            abc = _classe_abc(valor)
            for s, dem in estado.items():
                linha = _linha(s, site, D, dem, abc.get(s, "C"), P, skus, param, saldo, cont, lt_obs, psku, unid,
                               pv, pc, prog, clientes, acordo, util, sintetico, empresa, mov)
                linhas.append(linha)
                riscos.extend(_risco(s, site, D, linha, saldo, lotes, skus, param, sintetico, empresa, mov))
    plan = pd.DataFrame(linhas).drop(columns=["_vmin", "_transito"], errors="ignore")
    return {"fato_planejamento_sku": plan, "fato_risco_validade": pd.DataFrame(riscos)}


# ----------------------------------------------------------------------------- partes

def _serie_demanda(sku_sk, tipo, pv, consumo, locais, site) -> dict:
    """PA/revenda: pedido do cliente por data desejada (não faturamento: demanda censurada). MP: consumo."""
    if tipo in ("PA", "REVENDA") and not pv.empty:
        g = pv[(pv["sku_sk"] == sku_sk) & (pv["site"] == site)].groupby("data_desejada")["delta_qtd"].sum()
        return {d: max(0.0, float(q)) for d, q in g.items()}
    if not consumo.empty:
        c = consumo[(consumo["sku_sk"] == sku_sk) & (consumo["local_sk"].map(locais["site"]) == site)]
        g = c.groupby("data_movimento")["qtd"].sum()
        return {d: max(0.0, float(-q)) for d, q in g.items()}
    return {}


def _custo(sku_sk, saldo, mov) -> float:
    if not saldo.empty:
        c = saldo.loc[saldo["sku_sk"] == sku_sk, "custo_unit_medio"]
        if len(c):
            return float(c.iloc[-1])
    if not mov.empty:
        c = mov.loc[mov["sku_sk"] == sku_sk, "custo_unit"]
        if len(c):
            return float(c.iloc[-1])
    return 0.0


def _classe_abc(valor: dict) -> dict:
    total = sum(valor.values())
    if total <= 0:
        return {s: "C" for s in valor}
    acum, classe = 0.0, {}
    for s, v in sorted(valor.items(), key=lambda kv: -kv[1]):
        antes = acum / total
        acum += v
        classe[s] = "A" if antes < 0.80 else "B" if antes < 0.95 else "C"
    return classe


def _vmin_sku_local(sku_sk, site, D, P, skus, pv, clientes, acordo) -> int:
    """Validade mínima mais restritiva entre os clientes que pediram o SKU na janela (acordo > cliente > SKU)."""
    padrao = skus.loc[sku_sk, "validade_minima_padrao_dias"]
    padrao = 0 if pd.isna(padrao) else int(padrao)
    if pv.empty:
        return padrao
    janela = pv[(pv["sku_sk"] == sku_sk) & (pv["site"] == site) & (pv["data_evento"] <= D)
                & (pv["data_evento"] > D - timedelta(days=int(P["janela_clientes_dias"])))]
    valores = []
    for c in set(janela["cliente_sk"]):
        if (c, sku_sk) in acordo:
            valores.append(int(acordo[(c, sku_sk)]))
        elif len(clientes) and c in clientes.index and not pd.isna(clientes.loc[c, "validade_minima_dias"]):
            valores.append(int(clientes.loc[c, "validade_minima_dias"]))
        else:
            valores.append(padrao)
    return max(valores) if valores else padrao


def _linha(s, site, D, dem, abc, P, skus, param, saldo, cont, lt_obs, psku, unid, pv, pc, prog, clientes, acordo,
           util, sintetico, empresa, mov) -> dict:
    sku = skus.loc[s]
    par = param.loc[(s, site)] if param is not None and (s, site) in param.index else None
    nivel = float(par["nivel_servico"]) if par is not None else 0.95
    n = len(dem)
    d = float(dem.mean()) if n else 0.0
    sigma_d = float(dem.std(ddof=1)) if n > 1 else 0.0
    nz = dem[dem > 0]
    adi = n / len(nz) if len(nz) else math.inf
    cv2 = float((nz.std(ddof=0) / nz.mean()) ** 2) if len(nz) > 1 and nz.mean() > 0 else 0.0
    padrao = _padrao(adi, cv2) if len(nz) else "SEM_DEMANDA"

    # lead time
    obs = lt_obs[(lt_obs["sku_sk"] == s) & (lt_obs["data"] <= D)
                 & (lt_obs["data"] > D - timedelta(days=int(P["janela_lead_time_dias"])))] if not lt_obs.empty else lt_obs
    if len(obs):
        w = obs["qtd_recebida"].to_numpy(dtype=float)
        x = obs["lt"].to_numpy(dtype=float)
        L = float(np.average(x, weights=w)) if w.sum() > 0 else float(x.mean())
        sigma_L = float(math.sqrt(np.average((x - L) ** 2, weights=w))) if len(x) > 1 and w.sum() > 0 else 0.0
        n_lt, fonte_lt = len(obs), "HISTORICO"
    else:
        contratado = psku.loc[psku["sku_sk"] == s, "lead_time_contratado_dias"] if not psku.empty else pd.Series(dtype=float)
        if par is not None and not pd.isna(par["lead_time_reposicao_dias"]):
            L, fonte_lt = float(par["lead_time_reposicao_dias"]), "PARAMETRO"
        elif len(contratado):
            L, fonte_lt = float(contratado.min()), "CONTRATADO"
        else:
            L, fonte_lt = 1.0, "PADRAO"
        sigma_L, n_lt = 0.0, 0

    # aptidão (acuracidade medida do SKU na janela)
    tol = float(par["tolerancia_contagem_pct"]) if par is not None and not pd.isna(par["tolerancia_contagem_pct"]) \
        else TOLERANCIA_ABC[abc]
    c = cont[(cont["sku_sk"] == s) & (pd.to_datetime(cont["instante_contagem"]).dt.date <= D)
             & (pd.to_datetime(cont["instante_contagem"]).dt.date > D - timedelta(days=int(P["apto_janela_dias"])))] \
        if not cont.empty else cont
    if len(c):
        acerto = (c["qtd_contada"] - c["qtd_sistema_congelada"]).abs() <= tol * c["qtd_sistema_congelada"] + 1e-9
        acur, n_cont = float(acerto.mean()), len(c)
    else:
        acur, n_cont = None, 0
    apto = n_cont >= int(P["apto_n_contagens"]) and acur is not None and acur >= float(P["apto_limiar"])

    # estoque de segurança e ponto de pedido (K09)
    z = NormalDist().inv_cdf(nivel)
    metodo = "NORMAL" if padrao in ("SUAVE", "SEM_DEMANDA") else "QUANTIL_EMPIRICO"
    ss = rop = None
    motivo = None
    if not apto:
        motivo = "acuracidade desconhecida" if n_cont < int(P["apto_n_contagens"]) else "acuracidade abaixo do limiar"
    elif n == 0:
        motivo = "sem histórico de demanda"
    elif metodo == "NORMAL":
        ss = z * math.sqrt(L * sigma_d ** 2 + d ** 2 * sigma_L ** 2)
    else:
        dias_lt = max(1, math.ceil(L))
        rng = np.random.default_rng(abs(hash((int(s) % 100003, D.toordinal()))) % (2 ** 32))
        ltd = rng.choice(dem, size=(AMOSTRAS_BOOTSTRAP, dias_lt), replace=True).sum(axis=1)
        ss = max(0.0, float(np.quantile(ltd, nivel)) - d * dias_lt)
    if ss is not None:
        rop = d * L + ss

    # lote com teto de vida útil (K10)
    custo = _custo(s, saldo, mov)
    H = (float(par["taxa_manter_ano"]) * custo) if par is not None else 0.0
    S = float(par["custo_pedido"]) if par is not None else 0.0
    D_ano = d * DIAS_UTEIS_ANO
    q_eoq = math.sqrt(2 * D_ano * S / H) if H > 0 and D_ano > 0 and S > 0 else None
    pal = unid.loc[(unid["sku_sk"] == s) & (unid["e_unidade_palete"] == "S"), "fator_para_base"] if not unid.empty else []
    pal = float(pal.iloc[0]) if len(pal) else None
    q_palete = (math.ceil(q_eoq / pal) * pal if pal else math.ceil(q_eoq)) if q_eoq else None
    shelf = None if pd.isna(sku["shelf_life_dias"]) else int(sku["shelf_life_dias"])
    transito = int(par["transito_dias"]) if par is not None else 0
    parados = int(par["dias_parados"]) if par is not None else 0
    vmin = _vmin_sku_local(s, site, D, P, skus, pv, clientes, acordo)
    cob_max = (shelf - vmin - transito - parados) if shelf else None
    teto = None
    if cob_max is not None:
        bruto = max(0.0, d * cob_max)
        teto = math.floor(bruto / pal) * pal if pal else math.floor(bruto)
    lote_min = psku.loc[psku["sku_sk"] == s, "lote_minimo"] if not psku.empty else []
    lote_min = float(lote_min.min()) if len(lote_min) else 0.0
    q_lote = (min(q_palete, teto) if teto is not None else q_palete) if q_palete else None
    alerta = bool(teto is not None and d > 0 and (teto <= 0 or teto < lote_min))

    # saldo disponível, cobertura e dias até ruptura (K07, K14)
    hoje = saldo[(saldo["site"] == site) & (saldo["data_saldo"] == D) & (saldo["sku_sk"] == s)] if not saldo.empty else saldo
    disp = float((hoje.loc[hoje["tipo_local"] != "QUARENTENA", "qtd_fisica"]
                  - hoje.loc[hoje["tipo_local"] != "QUARENTENA", "qtd_bloqueada"]
                  - hoje.loc[hoje["tipo_local"] != "QUARENTENA", "qtd_reservada"]).sum()) if len(hoje) else 0.0
    quarentena = float(hoje.loc[hoje["tipo_local"] == "QUARENTENA", "qtd_fisica"].sum()) if len(hoje) else 0.0
    cobertura = disp / d if d > 0 else None
    ruptura = None
    if ss is not None:
        H_proj = int(P["horizonte_projecao_dias"])
        entradas = {D + timedelta(days=max(1, parados)): quarentena}
        if not pc.empty:
            abertos = pc[(pc["sku_sk"] == s) & (pc["site"] == site) & (pc["data_emissao"] <= D)]
            for r in abertos.itertuples():
                if r.data_encerramento is not None and not pd.isna(r.data_encerramento) and r.data_encerramento <= D:
                    continue
                recebido = float(rec_ate(r, D))
                falta = r.qtd_pedida - r.qtd_cancelada - recebido
                if falta > 0:
                    quando = max(r.data_prevista_atual, D + timedelta(days=1))
                    entradas[quando] = entradas.get(quando, 0.0) + falta
        if not prog.empty:
            futuro = prog[(prog["sku_sk"] == s) & (prog["data"] > D) & (prog["data"] <= D + timedelta(days=H_proj))]
            for r in futuro.itertuples():
                entradas[r.data] = entradas.get(r.data, 0.0) + r.qtd_programada
        comprometida = {}
        if not pv.empty and sku["tipo"] in ("PA", "REVENDA"):
            fut = pv[(pv["sku_sk"] == s) & (pv["site"] == site) & (pv["data_evento"] <= D) & (pv["data_desejada"] > D)]
            comprometida = fut.groupby("data_desejada")["delta_qtd"].sum().to_dict()
        posicao = disp
        for k in range(1, H_proj + 1):
            dia = D + timedelta(days=k)
            posicao += entradas.get(dia, 0.0)
            if util is None or dia in util:
                posicao -= max(float(comprometida.get(dia, 0.0)), d)
            if posicao < ss:
                ruptura = k
                break
    gatilho = bool(ruptura is not None and ruptura < L)
    n_min = int(P["n_min_observacoes"])
    provisorio = bool(sintetico or P.get("_padrao") or n < n_min or fonte_lt != "HISTORICO" or n_lt < n_min)

    return {"empresa": empresa, "sintetico": sintetico, "data": D, "data_sk": D.year * 10000 + D.month * 100 + D.day,
            "sku_sk": s, "site": site, "classe_abc": abc, "apto_reposicao": apto, "acuracidade_janela": acur,
            "n_contagens_janela": n_cont, "d": d, "sigma_d": sigma_d, "n_obs_demanda": n,
            "adi": None if math.isinf(adi) else adi, "cv2": cv2, "padrao_demanda": padrao, "L": L, "sigma_L": sigma_L,
            "n_obs_lead_time": n_lt, "fonte_lead_time": fonte_lt, "nivel_servico": nivel, "z": z, "metodo_ss": metodo,
            "ss": ss, "rop": rop, "motivo_nulo": motivo, "q_eoq": q_eoq, "q_palete": q_palete, "cob_max": cob_max,
            "teto_lote": teto, "lote_minimo": lote_min, "q_lote": q_lote, "alerta_lote_inviavel": alerta,
            "saldo_disponivel": disp, "custo_unit": custo, "cobertura_dias": cobertura, "dias_ate_ruptura": ruptura,
            "gatilho_compra": gatilho, "provisorio": provisorio, "_vmin": vmin, "_transito": transito}


def rec_ate(pc_linha, D) -> float:
    """Recebido até D: aproximação pelo acumulado quando o último recebimento já ocorreu até D."""
    ult = pc_linha.data_ultimo_receb
    if ult is None or pd.isna(ult):
        return 0.0
    return pc_linha.qtd_recebida_acum if ult <= D else 0.0


def _risco(s, site, D, linha, saldo, lotes, skus, param, sintetico, empresa, mov) -> list[dict]:
    """K05: consumo FEFO projetado; a parte de um lote que vence antes de ser consumida é risco."""
    shelf = skus.loc[s, "shelf_life_dias"]
    if pd.isna(shelf) or saldo.empty:
        return []
    hoje = saldo[(saldo["site"] == site) & (saldo["data_saldo"] == D) & (saldo["sku_sk"] == s) & (saldo["lote_sk"] > 0)]
    if hoje.empty:
        return []
    por_lote = hoje.groupby("lote_sk")["qtd_fisica"].sum()
    itens = sorted(((l, q, lotes.loc[l, "data_validade"]) for l, q in por_lote.items()
                    if l in lotes.index and not pd.isna(lotes.loc[l, "data_validade"])), key=lambda i: i[2])
    d_corrido = linha["d"] * 6 / 7      # demanda por dia útil → por dia corrido (seg–sáb)
    custo = _custo(s, saldo, mov)
    saida, consumido = [], 0.0
    for lote, q, val in itens:
        t = (val - timedelta(days=linha["_vmin"] + linha["_transito"]) - D).days
        consumivel = min(q, max(0.0, d_corrido * max(t, 0) - consumido))
        consumido += consumivel
        risco = q - consumivel
        saida.append({"empresa": empresa, "sintetico": sintetico, "data": D,
                      "data_sk": D.year * 10000 + D.month * 100 + D.day, "sku_sk": s, "lote_sk": lote, "site": site,
                      "data_validade": val, "validade_minima_dias": linha["_vmin"], "dias_vendaveis": t, "saldo": q,
                      "consumivel": consumivel, "risco_qtd": risco, "risco_valor": risco * custo,
                      "provisorio": linha["provisorio"]})
    return saida
