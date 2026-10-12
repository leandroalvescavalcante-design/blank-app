"""Reconstrói dimensões e fatos (frente 1) a partir da camada bruta.

Reconstrução total e determinística: rodar duas vezes dá o mesmo resultado
(idempotência por construção). Chaves substitutas são derivadas de hash da
chave natural, portanto estáveis entre reconstruções.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

import duckdb
import pandas as pd

from app.config import ARQ_MODELO_SQL, ARQ_VISOES_SQL, CONFIABILIDADE, EMPRESA_PADRAO
from app.validacao import especificacao, layout

DESCONHECIDO, NAO_SE_APLICA = -1, -2
TIPOS_AJUSTE_BAIXA = {"AJUSTE_POSITIVO", "AJUSTE_NEGATIVO", "BAIXA"}


def sk(*partes) -> int:
    """Chave substituta estável: hash da chave natural (63 bits, positiva)."""
    return int(hashlib.md5("|".join(map(str, partes)).encode()).hexdigest()[:15], 16)


def _vazio_para_none(v):
    """Normaliza ausência: None, NaN (pandas 3 converte None em NaN em colunas de texto) e ''."""
    if v is None or (isinstance(v, str) and v == ""):
        return None
    try:
        return None if pd.isna(v) else v
    except (TypeError, ValueError):
        return v


# ----------------------------------------------------------------------------- leitura do bruto

def linhas_aceitas(con: duckdb.DuckDBPyConnection, nome_layout: str) -> pd.DataFrame:
    """Linhas NOVA/CORRECAO de cargas aceitas, tipadas conforme o layout, em ordem de chegada."""
    df = con.execute(
        """
        SELECT c.carga_id, c.empresa, c.fonte, c.sintetico, c.instante AS instante_carga,
               l.num_linha, l.payload, l.chave_negocio, l.hash_linha, l.status AS status_linha
        FROM bruto_linha l JOIN bruto_carga c USING (carga_id)
        WHERE c.layout = ? AND c.status = 'ACEITA' AND l.status IN ('NOVA', 'CORRECAO')
        ORDER BY c.carga_id, l.num_linha
        """,
        [nome_layout],
    ).df()
    campos = layout(nome_layout)["campos"]
    if df.empty:
        return pd.DataFrame(columns=["carga_id", "empresa", "fonte", "sintetico", "instante_carga", "num_linha",
                                     "chave_negocio", "hash_linha", "status_linha",
                                     *[c for c in campos if c != "empresa"]])
    dados = pd.DataFrame([json.loads(p) for p in df["payload"]], index=df.index)
    for nome, spec in campos.items():
        if nome not in dados:
            dados[nome] = None
        if spec["tipo"] == "data":
            dados[nome] = pd.to_datetime(dados[nome]).dt.date
        elif spec["tipo"] == "instante":
            dados[nome] = pd.to_datetime(dados[nome])
        elif spec["tipo"] == "texto":
            dados[nome] = dados[nome].astype(object).where(dados[nome].notna(), None)
    # o campo "empresa" de parametro_empresa coincide com a empresa da carga: vale a da carga
    return pd.concat([df.drop(columns=["payload"]), dados[[c for c in campos if c != "empresa"]]], axis=1)


def versoes_atuais(con, nome_layout: str) -> pd.DataFrame:
    df = linhas_aceitas(con, nome_layout)
    return df.drop_duplicates("chave_negocio", keep="last") if not df.empty else df


def cadastros(con) -> dict[str, dict[str, dict]]:
    """Estado atual dos cadastros: cadastro → {código: atributos}. Base das referências na validação."""
    refs = {}
    for nome, spec in especificacao()["layouts"].items():
        if not nome.startswith("cad_") or len(spec["chave"]) != 1 or nome == "cad_motivo":
            continue
        df = versoes_atuais(con, nome)
        refs[nome] = {r[spec["chave"][0]]: r for r in df.to_dict(orient="records")}
    motivos = {m["codigo"]: dict(m, origem="PADRAO") for m in especificacao()["motivos_padrao"]}
    for r in versoes_atuais(con, "cad_motivo").to_dict(orient="records"):
        motivos[r["codigo"]] = dict(r, origem="CADASTRO")
    refs["cad_motivo"] = motivos
    return refs


# ----------------------------------------------------------------------------- versionamento (estorno)

def versionar(df: pd.DataFrame, medidas: list[str]) -> pd.DataFrame:
    """Cada chave de negócio vira: NORMAL (1ª versão) e, a cada mudança, ESTORNO da anterior + CORRECAO.

    Soma das medidas por chave = última versão. Nada é sobrescrito (Etapa 3, regra 2).
    """
    if df.empty:
        return df.assign(tipo_registro=pd.Series(dtype=str), sinal=pd.Series(dtype=int))
    saida = []
    for _, grupo in df.groupby("chave_negocio", sort=False):
        anterior = None
        for registro in grupo.to_dict(orient="records"):
            if anterior is None:
                saida.append(dict(registro, tipo_registro="NORMAL", sinal=1))
            else:
                estorno = dict(anterior, tipo_registro="ESTORNO", sinal=-1,
                               carga_id=registro["carga_id"], num_linha=registro["num_linha"])
                for m in medidas:
                    estorno[m] = -estorno[m] if estorno[m] is not None else None
                saida.append(estorno)
                saida.append(dict(registro, tipo_registro="CORRECAO", sinal=1))
            anterior = registro
    return pd.DataFrame(saida)


# ----------------------------------------------------------------------------- reconstrução

def reconstruir(con: duckdb.DuckDBPyConnection, empresa: str = EMPRESA_PADRAO) -> None:
    spec = especificacao()
    refs = cadastros(con)
    mov = linhas_aceitas(con, "mov_estoque")
    saldo_todas = linhas_aceitas(con, "saldo_estoque")
    cont = linhas_aceitas(con, "contagem")
    inv = versoes_atuais(con, "investigacao_divergencia")
    lotes_cad = versoes_atuais(con, "cad_lote")
    unidades = versoes_atuais(con, "cad_sku_unidade")

    # Fotografia: a carga mais recente de cada site × dia substitui as anteriores por inteiro.
    if not saldo_todas.empty:
        ultima = saldo_todas.groupby(["site", "data_saldo"])["carga_id"].transform("max")
        saldo = saldo_todas[saldo_todas["carga_id"] == ultima].copy()
    else:
        saldo = saldo_todas

    tabelas: dict[str, pd.DataFrame] = {}

    # --- dim_procedencia
    tabelas["dim_procedencia"] = pd.DataFrame(
        [{"procedencia_sk": sk("proc", f), "fonte": f, "confiabilidade": c} for f, c in CONFIABILIDADE.items()])

    # --- dim_site
    tabelas["dim_site"] = pd.DataFrame(
        [{"site_sk": sk(empresa, "site", s), "empresa": empresa, "site": s,
          "descricao": r["descricao"], "horario_corte": r["horario_corte"]} for s, r in refs["cad_site"].items()],
        columns=["site_sk", "empresa", "site", "descricao", "horario_corte"])

    # --- dim_local (+ inferidos; site do inferido vem do saldo, quando houver)
    locais = [{"local_sk": sk(empresa, "local", e), "empresa": empresa, "endereco": e, "site": r["site"],
               "zona": r["zona"], "tipo": r["tipo"], "classe_temperatura": r["classe_temperatura"], "inferido": False}
              for e, r in refs["cad_local"].items()]
    site_por_endereco = dict(zip(saldo_todas.get("endereco", []), saldo_todas.get("site", [])))
    usados = set(mov.get("endereco", [])) | set(saldo_todas.get("endereco", [])) | set(cont.get("endereco", []))
    for e in sorted(usados - set(refs["cad_local"])):
        locais.append({"local_sk": sk(empresa, "local", e), "empresa": empresa, "endereco": e,
                       "site": site_por_endereco.get(e, "-1"), "zona": None, "tipo": None,
                       "classe_temperatura": None, "inferido": True})
    tabelas["dim_local"] = _com_especiais(pd.DataFrame(locais), "local_sk", "endereco")

    # --- dim_sku (+ inferidos)
    skus = [{"sku_sk": sk(empresa, "sku", s), "empresa": empresa, "sku": s, "descricao": r["descricao"],
             "tipo": r["tipo"], "familia": r["familia"], "unidade_base": r["unidade_base"],
             "controla_lote": r["controla_lote"], "shelf_life_dias": r["shelf_life_dias"],
             "validade_minima_padrao_dias": r["validade_minima_padrao_dias"],
             "classe_temperatura": r["classe_temperatura"], "peso_bruto_kg_un_base": r["peso_bruto_kg_un_base"],
             "volume_m3_un_base": r["volume_m3_un_base"], "codigo_barras": r["codigo_barras"], "inferido": False}
            for s, r in refs["cad_sku"].items()]
    usados = set(mov.get("sku", [])) | set(saldo_todas.get("sku", [])) | set(cont.get("sku", []))
    for s in sorted(usados - set(refs["cad_sku"])):
        skus.append({"sku_sk": sk(empresa, "sku", s), "empresa": empresa, "sku": s, "inferido": True})
    tabelas["dim_sku"] = _com_especiais(pd.DataFrame(skus), "sku_sk", "sku")

    # --- sku_unidade
    tabelas["sku_unidade"] = pd.DataFrame(
        [{"sku_sk": sk(empresa, "sku", r["sku"]), "unidade": r["unidade"], "fator_para_base": r["fator_para_base"],
          "e_unidade_palete": r["e_unidade_palete"]} for r in unidades.to_dict(orient="records")],
        columns=["sku_sk", "unidade", "fator_para_base", "e_unidade_palete"])

    # --- dim_lote: cadastro tem precedência; senão, a validade mais recente informada em saldo/movimento
    lotes: dict[tuple, dict] = {}
    for origem_df, origem in ((mov, "MOVIMENTO"), (saldo_todas, "SALDO")):
        for r in origem_df.to_dict(orient="records"):
            if _vazio_para_none(r.get("lote")) is None:
                continue
            k = (r["sku"], r["lote"])
            atual = lotes.get(k, {"data_fabricacao": None, "data_validade": None, "origem_validade": None})
            if r.get("data_validade") is not None and not pd.isna(r["data_validade"]):
                atual.update(data_validade=r["data_validade"], origem_validade=origem)
            lotes[k] = atual
    for r in lotes_cad.to_dict(orient="records"):
        lotes[(r["sku"], r["lote"])] = {"data_fabricacao": r["data_fabricacao"], "data_validade": r["data_validade"],
                                        "origem_validade": "CADASTRO"}
    for r in cont.to_dict(orient="records"):
        if _vazio_para_none(r.get("lote")) is not None:
            lotes.setdefault((r["sku"], r["lote"]), {"data_fabricacao": None, "data_validade": None,
                                                     "origem_validade": None})
    tabelas["dim_lote"] = _com_especiais(pd.DataFrame(
        [{"lote_sk": sk(empresa, "lote", s, l), "empresa": empresa, "sku_sk": sk(empresa, "sku", s), "sku": s,
          "lote": l, **v} for (s, l), v in lotes.items()],
        columns=["lote_sk", "empresa", "sku_sk", "sku", "lote", "data_fabricacao", "data_validade",
                 "origem_validade"]), "lote_sk", "lote")

    # --- dim_motivo
    tabelas["dim_motivo"] = _com_especiais(pd.DataFrame(
        [{"motivo_sk": sk(empresa, "motivo", c), "empresa": empresa, "codigo": c, "descricao": m["descricao"],
          "processo": m["processo"], "etapa_origem": m["etapa_origem"], "gera_baixa": m["gera_baixa"],
          "categoria_perda": m["categoria_perda"], "controlavel": m["controlavel"], "origem": m["origem"]}
         for c, m in refs["cad_motivo"].items()]), "motivo_sk", "codigo")

    # --- dim_colaborador (sem nome/CPF — LGPD)
    tabelas["dim_colaborador"] = _com_especiais(pd.DataFrame(
        [{"colaborador_sk": sk(empresa, "colab", m), "empresa": empresa, "matricula": m, "funcao": r["funcao"],
          "turno": r["turno"], "site": r["site"]} for m, r in refs["cad_colaborador"].items()],
        columns=["colaborador_sk", "empresa", "matricula", "funcao", "turno", "site"]), "colaborador_sk", "matricula")

    # --- dim_tipo_movimento
    tabelas["dim_tipo_movimento"] = pd.DataFrame(
        [{"tipo_movimento_sk": sk("tipo_mov", c), "codigo": c, "sinal_esperado": v["sinal"],
          "afeta_disponivel": v["afeta_disponivel"]} for c, v in spec["tipos_movimento"].items()])

    lote_sk = lambda s, l: NAO_SE_APLICA if _vazio_para_none(l) is None else sk(empresa, "lote", s, l)  # noqa: E731
    proc_sk = lambda f: sk("proc", f)  # noqa: E731

    # --- aux_investigacao
    tabelas["aux_investigacao"] = pd.DataFrame(
        [{"numero_contagem": r["numero_contagem"], "endereco": r["endereco"], "sku": r["sku"],
          "lote": _vazio_para_none(r["lote"]) or "", "motivo": r["motivo"], "matricula": r["matricula"],
          "instante": r["instante_carga"]} for r in inv.to_dict(orient="records")],
        columns=["numero_contagem", "endereco", "sku", "lote", "motivo", "matricula", "instante"])
    motivo_inv = {(r["numero_contagem"], r["endereco"], r["sku"], r["lote"]): r["motivo"]
                  for r in tabelas["aux_investigacao"].to_dict(orient="records")}

    # --- F02 fato_movimento_estoque (razão)
    f02 = versionar(mov, ["qtd"])
    linhas = []
    for r in f02.to_dict(orient="records"):
        motivo = _vazio_para_none(r["motivo"])
        if r["tipo_movimento"] in ("AJUSTE_POSITIVO", "AJUSTE_NEGATIVO") and r["documento_tipo"] == "CONTAGEM":
            motivo = motivo_inv.get((r["documento_numero"], r["endereco"], r["sku"],
                                     _vazio_para_none(r["lote"]) or ""), motivo)
        if motivo is None and r["tipo_movimento"] in TIPOS_AJUSTE_BAIXA:
            motivo = "DESCONHECIDO"
        linhas.append({
            "empresa": r["empresa"], "procedencia_sk": proc_sk(r["fonte"]), "carga_id": r["carga_id"],
            "bruto_num_linha": r["num_linha"], "chave_negocio": r["chave_negocio"], "hash_linha": r["hash_linha"],
            "tipo_registro": r["tipo_registro"], "sinal": r["sinal"], "sintetico": bool(r["sintetico"]),
            "data_movimento": r["data_movimento"], "data_sk": _data_sk(r["data_movimento"]),
            "instante_lancamento": r["instante_lancamento"],
            "retroativo": r["instante_lancamento"].date() > r["data_movimento"],
            "sku_sk": sk(empresa, "sku", r["sku"]), "lote_sk": lote_sk(r["sku"], r["lote"]),
            "local_sk": sk(empresa, "local", r["endereco"]),
            "tipo_movimento_sk": sk("tipo_mov", r["tipo_movimento"]),
            "motivo_sk": sk(empresa, "motivo", motivo) if motivo else NAO_SE_APLICA,
            "documento_tipo": r["documento_tipo"], "documento_numero": r["documento_numero"],
            "item": r["item"], "sequencia": r["sequencia"],
            "qtd": r["qtd"], "custo_unit": r["custo_unit"], "valor": r["qtd"] * r["custo_unit"]})
    tabelas["fato_movimento_estoque"] = pd.DataFrame(linhas, columns=list(_COLS_F02))

    # --- F03 fato_saldo_diario (esparso: saldo zero não vira linha) + cobertura
    tabelas["fato_saldo_diario"] = pd.DataFrame([{
        "empresa": r["empresa"], "procedencia_sk": proc_sk(r["fonte"]), "carga_id": r["carga_id"],
        "bruto_num_linha": r["num_linha"], "chave_negocio": r["chave_negocio"], "sintetico": bool(r["sintetico"]),
        "data_saldo": r["data_saldo"], "data_sk": _data_sk(r["data_saldo"]), "instante_extracao": r["instante_extracao"],
        "sku_sk": sk(empresa, "sku", r["sku"]), "lote_sk": lote_sk(r["sku"], r["lote"]),
        "local_sk": sk(empresa, "local", r["endereco"]), "qtd_fisica": r["qtd_fisica"],
        "qtd_bloqueada": r["qtd_bloqueada"], "qtd_reservada": r["qtd_reservada"],
        "custo_unit_medio": r["custo_unit_medio"], "valor": r["qtd_fisica"] * r["custo_unit_medio"]}
        for r in saldo.to_dict(orient="records") if r["qtd_fisica"] > 0], columns=list(_COLS_F03))
    if not saldo.empty:
        cob = (saldo.groupby(["site", "data_saldo"])
               .agg(instante_extracao=("instante_extracao", "max"), carga_id=("carga_id", "max"),
                    sintetico=("sintetico", "max")).reset_index())
        versoes = saldo_todas.groupby(["site", "data_saldo"])["carga_id"].nunique().rename("versoes").reset_index()
        cob = cob.merge(versoes, on=["site", "data_saldo"])
    else:
        cob = pd.DataFrame(columns=["site", "data_saldo", "instante_extracao", "carga_id", "sintetico", "versoes"])
    tabelas["cobertura_saldo"] = cob

    # --- F04 fato_contagem (recontagem final derivada, nunca digitada)
    f04 = versionar(cont, ["qtd_contada", "qtd_sistema_congelada"])
    if not f04.empty:
        atuais = cont.drop_duplicates("chave_negocio", keep="last").copy()
        atuais["lote_n"] = atuais["lote"].map(lambda x: _vazio_para_none(x) or "")
        maxima = atuais.groupby(["numero_contagem", "endereco", "sku", "lote_n"])["numero_recontagem"].transform("max")
        finais = set(atuais.loc[atuais["numero_recontagem"] == maxima, "chave_negocio"])
    else:
        finais = set()
    tabelas["fato_contagem"] = pd.DataFrame([{
        "empresa": r["empresa"], "procedencia_sk": proc_sk(r["fonte"]), "carga_id": r["carga_id"],
        "bruto_num_linha": r["num_linha"], "chave_negocio": r["chave_negocio"], "hash_linha": r["hash_linha"],
        "tipo_registro": r["tipo_registro"], "sinal": r["sinal"], "sintetico": bool(r["sintetico"]),
        "numero_contagem": r["numero_contagem"], "numero_recontagem": r["numero_recontagem"],
        "e_final": r["chave_negocio"] in finais, "data_sk": _data_sk(r["instante_contagem"].date()),
        "instante_contagem": r["instante_contagem"], "instante_congelamento": r["instante_congelamento"],
        "sku_sk": sk(empresa, "sku", r["sku"]), "lote_sk": lote_sk(r["sku"], r["lote"]),
        "local_sk": sk(empresa, "local", r["endereco"]),
        "colaborador_sk": sk(empresa, "colab", r["matricula"]),
        "qtd_contada": r["qtd_contada"], "qtd_sistema_congelada": r["qtd_sistema_congelada"]}
        for r in f04.to_dict(orient="records")], columns=list(_COLS_F04))

    # --- frentes 2 e 3 (dimensões e fatos) e calendário operacional
    from app import planejamento, transform_f23
    for nome, df in transform_f23.construir(con, empresa, refs).items():
        especiais = {"dim_cliente": ("cliente_sk", "cliente"), "dim_parceiro": ("parceiro_sk", "cnpj"),
                     "dim_veiculo": ("veiculo_sk", "placa"), "dim_recurso": ("recurso_sk", "recurso"),
                     "dim_turno": ("turno_sk", "turno")}
        tabelas[nome] = _com_especiais(df, *especiais[nome]) if nome in especiais else df

    # --- dim_data (intervalo coberto pelos fatos)
    datas = [d for d in list(mov.get("data_movimento", [])) + list(saldo_todas.get("data_saldo", []))
             + [i.date() for i in cont.get("instante_contagem", [])]
             + list(tabelas["fato_evento_pedido_venda"].get("data_desejada", []))
             + list(tabelas["fato_evento_pedido_venda"].get("data_evento", [])) if d is not None and not pd.isna(d)]
    tabelas["dim_data"] = _dim_data(min(datas, default=date.today()), max(datas, default=date.today()))
    sites = list(tabelas["dim_site"]["site"]) if not tabelas["dim_site"].empty else []
    tabelas["dim_calendario_operacional"] = pd.DataFrame(
        [{"site": st, "data": d, "dia_util": d.weekday() != 6} for st in sites for d in tabelas["dim_data"]["data"]],
        columns=["site", "data", "dia_util"])

    # --- F12 / F12b planejamento (derivados; usam os fatos acima)
    tabelas.update(planejamento.construir(tabelas, empresa))

    con.execute("BEGIN")
    try:
        con.execute(ARQ_MODELO_SQL.read_text(encoding="utf-8"))
        for nome, df in tabelas.items():
            if df.empty:
                continue
            con.register("_tmp", df)
            con.execute(f"INSERT INTO {nome} BY NAME SELECT * FROM _tmp")
            con.unregister("_tmp")
        con.execute(_SQL_VISOES)
        con.execute(ARQ_VISOES_SQL.read_text(encoding="utf-8"))
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


# ----------------------------------------------------------------------------- auxiliares

_COLS_F02 = ("empresa", "procedencia_sk", "carga_id", "bruto_num_linha", "chave_negocio", "hash_linha",
             "tipo_registro", "sinal", "sintetico", "data_movimento", "data_sk", "instante_lancamento", "retroativo",
             "sku_sk", "lote_sk", "local_sk", "tipo_movimento_sk", "motivo_sk", "documento_tipo",
             "documento_numero", "item", "sequencia", "qtd", "custo_unit", "valor")
_COLS_F03 = ("empresa", "procedencia_sk", "carga_id", "bruto_num_linha", "chave_negocio", "sintetico", "data_saldo",
             "data_sk", "instante_extracao", "sku_sk", "lote_sk", "local_sk", "qtd_fisica", "qtd_bloqueada",
             "qtd_reservada", "custo_unit_medio", "valor")
_COLS_F04 = ("empresa", "procedencia_sk", "carga_id", "bruto_num_linha", "chave_negocio", "hash_linha",
             "tipo_registro", "sinal", "sintetico", "numero_contagem", "numero_recontagem", "e_final", "data_sk",
             "instante_contagem", "instante_congelamento", "sku_sk", "lote_sk", "local_sk", "colaborador_sk",
             "qtd_contada", "qtd_sistema_congelada")


def _data_sk(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def _dim_data(inicio: date, fim: date) -> pd.DataFrame:
    dias = pd.date_range(inicio - pd.Timedelta(days=1), fim, freq="D")
    iso = dias.isocalendar()
    return pd.DataFrame({
        "data_sk": dias.year * 10000 + dias.month * 100 + dias.day,
        "data": dias.date, "ano": dias.year, "mes": dias.month, "dia": dias.day, "trimestre": dias.quarter,
        "dia_semana_iso": dias.dayofweek + 1, "semana_iso": iso["week"].to_numpy(), "ano_iso": iso["year"].to_numpy(),
    })


def _com_especiais(df: pd.DataFrame, col_sk: str, col_rotulo: str) -> pd.DataFrame:
    """Acrescenta os membros -1 (desconhecido) e -2 (não se aplica): fato nunca tem chave nula."""
    especiais = pd.DataFrame([{col_sk: DESCONHECIDO, col_rotulo: "(desconhecido)"},
                              {col_sk: NAO_SE_APLICA, col_rotulo: "(não se aplica)"}])
    return pd.concat([especiais, df], ignore_index=True) if not df.empty else especiais


# Reconciliação (K04) no grão SKU × lote × endereço, por site e dia com fotografia no dia e na véspera.
# Variação esperada entre as duas fotografias = movimentos datados no dia e lançados até a extração do dia
# + movimentos retroativos (datados antes) lançados entre a extração da véspera e a do dia.
_SQL_VISOES = """
CREATE OR REPLACE VIEW v_reconciliacao AS
WITH cob AS (
    SELECT c.site, c.data_saldo AS d, c.instante_extracao AS ext, p.instante_extracao AS ext_ant
    FROM cobertura_saldo c
    JOIN cobertura_saldo p ON p.site = c.site AND p.data_saldo = c.data_saldo - 1
),
saldo AS (
    SELECT l.site, s.data_saldo AS d, s.sku_sk, s.lote_sk, s.local_sk, sum(s.qtd_fisica) AS q
    FROM fato_saldo_diario s JOIN dim_local l USING (local_sk)
    GROUP BY ALL
),
mov AS (
    SELECT cob.site, cob.d, m.sku_sk, m.lote_sk, m.local_sk, sum(m.qtd) AS q
    FROM fato_movimento_estoque m
    JOIN dim_local l USING (local_sk)
    JOIN cob ON cob.site = l.site
    WHERE (m.data_movimento = cob.d AND m.instante_lancamento <= cob.ext)
       OR (m.data_movimento < cob.d AND m.instante_lancamento > cob.ext_ant AND m.instante_lancamento <= cob.ext)
    GROUP BY ALL
),
chaves AS (
    SELECT s.site, s.d, s.sku_sk, s.lote_sk, s.local_sk FROM saldo s JOIN cob ON cob.site = s.site AND cob.d = s.d
    UNION
    SELECT cob.site, cob.d, s.sku_sk, s.lote_sk, s.local_sk FROM saldo s JOIN cob ON cob.site = s.site AND s.d = cob.d - 1
    UNION
    SELECT site, d, sku_sk, lote_sk, local_sk FROM mov
)
SELECT k.site, k.d AS data_saldo, k.sku_sk, k.lote_sk, k.local_sk,
       coalesce(s0.q, 0) AS saldo_vespera,
       coalesce(m.q, 0)  AS movimentos,
       coalesce(s1.q, 0) AS saldo_dia,
       coalesce(s1.q, 0) - coalesce(s0.q, 0) - coalesce(m.q, 0) AS dif_reconciliacao
FROM chaves k
LEFT JOIN saldo s1 ON s1.site = k.site AND s1.d = k.d     AND s1.sku_sk = k.sku_sk AND s1.lote_sk = k.lote_sk AND s1.local_sk = k.local_sk
LEFT JOIN saldo s0 ON s0.site = k.site AND s0.d = k.d - 1 AND s0.sku_sk = k.sku_sk AND s0.lote_sk = k.lote_sk AND s0.local_sk = k.local_sk
LEFT JOIN mov   m  ON m.site  = k.site AND m.d  = k.d     AND m.sku_sk  = k.sku_sk AND m.lote_sk  = k.lote_sk AND m.local_sk  = k.local_sk;

CREATE OR REPLACE VIEW v_divergencias_pendentes AS
WITH atual AS (
    SELECT numero_contagem, sku_sk, lote_sk, local_sk, chave_negocio,
           sum(sinal * qtd_contada) AS qtd_contada_liq, max(qtd_contada) FILTER (WHERE tipo_registro != 'ESTORNO') AS qtd_contada,
           max(qtd_sistema_congelada) FILTER (WHERE tipo_registro != 'ESTORNO') AS qtd_sistema,
           max(instante_contagem) AS instante_contagem, bool_or(e_final) AS e_final
    FROM fato_contagem GROUP BY ALL
)
SELECT a.numero_contagem, l.endereco, s.sku, coalesce(lt.lote, '') AS lote, a.qtd_contada, a.qtd_sistema,
       a.qtd_contada - a.qtd_sistema AS diferenca, a.instante_contagem
FROM atual a
JOIN dim_local l USING (local_sk)
JOIN dim_sku s USING (sku_sk)
LEFT JOIN dim_lote lt ON lt.lote_sk = a.lote_sk AND a.lote_sk > 0
WHERE a.e_final AND abs(a.qtd_contada - a.qtd_sistema) > 1e-9
  AND NOT EXISTS (SELECT 1 FROM aux_investigacao i
                  WHERE i.numero_contagem = a.numero_contagem AND i.endereco = l.endereco
                    AND i.sku = s.sku AND i.lote = coalesce(lt.lote, ''));
"""
