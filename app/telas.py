"""Páginas das telas de entrada (Etapa 7) — derivadas dos fatos da frente 1.

Upload (CSV/XLSX) e formulários passam pela MESMA validação (entrada/layouts.yaml) e gravam na camada
bruta imutável; dimensões e fatos são reconstruídos a partir dela. O dashboard é a Etapa 8.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from app import carga, consultas
from app.config import caminho_banco
from app.db import conectar
from app.validacao import especificacao, ler_arquivo, modelo_csv

@st.cache_resource
def _conexao_base(caminho: str):
    con = conectar(caminho)
    carga.garantir_modelo(con)
    return con


def con():
    # um cursor por execução: DuckDB não compartilha conexão entre threads
    return _conexao_base(str(caminho_banco())).cursor()


def usuario() -> str | None:
    u = st.session_state.get("usuario", "").strip()
    return u or None


def exigir_usuario() -> bool:
    if not usuario():
        st.warning("Informe o usuário na barra lateral. Toda gravação no bruto registra quem gravou.")
        return False
    return True


def mostrar_resultado(r: carga.ResultadoCarga) -> None:
    {"ACEITA": st.success, "DUPLICADA": st.info, "RECUSADA": st.error}[r.status](r.mensagem)
    if r.status == "RECUSADA":
        st.dataframe(r.validacao.tabela_erros(), hide_index=True, width="stretch")


# ----------------------------------------------------------------------------- páginas

def pagina_upload():
    st.header("Carga de arquivos")
    layouts = {k: v for k, v in especificacao()["layouts"].items() if v.get("implementado") and "upload" in v["canal"]}
    nome = st.selectbox("Layout", list(layouts), format_func=lambda k: f"{k} — {layouts[k]['descricao']}")
    spec = layouts[nome]
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption(f"Chave de negócio: {', '.join(spec['chave'])}. "
                   + ("Fotografia: substitui por inteiro a anterior do mesmo " + " × ".join(spec["snapshot"]["por"]) + "."
                      if "snapshot" in spec else "Linha com a mesma chave e conteúdo diferente vira correção (estorno + nova)."))
    with col2:
        st.download_button("Baixar modelo CSV", modelo_csv(nome), file_name=f"{nome}.csv", mime="text/csv")
    with st.expander("Campos do layout"):
        st.dataframe(_tabela_campos(spec), hide_index=True, width="stretch")

    arquivo = st.file_uploader("Arquivo (CSV com ';' ou ',', ou XLSX)", type=["csv", "xlsx"], key=f"up_{nome}")
    if arquivo is None:
        return
    try:
        df = ler_arquivo(arquivo.getvalue(), arquivo.name)
    except Exception as exc:  # noqa: BLE001 — arquivo ilegível é recusado com mensagem
        st.error(f"Não foi possível ler o arquivo: {exc}")
        return
    res = carga.pre_validar(con(), nome, df)
    st.write(f"{len(df)} linha(s) lida(s).")
    if res.valido:
        st.success("Validação sem erros.")
    else:
        st.error(f"{res.n_erros} erro(s). Política tudo-ou-nada: corrija o arquivo; se registrar, a carga entra como RECUSADA "
                 "(fica no histórico, nada chega ao modelo).")
        st.dataframe(res.tabela_erros(), hide_index=True, width="stretch")
    sintetico = st.checkbox("Dados sintéticos (tudo o que derivar nasce provisório)", value=False)
    if st.button("Registrar carga", type="primary", disabled=not usuario()):
        r = carga.registrar(con(), nome, df, usuario=usuario(), fonte="UPLOAD", nome_arquivo=arquivo.name,
                            sintetico=sintetico)
        mostrar_resultado(r)
    if not usuario():
        st.caption("Informe o usuário na barra lateral para registrar.")


def pagina_contagem():
    st.header("Contagem cega")
    st.caption("O saldo do sistema é congelado ao iniciar e nunca é mostrado a quem conta.")
    c = con()
    if not exigir_usuario():
        return
    contadores = consultas.colaboradores(c, ("INVENTARIANTE", "CONFERENTE", "SUPERVISOR"))
    if not contadores:
        st.error("Nenhum colaborador com função de contagem cadastrado (layout cad_colaborador).")
        return

    tarefa = st.session_state.get("tarefa_contagem")
    if tarefa is None:
        modo = st.radio("Tipo", ["Nova contagem", "Recontagem de divergência pendente"], horizontal=True)
        if modo == "Recontagem de divergência pendente":
            pend = consultas.divergencias_pendentes(c)
            if pend.empty:
                st.info("Nenhuma divergência pendente.")
                return
            opcoes = pend.to_dict(orient="records")
            esc = st.selectbox("Divergência", range(len(opcoes)), format_func=lambda i: (
                f"{opcoes[i]['numero_contagem']} · {opcoes[i]['endereco']} · {opcoes[i]['sku']} {opcoes[i]['lote']}"))
            numero, endereco, sku, lote = (opcoes[esc][k] for k in ("numero_contagem", "endereco", "sku", "lote"))
            lote = lote or None
        else:
            enderecos = [r[0] for r in c.execute(
                "SELECT endereco FROM dim_local WHERE local_sk > 0 AND NOT inferido ORDER BY endereco").fetchall()]
            if not enderecos:
                st.error("Nenhum endereço cadastrado (layout cad_local).")
                return
            endereco = st.selectbox("Endereço", enderecos)
            leitura = st.text_input("SKU: leia o código de barras ou digite o código").strip()
            if not leitura:
                return
            achado = c.execute(
                "SELECT sku, controla_lote FROM dim_sku WHERE sku_sk > 0 AND NOT inferido AND (sku = ? OR codigo_barras = ?)",
                [leitura, leitura]).fetchone()
            if achado is None:
                st.error(f"'{leitura}' não corresponde a nenhum SKU cadastrado.")
                return
            sku, controla = achado
            st.write(f"SKU: **{sku}**")
            lote = None
            if controla == "S":
                lotes = consultas.lotes_do_sku(c, sku)
                fora = st.checkbox("O lote físico não aparece na lista")
                lote = st.text_input("Lote (como impresso na embalagem)").strip() if fora or not lotes \
                    else st.selectbox("Lote", lotes)
                if not lote:
                    return
            numero = None
        if st.button("Iniciar contagem (congela o saldo do sistema)", type="primary"):
            agora = datetime.now().replace(microsecond=0)
            congelado = consultas.saldo_congelado(c, endereco, sku, lote, agora)
            if congelado is None:
                st.error("O site deste endereço não tem fotografia de saldo carregada. Sem base, não há contagem comparável.")
                return
            numero = numero or f"CNT-{endereco}-{agora:%Y%m%d%H%M%S}"
            st.session_state["tarefa_contagem"] = {
                "numero_contagem": numero, "endereco": endereco, "sku": sku, "lote": lote or "",
                "numero_recontagem": consultas.proximo_numero_recontagem(c, numero, endereco, sku, lote),
                "qtd_sistema_congelada": congelado[0], "instante_congelamento": agora}
            st.rerun()
        return

    st.info(f"Contagem **{tarefa['numero_contagem']}** (recontagem nº {tarefa['numero_recontagem']}) — "
            f"{tarefa['endereco']} · {tarefa['sku']} {tarefa['lote']}")
    with st.form("contagem"):
        matricula = st.selectbox("Matrícula de quem contou", contadores)
        qtd = st.number_input("Quantidade contada (unidade base)", min_value=0.0, step=1.0, format="%.3f")
        col1, col2 = st.columns(2)
        enviar = col1.form_submit_button("Registrar contagem", type="primary")
        cancelar = col2.form_submit_button("Cancelar")
    if cancelar:
        del st.session_state["tarefa_contagem"]
        st.rerun()
    if enviar:
        linha = {**tarefa, "qtd_contada": qtd, "matricula": matricula,
                 "instante_congelamento": tarefa["instante_congelamento"].strftime("%Y-%m-%d %H:%M:%S"),
                 "instante_contagem": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        r = carga.registrar(c, "contagem", pd.DataFrame([{k: str(v) for k, v in linha.items()}]),
                            usuario=usuario(), fonte="FORMULARIO", nome_arquivo="formulario")
        if r.status == "ACEITA":
            del st.session_state["tarefa_contagem"]
            st.success("Contagem registrada.")  # cega: não mostra a diferença a quem contou
        else:
            mostrar_resultado(r)


def pagina_investigacao():
    st.header("Investigação de divergência")
    st.caption("Atribui a etapa de origem à divergência final. É daqui que sai a divergência por etapa (K02).")
    c = con()
    if not exigir_usuario():
        return
    pend = consultas.divergencias_pendentes(c)
    if pend.empty:
        st.info("Nenhuma divergência final pendente de investigação.")
        return
    st.dataframe(pend, hide_index=True, width="stretch")
    opcoes = pend.to_dict(orient="records")
    supervisores = consultas.colaboradores(c, ("SUPERVISOR",))
    motivos = c.execute("SELECT codigo, descricao FROM dim_motivo WHERE processo = 'DIVERGENCIA' ORDER BY codigo").fetchall()
    if not supervisores:
        st.error("Nenhum colaborador com função SUPERVISOR cadastrado.")
        return
    with st.form("investigacao"):
        i = st.selectbox("Divergência", range(len(opcoes)), format_func=lambda i: (
            f"{opcoes[i]['numero_contagem']} · {opcoes[i]['endereco']} · {opcoes[i]['sku']} {opcoes[i]['lote']} "
            f"· diferença {opcoes[i]['diferenca']:+g}"))
        motivo = st.selectbox("Etapa de origem (motivo)", [m[0] for m in motivos],
                              format_func=lambda m: f"{m} — {dict(motivos)[m]}")
        matricula = st.selectbox("Supervisor", supervisores)
        enviar = st.form_submit_button("Registrar investigação", type="primary")
    if enviar:
        d = opcoes[i]
        linha = {"numero_contagem": d["numero_contagem"], "endereco": d["endereco"], "sku": d["sku"],
                 "lote": d["lote"], "motivo": motivo, "matricula": matricula}
        r = carga.registrar(c, "investigacao_divergencia", pd.DataFrame([linha]), usuario=usuario(),
                            fonte="FORMULARIO", nome_arquivo="formulario")
        mostrar_resultado(r)


def pagina_cargas():
    st.header("Cargas e integridade da entrada")
    c = con()
    hist = consultas.historico_cargas(c)
    st.subheader("Histórico de cargas (camada bruta)")
    st.dataframe(hist, hide_index=True, width="stretch")
    recusadas = hist[hist["status"] == "RECUSADA"]
    if not recusadas.empty:
        cid = st.selectbox("Ver erros da carga recusada", recusadas["carga_id"].tolist())
        st.dataframe(consultas.erros_da_carga(c, int(cid)), hide_index=True, width="stretch")

    st.subheader("Reconciliação saldo × movimentos (K04)")
    st.caption("Mede a integridade da CARGA contra o ERP — não mede acuracidade física (isso é a contagem).")
    st.dataframe(consultas.resumo_reconciliacao(c), hide_index=True, width="stretch")
    exc = consultas.excecoes_reconciliacao(c)
    if not exc.empty:
        st.dataframe(exc, hide_index=True, width="stretch")

    st.subheader("Membros inferidos (código usado antes de cadastrado)")
    inferidos = c.execute(
        "SELECT 'SKU' AS tipo, sku AS codigo FROM dim_sku WHERE inferido UNION ALL "
        "SELECT 'Endereço', endereco FROM dim_local WHERE inferido ORDER BY 1, 2").df()
    if inferidos.empty:
        st.write("Nenhum.")
    else:
        st.dataframe(inferidos, hide_index=True, width="stretch")

    st.divider()
    st.subheader("Cenário sintético (8 semanas)")
    st.caption("Planta + CD de lácteos simulada: todos os layouts gerados de um único estado, então os números fecham "
               "entre si. Valida a mecânica, não o parâmetro. Tudo entra marcado como sintético.")
    if st.button("Carregar cenário sintético", disabled=not usuario()):
        from dados_sinteticos import simulacao
        with st.spinner("Carregando 8 semanas e reconstruindo o modelo…"):
            res = simulacao.carregar(c, usuario())
        st.write(f"{sum(1 for _, r in res if r.status == 'ACEITA')} carga(s) aceita(s), "
                 f"{sum(1 for _, r in res if r.status == 'DUPLICADA')} duplicada(s) (já carregadas antes).")

    st.subheader("Apagar o histórico sintético")
    from app import admin
    n_cargas, n_linhas = admin.resumo_sinteticos(c)
    st.caption(f"Há {n_cargas} carga(s) sintética(s) ({n_linhas} linhas). Cargas reais nunca são apagadas; "
               "o expurgo fica registrado em bruto_expurgo.")
    frase = st.text_input(f"Para confirmar, digite {admin.FRASE_CONFIRMACAO}", key="frase_expurgo")
    if st.button("Apagar sintéticos", disabled=not (usuario() and n_cargas and frase == admin.FRASE_CONFIRMACAO)):
        apagadas = admin.limpar_sinteticos(c, usuario())
        st.success(f"Apagadas {apagadas[0]} carga(s) ({apagadas[1]} linhas). Modelo reconstruído.")


def pagina_painel():
    from app import painel
    painel.pagina_painel(con)


def pagina_layouts():
    st.header("Layouts canônicos de entrada")
    st.caption("Fonte: entrada/layouts.yaml. Cada layout deriva de uma tabela fato ou dimensão (Etapa 5).")
    for nome, spec in especificacao()["layouts"].items():
        situacao = "implementado" if spec.get("implementado") else "especificado (frentes 2/3)"
        with st.expander(f"{nome} — {spec['descricao']}  [{situacao}]"):
            st.write(f"Destino: `{spec['destino']}` · Canal: {', '.join(spec['canal'])} · Chave: {', '.join(spec['chave'])}")
            st.dataframe(_tabela_campos(spec), hide_index=True, width="stretch")
            for r in spec.get("regras", []):
                st.write(f"Regra: {r['msg']}")


def _tabela_campos(spec: dict) -> pd.DataFrame:
    linhas = []
    for nome, c in spec["campos"].items():
        restricao = []
        if "min" in c: restricao.append(f"≥ {c['min']}")
        if "max" in c: restricao.append(f"≤ {c['max']}")
        if "lista" in c: restricao.append(f"lista {c['lista']}")
        if "ref" in c: restricao.append(f"cadastro {c['ref']['cadastro']} ({c['ref'].get('ausente', 'rejeitar')})")
        if "max_len" in c: restricao.append(f"até {c['max_len']} caracteres")
        linhas.append({"campo": nome, "tipo": c["tipo"], "obrigatório": "sim" if c.get("obrigatorio") else "não",
                       "restrição": "; ".join(restricao)})
    return pd.DataFrame(linhas)
