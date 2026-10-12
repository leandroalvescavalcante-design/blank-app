"""Motor de métricas: executa K01–K19 sobre as visões analíticas (sql/visoes.sql).

A DEFINIÇÃO de cada métrica (fórmula, unidade, dono, dimensões, direção) mora em semantica/metricas.yaml (R1).
Aqui está só a execução: qual visão, quais medidas, qual agregação. O teste test_metricas garante que
registro e YAML não divergem (mesmos IDs, dimensões de drill dentro das permitidas).

Regras globais aplicadas pelo motor (docs/06-camada-semantica.md):
R2 nulo com motivo · R4 razão das somas · R5 semiaditivo = último dia · R6 percentil recalculado no grupo ·
R7 unidades misturadas bloqueadas · R8 procedência propaga · R9 provisório propaga.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

import pandas as pd
import yaml

from app.config import ARQ_METRICAS

# Dimensão do YAML → coluna da visão. "data" é tratada à parte (série temporal).
COLUNA = {"sku": "sku", "lote": "lote", "local": "endereco", "cliente": "cliente", "parceiro": "parceiro",
          "recurso": "recurso", "turno": "turno", "veiculo": "veiculo", "colaborador": "colaborador",
          "motivo": "motivo", "procedencia": "fonte", "familia": "familia", "etapa": "etapa",
          "etapa_origem": "etapa_origem", "classe_abc": "classe_abc", "site": "site"}
AREAS = {"Estoque": ["K01", "K02", "K02b", "K03", "K04", "K05", "K06", "K07", "K08"],
         "Planejamento": ["K09", "K10", "K11", "K12", "K13", "K14"],
         "Pedido e expedição": ["K15", "K16", "K17", "K18", "K19"]}
RANK = {"ALTA": 3, "MEDIA": 2, "BAIXA": 1}


@dataclass
class Execucao:
    visao: str
    agregacao: str                    # razao | soma | ultimo_soma | ultimo_razao | percentil | media | contagem_ultimo
    num: str = "num"
    den: str | None = "den"
    filtro: str | None = None
    escala: float = 1.0               # 100 para %
    drill_padrao: str | None = None
    extra: dict = field(default_factory=dict)


REGISTRO: dict[str, Execucao] = {
    "K01": Execucao("vm_contagem", "razao", escala=100, drill_padrao="sku"),
    "K02": Execucao("vm_mov", "soma", num="valor_abs", den=None,
                    filtro="tipo_movimento IN ('AJUSTE_POSITIVO','AJUSTE_NEGATIVO')", drill_padrao="etapa_origem"),
    "K02b": Execucao("vm_mov", "razao", num="CASE WHEN etapa_origem = 'DESCONHECIDA' THEN valor_abs ELSE 0 END",
                     den="valor_abs", filtro="tipo_movimento IN ('AJUSTE_POSITIVO','AJUSTE_NEGATIVO')", escala=100,
                     drill_padrao="sku"),
    "K03": Execucao("vm_mov", "soma", num="valor_abs", den=None,
                    filtro="tipo_movimento IN ('AJUSTE_POSITIVO','AJUSTE_NEGATIVO')", drill_padrao="local",
                    extra={"secundario": ("líquido", "sum(valor)")}),
    "K04": Execucao("vm_reconciliacao", "soma", num="excecao", den=None, drill_padrao="sku"),
    "K05": Execucao("vm_risco", "ultimo_soma", num="risco_valor", den=None, drill_padrao="lote",
                    extra={"secundario": ("lotes em risco", "count(*) FILTER (WHERE risco_qtd > 1e-9)")}),
    "K06": Execucao("vm_mov", "soma", num="valor_abs", den=None, filtro="tipo_movimento = 'BAIXA'",
                    drill_padrao="motivo"),
    "K07": Execucao("vm_planejamento", "ultimo_razao", num="saldo_disponivel * custo_unit", den="d * custo_unit",
                    drill_padrao="sku"),
    "K08": Execucao("vm_saldo", "ultimo_soma", num="valor", den=None, drill_padrao="sku"),
    "K09": Execucao("vm_planejamento", "ultimo_razao", num="CASE WHEN rop IS NOT NULL THEN 1 ELSE 0 END", den="1",
                    escala=100, drill_padrao="sku"),
    "K10": Execucao("vm_planejamento", "ultimo_soma", num="CASE WHEN alerta_lote_inviavel THEN 1 ELSE 0 END",
                    den=None, drill_padrao="sku"),
    "K11": Execucao("vm_programacao", "razao", escala=100, drill_padrao="turno"),
    "K12": Execucao("vm_aderencia", "razao", escala=100, drill_padrao="sku"),
    "K13": Execucao("vm_leadtime", "razao", drill_padrao="parceiro"),
    "K14": Execucao("vm_planejamento", "ultimo_soma", num="CASE WHEN gatilho_compra THEN 1 ELSE 0 END", den=None,
                    drill_padrao="sku"),
    "K15": Execucao("vm_ciclo_linha", "razao", escala=100, drill_padrao="cliente"),
    "K16": Execucao("vm_ciclo", "razao", escala=100, drill_padrao="cliente", extra={"unidade_sensivel": True}),
    "K17": Execucao("vm_etapas", "percentil", num="horas", den=None, filtro="etapa = '0 ciclo total'",
                    drill_padrao="etapa", extra={"sem_filtro_no_drill": "etapa"}),
    "K18": Execucao("vm_viagem", "media", num="ocupacao", den=None, escala=100, drill_padrao="veiculo"),
    "K19": Execucao("vm_frete", "razao", drill_padrao="cliente"),
}

# Como o painel lê cada métrica agregada (rótulo do valor quando não é a fórmula literal do YAML).
ROTULO_AGREGADO = {"K09": "% dos SKUs com ponto de pedido calculável", "K10": "SKUs com lote inviável",
                   "K14": "SKUs com ruptura antes do lead time", "K17": "mediana do ciclo total (h)",
                   "K05": "R$ em risco de vencimento", "K04": "exceções de reconciliação"}


@lru_cache(maxsize=1)
def definicoes() -> dict:
    return yaml.safe_load(ARQ_METRICAS.read_text(encoding="utf-8"))["metricas"]


@dataclass
class Filtros:
    inicio: date
    fim: date
    site: str | None = None
    familia: str | None = None
    sku: str | None = None
    cliente: str | None = None


@dataclass
class Resultado:
    kid: str
    valor: float | None
    motivo_nulo: str | None
    unidade: str
    provisorio: bool
    confiabilidade: str
    pct_estimado: float
    n_linhas: int
    secundario: tuple[str, float] | None
    filtros_ignorados: list[str]
    p90: float | None = None


def _colunas(con, visao: str) -> set[str]:
    return {r[0] for r in con.execute(f"DESCRIBE {visao}").fetchall()}


def _where(con, ex: Execucao, f: Filtros, ignorar_filtro_proprio: bool = False) -> tuple[str, list, list[str]]:
    cols = _colunas(con, ex.visao)
    partes, params, ignorados = ["data BETWEEN ? AND ?"], [f.inicio, f.fim], []
    for nome, valor in (("site", f.site), ("familia", f.familia), ("sku", f.sku), ("cliente", f.cliente)):
        if valor is None:
            continue
        if nome in cols:
            partes.append(f"{nome} = ?")
            params.append(valor)
        else:
            ignorados.append(nome)
    if ex.filtro and not ignorar_filtro_proprio:
        partes.append(f"({ex.filtro})")
    return " AND ".join(partes), params, ignorados


def _agregado(ex: Execucao) -> str:
    if ex.agregacao in ("razao", "ultimo_razao"):
        return f"sum({ex.num}) / nullif(sum({ex.den}), 0)"
    if ex.agregacao in ("soma", "ultimo_soma"):
        return f"sum({ex.num})"
    if ex.agregacao == "media":
        return f"avg({ex.num})"
    if ex.agregacao == "percentil":
        return f"quantile_cont({ex.num}, 0.5)"
    raise ValueError(ex.agregacao)


def _sql_base(con, ex: Execucao, f: Filtros, grupo: str | None, ignorar_filtro_proprio=False):
    where, params, ignorados = _where(con, ex, f, ignorar_filtro_proprio)
    if ex.agregacao.startswith("ultimo"):
        # R5: semiaditivo usa o último dia do período (por site, se houver mais de um)
        where = f"{where} AND data = (SELECT max(data) FROM {ex.visao} WHERE {where})"
        params = params + params
    cols = _colunas(con, ex.visao)
    conf = "min(CASE confiabilidade WHEN 'ALTA' THEN 3 WHEN 'MEDIA' THEN 2 WHEN 'BAIXA' THEN 1 END)"
    est = "avg(CASE WHEN fonte = 'ESTIMADO' THEN 1.0 ELSE 0.0 END)"
    if "estimado" in cols:
        est = "avg(CASE WHEN fonte = 'ESTIMADO' OR estimado THEN 1.0 ELSE 0.0 END)"
    sel = [f"{_agregado(ex)} AS valor", "count(*) AS n", "bool_or(sintetico) OR bool_or(provisorio) AS provisorio",
           f"{conf} AS conf", f"{est} AS pct_estimado"]
    if ex.agregacao == "percentil":
        sel.append(f"quantile_cont({ex.num}, 0.9) AS p90")
    if "secundario" in ex.extra:
        sel.append(f"{ex.extra['secundario'][1]} AS secundario")
    if ex.extra.get("unidade_sensivel") and "unidade_base" in cols:
        sel.append("count(DISTINCT unidade_base) AS n_unidades")
    g = f"{grupo} AS grupo, " if grupo else ""
    sql = f"SELECT {g}{', '.join(sel)} FROM {ex.visao} WHERE {where}"
    if grupo:
        sql += " GROUP BY grupo ORDER BY grupo"
    return sql, params, ignorados


def calcular(con, kid: str, f: Filtros) -> Resultado:
    ex, d = REGISTRO[kid], definicoes()[kid]
    unidade = d.get("agregado", {}).get("unidade", d["unidade"])
    if kid == "K04":
        return _k04(con, f, unidade)
    sql, params, ignorados = _sql_base(con, ex, f, None)
    r = con.execute(sql, params).df().iloc[0]
    valor = None if pd.isna(r["valor"]) else float(r["valor"]) * ex.escala
    motivo = None
    if int(r["n"]) == 0:
        motivo = "sem dados no período"
    elif valor is None:
        motivo = "denominador zero"
    if "n_unidades" in r and not pd.isna(r["n_unidades"]) and int(r["n_unidades"]) > 1:
        valor, motivo = None, "unidades diferentes no grupo; abra por SKU (R7)"
    sec = None
    if "secundario" in ex.extra and not pd.isna(r.get("secundario")):
        sec = (ex.extra["secundario"][0], float(r["secundario"]))
    conf = {3: "ALTA", 2: "MEDIA", 1: "BAIXA"}.get(None if pd.isna(r["conf"]) else int(r["conf"]), "DERIVADO")
    p90 = float(r["p90"]) if "p90" in r and not pd.isna(r["p90"]) else None
    return Resultado(kid, valor, motivo, unidade, bool(r["provisorio"]) if not pd.isna(r["provisorio"]) else True,
                     conf, float(r["pct_estimado"] or 0) if not pd.isna(r["pct_estimado"]) else 0.0, int(r["n"]),
                     sec, ignorados, p90)


def _k04(con, f: Filtros, unidade: str) -> Resultado:
    """K04 só existe onde há fotografia no dia e na véspera; sem isso é 'não verificável' (R2)."""
    where_site = " AND site = ?" if f.site else ""
    p_site = [f.site] if f.site else []
    dias = con.execute(f"SELECT count(*), bool_or(sintetico) FROM vm_dias_verificaveis WHERE data BETWEEN ? AND ?{where_site}",
                       [f.inicio, f.fim, *p_site]).fetchone()
    if not dias[0]:
        return Resultado("K04", None, "não verificável (sem fotografia do dia e da véspera)", unidade, True, "ALTA",
                         0.0, 0, None, [])
    filtros_sku = ""
    params = [f.inicio, f.fim, *p_site]
    for nome, valor in (("familia", f.familia), ("sku", f.sku)):
        if valor:
            filtros_sku += f" AND {nome} = ?"
            params.append(valor)
    exc = con.execute(f"SELECT coalesce(sum(excecao), 0) FROM vm_reconciliacao WHERE data BETWEEN ? AND ?{where_site}{filtros_sku}",
                      params).fetchone()[0]
    return Resultado("K04", float(exc), None, unidade, bool(dias[1]), "ALTA", 0.0, int(dias[0]),
                     ("dias verificados", float(dias[0])), ["cliente"] if f.cliente else [])


def drill(con, kid: str, f: Filtros, por: str) -> pd.DataFrame:
    """Abre a métrica por uma dimensão permitida no YAML. Percentil e razão são recalculados no grupo (R4, R6)."""
    ex = REGISTRO[kid]
    if por == "data":
        grupo = "data"
    else:
        if por not in permitidas(kid):
            raise ValueError(f"{kid} não abre por {por}")
        grupo = COLUNA[por]
    ignorar = ex.extra.get("sem_filtro_no_drill") == por
    sql, params, _ = _sql_base(con, ex, f, grupo, ignorar_filtro_proprio=ignorar)
    if kid == "K04":
        sql, params, _ = _sql_base(con, ex, f, grupo)
    df = con.execute(sql, params).df()
    df["valor"] = df["valor"] * ex.escala
    if "n_unidades" in df:
        df.loc[df["n_unidades"] > 1, "valor"] = None
    return df


def permitidas(kid: str) -> list[str]:
    """Dimensões de drill = as do YAML que existem como coluna na visão (data à parte)."""
    d = definicoes()[kid]["dimensoes"]
    extras = {"K02": ["etapa_origem"], "K02b": ["etapa_origem"], "K03": ["etapa_origem"], "K17": ["etapa"],
              "K01": ["classe_abc"], "K07": ["familia"], "K08": ["familia"]}
    return [x for x in d if x != "data"] + extras.get(kid, [])


def gatilhos(con, f: Filtros) -> pd.DataFrame:
    """Lista de ações: cada gatilho acionado vira uma linha com a decisão da Etapa 0 que ele dispara."""
    defs = definicoes()
    pe = con.execute("SELECT * FROM parametro_empresa LIMIT 1").df()
    limiar_k02b = float(pe["limiar_k02b"].iloc[0]) if not pe.empty else 0.3
    limiar_ocup = float(pe["limiar_ocupacao"].iloc[0]) if not pe.empty else 0.6
    site = " AND site = ?" if f.site else ""
    ps = [f.site] if f.site else []
    linhas = []

    def add(kid, objeto, detalhe, valor):
        linhas.append({"métrica": kid, "nome": defs[kid]["nome"], "decisão": ", ".join(defs[kid]["decisoes"]),
                       "dono": defs[kid]["dono"], "objeto": objeto, "detalhe": detalhe, "valor": valor})

    for r in con.execute(f"""SELECT site, data, sku, endereco, dif_reconciliacao FROM vm_reconciliacao
                             WHERE excecao = 1 AND data BETWEEN ? AND ?{site}""", [f.inicio, f.fim, *ps]).fetchall():
        add("K04", f"{r[2]} @ {r[3]}", f"{r[1]}: saldo não fecha com movimentos", r[4])
    for r in con.execute(f"""SELECT sku, lote, data_validade, risco_qtd, risco_valor FROM vm_risco
                             WHERE risco_qtd > 1e-9 AND data = (SELECT max(data) FROM vm_risco WHERE data <= ?){site}""",
                         [f.fim, *ps]).fetchall():
        add("K05", f"{r[0]} lote {r[1]}", f"vence {r[2]}; {r[3]:.0f} un sem saída prevista", r[4])
    plan = f"data = (SELECT max(data) FROM vm_planejamento WHERE data <= ?){site}"
    for r in con.execute(f"SELECT sku, teto_lote, lote_minimo FROM vm_planejamento WHERE alerta_lote_inviavel AND {plan}",
                         [f.fim, *ps]).fetchall():
        add("K10", r[0], f"teto de vida útil {r[1]:.0f} < lote mínimo {r[2]:.0f}", r[1])
    for r in con.execute(f"SELECT sku, dias_ate_ruptura, L FROM vm_planejamento WHERE gatilho_compra AND {plan}",
                         [f.fim, *ps]).fetchall():
        add("K14", r[0], f"ruptura projetada em {r[1]} dia(s) < lead time {r[2]:.1f}", r[1])
    for r in con.execute(f"SELECT sku, motivo_nulo FROM vm_planejamento WHERE rop IS NULL AND {plan}",
                         [f.fim, *ps]).fetchall():
        add("K09", r[0], f"ponto de pedido nulo: {r[1]}", None)
    for r in con.execute(f"""SELECT recurso, turno, data, num / den FROM vm_programacao
                             WHERE num > den AND data BETWEEN ? AND ?{site}""", [f.inicio, f.fim, *ps]).fetchall():
        add("K11", f"{r[0]} {r[1]}", f"{r[2]}: carga {r[3]:.0%} do disponível", r[3] * 100)
    k02b = calcular(con, "K02b", f)
    if k02b.valor is not None and k02b.valor / 100 > limiar_k02b:
        add("K02b", "divergências", f"{k02b.valor:.0f}% sem origem identificada (limiar {limiar_k02b:.0%})", k02b.valor)
    for r in con.execute(f"""SELECT numero_viagem, veiculo, ocupacao FROM vm_viagem
                             WHERE ocupacao < ? AND data BETWEEN ? AND ?{site}""",
                         [limiar_ocup, f.inicio, f.fim, *ps]).fetchall():
        add("K18", f"{r[0]} ({r[1]})", f"ocupação {r[2]:.0%} < limiar {limiar_ocup:.0%}", r[2] * 100)
    return pd.DataFrame(linhas, columns=["métrica", "nome", "decisão", "dono", "objeto", "detalhe", "valor"])
