"""Etapa 8 — painel único, navegável, com drill por dimensão. Área é FILTRO, não página.

Ordem de leitura: (1) ações disparadas por gatilho → (2) números por classe → (3) drill da métrica em foco.
Toda definição vem de semantica/metricas.yaml; todo número vem de app/metricas.py.
Visualização: uma série = uma cor (slot 1 da paleta de referência), barras finas com ponta arredondada,
grade recessiva, tooltip em toda marca, tabela sempre ao lado (skill dataviz).
"""
from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from app import metricas
from app.metricas import AREAS, Filtros

SERIE = "#2a78d6"          # slot 1 (azul) da paleta de referência
CLASSES = [("decisao", "Decisão", "dispara uma ação; tem limiar de gatilho"),
           ("diagnostico", "Diagnóstico", "explica a métrica de decisão; não tem meta"),
           ("integridade", "Integridade", "diz se o dado é confiável o bastante para decidir")]
ROTULO_DIM = {"data": "dia", "sku": "SKU", "lote": "lote", "local": "endereço", "site": "site", "cliente": "cliente",
              "parceiro": "parceiro", "recurso": "recurso", "turno": "turno", "veiculo": "veículo",
              "colaborador": "colaborador", "motivo": "motivo", "procedencia": "procedência", "familia": "família",
              "etapa": "etapa", "etapa_origem": "etapa de origem", "classe_abc": "classe ABC"}


def br(v: float | None, casas: int = 1) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar(valor: float | None, unidade: str) -> str:
    if valor is None:
        return "—"
    if unidade == "%":
        return f"{br(valor, 1)}%"
    if unidade == "moeda":
        return f"R$ {br(valor, 0)}"
    if unidade == "moeda/kg":
        return f"R$ {br(valor, 2)}/kg"
    if unidade in ("contagem",):
        return br(valor, 0)
    if unidade in ("dias", "horas"):
        return f"{br(valor, 1)} {unidade}"
    return br(valor, 1)


def pagina_painel(con_fn):
    c = con_fn()
    st.header("Painel")
    limites = c.execute("SELECT min(data_saldo), max(data_saldo), bool_or(sintetico) FROM cobertura_saldo").fetchone()
    if limites[0] is None:
        st.info("Sem dados. Carregue arquivos em **Carga de arquivos** ou o cenário sintético em **Cargas e integridade**.")
        return
    if limites[2]:
        st.warning("Dados **sintéticos**: os números validam a mecânica (fórmula, fluxo, somatório), não os parâmetros. "
                   "Tudo aparece como provisório até a carga de dados reais.", icon="⚠️")

    # ---------------------------------------------------------------- filtros (uma linha)
    sites = [r[0] for r in c.execute("SELECT site FROM dim_site WHERE site_sk > 0 ORDER BY 1").fetchall()]
    familias = [r[0] for r in c.execute("SELECT DISTINCT familia FROM dim_sku WHERE sku_sk > 0 AND familia IS NOT NULL ORDER BY 1").fetchall()]
    clientes = [r[0] for r in c.execute("SELECT cliente FROM dim_cliente WHERE cliente_sk > 0 ORDER BY 1").fetchall()]
    f1, f2, f3, f4, f5 = st.columns([2.2, 1, 1, 1, 2.4])
    periodo = f1.date_input("Período", value=(limites[0], limites[1]), min_value=limites[0], max_value=limites[1],
                            format="DD/MM/YYYY")
    site = f2.selectbox("Site", ["(todos)"] + sites)
    familia = f3.selectbox("Família", ["(todas)"] + familias)
    cliente = f4.selectbox("Cliente", ["(todos)"] + clientes)
    areas = f5.multiselect("Área (filtro)", list(AREAS), default=list(AREAS))
    if not isinstance(periodo, tuple) or len(periodo) != 2:
        st.caption("Escolha início e fim do período.")
        return
    filtros = Filtros(periodo[0], periodo[1], None if site.startswith("(") else site,
                      None if familia.startswith("(") else familia, None, None if cliente.startswith("(") else cliente)
    kids = [k for a in areas for k in AREAS[a]]
    if not kids:
        st.info("Escolha ao menos uma área.")
        return
    defs = metricas.definicoes()

    # ---------------------------------------------------------------- 1. ações
    gat = metricas.gatilhos(c, filtros)
    gat = gat[gat["métrica"].isin(kids)]
    st.subheader("Ações disparadas")
    if gat.empty:
        st.success("Nenhum gatilho acionado no período e área escolhidos.")
    else:
        resumo = gat.groupby(["métrica", "nome", "decisão", "dono"]).size().reset_index(name="ocorrências")
        st.dataframe(resumo, hide_index=True, width="stretch")
        with st.expander(f"Ver as {len(gat)} ocorrências"):
            st.dataframe(gat, hide_index=True, width="stretch",
                         column_config={"valor": st.column_config.NumberColumn(format="%.2f")})

    # ---------------------------------------------------------------- 2. números por classe
    resultados = {k: metricas.calcular(c, k, filtros) for k in kids}
    for classe, titulo, legenda in CLASSES:
        do_grupo = [k for k in kids if defs[k]["classe"] == classe]
        if not do_grupo:
            continue
        st.subheader(titulo)
        st.caption(legenda)
        for i in range(0, len(do_grupo), 4):
            cols = st.columns(4)
            for col, k in zip(cols, do_grupo[i:i + 4]):
                with col.container(border=True):
                    _tile(k, resultados[k], defs[k], gat)

    # ---------------------------------------------------------------- 3. drill
    st.subheader("Abrir métrica")
    d1, d2 = st.columns([2, 1])
    foco = d1.selectbox("Métrica", kids, format_func=lambda k: f"{k} — {defs[k]['nome']}")
    opcoes = metricas.permitidas(foco) + ["data"]
    padrao = metricas.REGISTRO[foco].drill_padrao
    por = d2.selectbox("Abrir por", opcoes, index=opcoes.index(padrao) if padrao in opcoes else 0,
                       format_func=lambda d: ROTULO_DIM.get(d, d))
    df = metricas.drill(c, foco, filtros, por)
    r = resultados[foco]
    if df.empty:
        st.info("Sem dados para esta combinação de filtros.")
    else:
        _grafico(df, por, r.unidade, defs[foco]["nome"])
        tabela = df.rename(columns={"grupo": ROTULO_DIM.get(por, por), "valor": f"valor ({r.unidade})",
                                    "n": "linhas", "pct_estimado": "% estimado"})
        tabela = tabela.drop(columns=[c for c in ("conf", "n_unidades") if c in tabela])
        if "% estimado" in tabela:
            tabela["% estimado"] = tabela["% estimado"] * 100
        st.dataframe(tabela, hide_index=True, width="stretch",
                     column_config={f"valor ({r.unidade})": st.column_config.NumberColumn(format="%.2f"),
                                    "% estimado": st.column_config.NumberColumn(format="%.0f%%")})
    with st.expander("Definição (semantica/metricas.yaml)"):
        d = defs[foco]
        st.markdown(f"**Fórmula:** `{d['formula'].strip()}`  \n**Unidade:** {d['unidade']} · **Dono:** {d['dono']} · "
                    f"**Decisões:** {', '.join(d['decisoes'])} · **Direção:** {d['direcao']}")
        for campo in ("gatilho", "nulo_quando", "aviso_exibicao", "provisorio_se", "grao_calculo"):
            if campo in d:
                st.markdown(f"**{campo.replace('_', ' ').capitalize()}:** {d[campo]}")
        if "agregado" in d:
            st.markdown(f"**Leitura agregada:** {d['agregado']['leitura']}")
        if r.filtros_ignorados:
            st.caption(f"Filtro que não se aplica a esta métrica e foi ignorado: {', '.join(r.filtros_ignorados)}.")


def _tile(k: str, r: metricas.Resultado, d: dict, gat: pd.DataFrame) -> None:
    st.caption(f"{k} · {d['nome']}")
    st.markdown(f"<div style='font-size:1.9rem;font-weight:600;line-height:1.2'>{formatar(r.valor, r.unidade)}</div>",
                unsafe_allow_html=True)
    if r.valor is None and r.motivo_nulo:
        st.caption(f"Nulo: {r.motivo_nulo}")
    linhas = []
    if "agregado" in d:
        linhas.append(d["agregado"]["leitura"])
    if r.secundario:
        v2 = r.secundario[1]
        linhas.append(f"{r.secundario[0]}: {br(v2, 0 if float(v2).is_integer() or abs(v2) >= 10 else 2)}")
    if r.p90 is not None:
        linhas.append(f"P90: {br(r.p90, 1)} h")
    marcas = []
    acionado = (gat["métrica"] == k).sum() if not gat.empty else 0
    if acionado:
        marcas.append(f"⚠ gatilho ×{acionado}")
    if d.get("meta") == "proibida":
        marcas.append("sem meta")
    if r.provisorio:
        marcas.append("provisório")
    marcas.append(f"fonte {r.confiabilidade.lower()}")
    if r.pct_estimado > 0:
        marcas.append(f"{r.pct_estimado:.0%} estimado")
    if linhas:
        st.caption(" · ".join(linhas))
    st.caption(" · ".join(marcas) + f" · n={r.n_linhas}")
    if d.get("aviso_exibicao"):
        st.caption(f"ℹ {d['aviso_exibicao']}")


def _grafico(df: pd.DataFrame, por: str, unidade: str, nome: str) -> None:
    dados = df[["grupo", "valor"]].dropna().copy()
    if dados.empty:
        st.caption("Valores nulos neste recorte (ver tabela).")
        return
    eixo_y = alt.Axis(grid=True, gridOpacity=0.15, domain=False, ticks=False, title=unidade)
    if por == "data":
        dados["grupo"] = pd.to_datetime(dados["grupo"])
        base = alt.Chart(dados).encode(
            x=alt.X("grupo:T", title=None, axis=alt.Axis(grid=False, format="%d/%m")),
            y=alt.Y("valor:Q", axis=eixo_y))
        sel = alt.selection_point(on="pointerover", nearest=True, fields=["grupo"], empty=False)
        linha = base.mark_line(strokeWidth=2, color=SERIE)
        pontos = base.mark_circle(size=64, color=SERIE).add_params(sel).encode(
            opacity=alt.condition(sel, alt.value(1), alt.value(0)),
            tooltip=[alt.Tooltip("grupo:T", title="dia", format="%d/%m/%Y"),
                     alt.Tooltip("valor:Q", title=nome, format=",.2f")])
        regra = alt.Chart(dados).mark_rule(color="#8a8984", strokeWidth=1).encode(x="grupo:T").transform_filter(sel)
        st.altair_chart((linha + regra + pontos).properties(height=260), width="stretch")
    else:
        dados["grupo"] = dados["grupo"].astype(str)
        altura = max(120, min(30 * len(dados), 600))
        barras = alt.Chart(dados).mark_bar(color=SERIE, cornerRadiusEnd=4, size=12).encode(
            y=alt.Y("grupo:N", sort="-x", title=None,
                    axis=alt.Axis(ticks=False, domain=False, labelOverlap=False, labelLimit=220)),
            x=alt.X("valor:Q", axis=alt.Axis(grid=True, gridOpacity=0.15, domain=False, ticks=False, title=unidade)),
            tooltip=[alt.Tooltip("grupo:N", title=ROTULO_DIM.get(por, por)),
                     alt.Tooltip("valor:Q", title=nome, format=",.2f")])
        st.altair_chart(barras.properties(height=altura), width="stretch")
