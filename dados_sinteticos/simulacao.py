"""Simulação SINTÉTICA integrada de uma planta + CD de lácteos (arquétipo A), 8 semanas.

Serve para validar a MECÂNICA da ferramenta inteira: todos os layouts são gerados a partir de um único
estado simulado, então os números fecham entre si (pedido → separação → NF → entrega → movimento → saldo).
Não valida PARÂMETRO: demanda, lead time, custos e taxas de erro são inventados.

Imperfeições injetadas de propósito (a ferramenta precisa detectá-las):
- erros físicos de estoque (perda e troca de endereço) que só a contagem cíclica revela;
- lançamentos retroativos (apontamento de consumo lançado no dia seguinte);
- 2 movimentos que "não vieram" no extrato (exceções de reconciliação esperadas);
- entregas fora da janela, cliente fechado, recebimento com recusa, cortes por falta de saldo/validade.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

import numpy as np
import pandas as pd

INICIO = date(2026, 8, 3)          # segunda-feira
DIAS = 56
SEMENTE = 20260803
SITE = "CD01"
CNPJ_EMPRESA = "44444444000135"
DIAS_OMITIDOS = (INICIO + timedelta(days=17), INICIO + timedelta(days=38))   # movimento fora do extrato

PA = {  # sku: família, shelf life, validade mínima padrão, peso, volume, custo, un/cx, cx/palete, recurso, min/un, consumo de leite
    "IOG-170": dict(familia="IOGURTE", shelf=35, vmin=10, peso=0.18, vol=0.00025, custo=1.10, cx=24, pl=100,
                    recurso="LINHA-1", min_un=0.02, leite=0.15, pote=1),
    "BEB-1L": dict(familia="BEBIDA", shelf=45, vmin=15, peso=1.05, vol=0.0011, custo=2.40, cx=12, pl=100,
                   recurso="LINHA-1", min_un=0.04, leite=0.90, pote=0),
    "QJ-500": dict(familia="QUEIJO", shelf=60, vmin=20, peso=0.52, vol=0.0006, custo=9.50, cx=12, pl=80,
                   recurso="PRENSA-1", min_un=0.50, leite=5.0, pote=0),
}
MP = {
    "LEITE-L": dict(familia="LEITE", unidade="L", lote=True, shelf=5, peso=1.03, vol=0.001, custo=2.10, temp="REFRIGERADO"),
    "EMB-POTE": dict(familia="EMB", unidade="UN", lote=False, shelf=None, peso=0.005, vol=0.00005, custo=0.06, temp="SECO"),
    "CX-PAP": dict(familia="EMB", unidade="UN", lote=False, shelf=None, peso=0.30, vol=0.002, custo=0.80, temp="SECO"),
}
CUSTO = {**{k: v["custo"] for k, v in PA.items()}, **{k: v["custo"] for k, v in MP.items()}}
CLIENTES = {  # código: município, lat, long, janela, prioridade, validade mínima (None = usa a do SKU), média de caixas por SKU
    "C01": ("João Pessoa", -7.12, -34.86, ("07:00", "12:00"), 1, 15, {"IOG-170": 10, "BEB-1L": 6, "QJ-500": 3}),
    "C02": ("Cabedelo", -6.98, -34.83, ("08:00", "14:00"), 2, None, {"IOG-170": 6, "BEB-1L": 4, "QJ-500": 1}),
    "C03": ("Bayeux", -7.13, -34.93, ("07:00", "11:00"), 2, 20, {"IOG-170": 8, "BEB-1L": 3, "QJ-500": 0.4}),
    "C04": ("Santa Rita", -7.11, -34.98, ("08:00", "16:00"), 3, None, {"IOG-170": 5, "BEB-1L": 5, "QJ-500": 2}),
    "C05": ("Campina Grande", -7.23, -35.88, ("09:00", "17:00"), 1, None, {"IOG-170": 12, "BEB-1L": 8, "QJ-500": 4}),
    "C06": ("Conde", -7.26, -34.91, ("07:00", "13:00"), 3, None, {"IOG-170": 3, "BEB-1L": 2, "QJ-500": 0.3}),
}
ACORDO = {("C05", "QJ-500"): 30}
FORNECEDOR_LEITE, FORNECEDOR_EMB, TRANSPORTADORA = "11111111000191", "22222222000172", "33333333000153"
VEICULOS = {"QAA1A11": dict(tipo="VUC", kg=1200, m3=6, propria="S", fixo=300, por_parada=60),
            "QBB2B22": dict(tipo="TOCO", kg=3500, m3=16, propria="N", fixo=650, por_parada=40)}
PICKING = ["A-01-01", "A-01-02", "A-01-03", "A-01-04", "A-01-05"]
END_LEITE, END_POTE, END_CX, END_QUAR = "A-01-06", "B-01-01", "B-01-02", "Q-01"


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".")
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return str(v)


def _df(linhas: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{k: _s(v) for k, v in l.items()} for l in linhas])


def _dt(d: date, hhmm: str, minutos: int = 0) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m)) + timedelta(minutes=minutos)


def _util(d: date) -> bool:
    return d.weekday() != 6  # domingo sem expedição


def _proximo_util(d: date, n: int = 1) -> date:
    while n:
        d += timedelta(days=1)
        if _util(d):
            n -= 1
    return d


def chave_nf(numero: int, d: date) -> str:
    corpo = f"25{d:%y%m}{CNPJ_EMPRESA}55001{numero:09d}1{numero % 10**8:08d}"
    dv = sum(int(c) * (2 + i % 8) for i, c in enumerate(reversed(corpo))) % 11
    return corpo + str(0 if dv < 2 else 11 - dv)


@dataclass
class Estado:
    sistema: dict = field(default_factory=lambda: defaultdict(float))   # (sku, lote, endereço) → qtd no ERP
    fisico: dict = field(default_factory=lambda: defaultdict(float))    # o que existe de fato
    validade: dict = field(default_factory=dict)                         # (sku, lote) → data
    causas: dict = field(default_factory=lambda: defaultdict(list))      # posição → causas ocultas de erro
    razao: list = field(default_factory=list)


class Simulacao:
    def __init__(self, semente: int = SEMENTE):
        self.rng = np.random.default_rng(semente)
        self.e = Estado()
        self.out: dict[str, list] = defaultdict(list)
        self.saldos: list[tuple[date, pd.DataFrame]] = []
        self.n_doc = defaultdict(int)
        self.pedidos_abertos: list[dict] = []
        self.pcs_abertos: list[dict] = []
        self.reentregas: list[dict] = []
        self.omitir: set = set()
        self.seq = defaultdict(int)

    # ------------------------------------------------------------------ utilidades
    def doc(self, prefixo: str) -> int:
        self.n_doc[prefixo] += 1
        return self.n_doc[prefixo]

    def mover(self, tipo, sku, lote, end, qtd, d, lanc, doc_tipo, doc_num, item=1, motivo=None, fisico=True):
        chave = (doc_tipo, doc_num, item, tipo)
        self.seq[chave] += 1
        seq = self.seq[chave]
        self.e.razao.append(dict(documento_tipo=doc_tipo, documento_numero=doc_num, item=item, sequencia=seq,
                                 tipo_movimento=tipo, sku=sku, lote=lote or "",
                                 data_validade=self.e.validade.get((sku, lote)) if lote else None,
                                 endereco=end, qtd=float(qtd), custo_unit=CUSTO[sku], data_movimento=d,
                                 instante_lancamento=lanc, motivo=motivo))
        k = (sku, lote or "", end)
        self.e.sistema[k] += qtd
        if fisico:
            self.e.fisico[k] += qtd

    def estoque_sku(self, sku, enderecos=None, sistema=True):
        base = self.e.sistema if sistema else self.e.fisico
        return sum(q for (s, _, e), q in base.items() if s == sku and q > 1e-9 and (enderecos is None or e in enderecos))

    def lotes_fefo(self, sku, enderecos, validade_min: date | None = None):
        itens = [((s, l, e), q) for (s, l, e), q in self.e.sistema.items()
                 if s == sku and e in enderecos and q > 1e-9]
        if validade_min:
            itens = [i for i in itens if not i[0][1] or self.e.validade[(sku, i[0][1])] >= validade_min]
        return sorted(itens, key=lambda i: (self.e.validade.get((sku, i[0][1]), date.max), i[0][2]))

    def consumir(self, sku, end, qtd, d, lanc, doc):
        """Consumo FEFO de MP; retorna quanto conseguiu consumir."""
        restante = qtd
        for (s, l, e), q in self.lotes_fefo(sku, [end]):
            usar = min(q, restante)
            self.mover("SAIDA_CONSUMO", sku, l, e, -usar, d, lanc, "OP", doc)
            restante -= usar
            if restante <= 1e-9:
                break
        return qtd - restante

    # ------------------------------------------------------------------ cadastros
    def cadastros(self) -> dict[str, pd.DataFrame]:
        c = {}
        c["cad_site"] = _df([dict(site=SITE, descricao="Planta + CD de lácteos (sintético)", horario_corte="00:00")])
        locais = [dict(endereco=e, site=SITE, zona="A", tipo="PICKING", classe_temperatura="REFRIGERADO") for e in PICKING]
        locais += [dict(endereco=END_LEITE, site=SITE, zona="A", tipo="PULMAO", classe_temperatura="REFRIGERADO"),
                   dict(endereco=END_POTE, site=SITE, zona="B", tipo="PULMAO", classe_temperatura="SECO"),
                   dict(endereco=END_CX, site=SITE, zona="B", tipo="PULMAO", classe_temperatura="SECO"),
                   dict(endereco=END_QUAR, site=SITE, zona="Q", tipo="QUARENTENA", classe_temperatura="REFRIGERADO"),
                   dict(endereco="DOCA-01", site=SITE, zona="D", tipo="DOCA", classe_temperatura="REFRIGERADO")]
        c["cad_local"] = _df(locais)
        skus = [dict(sku=s, descricao=f"{p['familia'].title()} (sintético)", tipo="PA", familia=p["familia"],
                     unidade_base="UN", controla_lote="S", shelf_life_dias=p["shelf"],
                     validade_minima_padrao_dias=p["vmin"], classe_temperatura="REFRIGERADO",
                     peso_bruto_kg_un_base=p["peso"], volume_m3_un_base=p["vol"], codigo_barras=f"789000000{i:04d}")
                for i, (s, p) in enumerate(PA.items(), start=1)]
        skus += [dict(sku=s, descricao=f"{s} (sintético)", tipo="MP" if s == "LEITE-L" else "EMBALAGEM",
                      familia=m["familia"], unidade_base=m["unidade"], controla_lote="S" if m["lote"] else "N",
                      shelf_life_dias=m["shelf"], validade_minima_padrao_dias=1 if m["shelf"] else None,
                      classe_temperatura=m["temp"], peso_bruto_kg_un_base=m["peso"], volume_m3_un_base=m["vol"],
                      codigo_barras=None) for s, m in MP.items()]
        c["cad_sku"] = _df(skus)
        un = []
        for s, p in PA.items():
            un += [dict(sku=s, unidade="CX", fator_para_base=p["cx"], e_unidade_palete="N"),
                   dict(sku=s, unidade="PL", fator_para_base=p["cx"] * p["pl"], e_unidade_palete="S")]
        un += [dict(sku="LEITE-L", unidade="PL", fator_para_base=1000, e_unidade_palete="S"),
               dict(sku="EMB-POTE", unidade="CX", fator_para_base=1000, e_unidade_palete="N"),
               dict(sku="EMB-POTE", unidade="PL", fator_para_base=50000, e_unidade_palete="S"),
               dict(sku="CX-PAP", unidade="FD", fator_para_base=25, e_unidade_palete="N"),
               dict(sku="CX-PAP", unidade="PL", fator_para_base=1000, e_unidade_palete="S")]
        c["cad_sku_unidade"] = _df(un)
        c["cad_colaborador"] = _df([
            dict(matricula="M001", funcao="INVENTARIANTE", turno="T1", site=SITE),
            dict(matricula="M002", funcao="SUPERVISOR", turno="T1", site=SITE),
            dict(matricula="M003", funcao="CONFERENTE", turno="T1", site=SITE),
            dict(matricula="M004", funcao="SEPARADOR", turno="T1", site=SITE),
            dict(matricula="M005", funcao="SEPARADOR", turno="T1", site=SITE),
            dict(matricula="M006", funcao="OPERADOR", turno="T1", site=SITE),
            dict(matricula="M007", funcao="OPERADOR", turno="T2", site=SITE),
            dict(matricula="M010", funcao="MOTORISTA", turno="T1", site=SITE),
            dict(matricula="M011", funcao="MOTORISTA", turno="T1", site=SITE)])
        c["cad_cliente"] = _df([dict(cliente=k, nome=f"Cliente {k} (sintético)", municipio=v[0], uf="PB",
                                     latitude=v[1], longitude=v[2], janela_inicio=v[3][0], janela_fim=v[3][1],
                                     prioridade=v[4], validade_minima_dias=v[5]) for k, v in CLIENTES.items()])
        c["cad_parceiro"] = _df([
            dict(cnpj=FORNECEDOR_LEITE, razao_social="Fornecedor de leite (sintético)", e_fornecedor="S", e_transportadora="N"),
            dict(cnpj=FORNECEDOR_EMB, razao_social="Fornecedor de embalagens (sintético)", e_fornecedor="S", e_transportadora="N"),
            dict(cnpj=TRANSPORTADORA, razao_social="Transportadora (sintética)", e_fornecedor="N", e_transportadora="S")])
        c["cad_parceiro_sku"] = _df([
            dict(cnpj=FORNECEDOR_LEITE, sku="LEITE-L", lote_minimo=4000, multiplo_compra=1000, lead_time_contratado_dias=1),
            dict(cnpj=FORNECEDOR_EMB, sku="EMB-POTE", lote_minimo=20000, multiplo_compra=1000, lead_time_contratado_dias=7),
            dict(cnpj=FORNECEDOR_EMB, sku="CX-PAP", lote_minimo=1000, multiplo_compra=25, lead_time_contratado_dias=7)])
        c["cad_veiculo"] = _df([dict(placa=p, tipo=v["tipo"], cap_kg=v["kg"], cap_m3=v["m3"], classe_temperatura="REFRIGERADO",
                                     propria=v["propria"], transportadora_cnpj=None if v["propria"] == "S" else TRANSPORTADORA)
                                for p, v in VEICULOS.items()])
        c["cad_recurso"] = _df([
            dict(recurso="LINHA-1", descricao="Linha de envase (sintética)", site=SITE, tipo="LINHA", e_restritivo="S"),
            dict(recurso="PRENSA-1", descricao="Prensa de queijo (sintética)", site=SITE, tipo="MAQUINA", e_restritivo="N")])
        c["cad_turno"] = _df([dict(turno="T1", site=SITE, inicio="06:00", fim="14:00", horas_disponiveis=7.5),
                              dict(turno="T2", site=SITE, inicio="14:00", fim="22:00", horas_disponiveis=7.5)])
        c["cad_setup"] = _df([
            dict(recurso="LINHA-1", familia_origem="IOGURTE", familia_destino="BEBIDA", minutos=45),
            dict(recurso="LINHA-1", familia_origem="BEBIDA", familia_destino="IOGURTE", minutos=60),
            dict(recurso="LINHA-1", familia_origem="IOGURTE", familia_destino="IOGURTE", minutos=10),
            dict(recurso="LINHA-1", familia_origem="BEBIDA", familia_destino="BEBIDA", minutos=10),
            dict(recurso="PRENSA-1", familia_origem="QUEIJO", familia_destino="QUEIJO", minutos=20)])
        c["cad_acordo_validade"] = _df([dict(cliente=k[0], sku=k[1], validade_minima_dias=v) for k, v in ACORDO.items()])
        params = []
        for s in [*PA, *MP]:
            params.append(dict(sku=s, site=SITE, nivel_servico=0.98 if s == "LEITE-L" else 0.95,
                               dias_parados=1 if s in PA else 0, transito_dias=1 if s in PA else 0,
                               custo_pedido=150 if s in PA else 80, taxa_manter_ano=0.25,
                               lead_time_reposicao_dias=1 if s in PA else None, tolerancia_contagem_pct=None))
        c["parametro_sku_local"] = _df(params)
        c["parametro_empresa"] = _df([dict(empresa="DEMO", otif_tolerancia_pct=0.0, limiar_ocupacao=0.15, limiar_k02b=0.3,
                                           n_min_observacoes=20, janela_demanda_dias=28, janela_lead_time_dias=56,
                                           janela_clientes_dias=28, apto_n_contagens=2, apto_janela_dias=30,
                                           apto_limiar=0.9, horizonte_projecao_dias=21)])
        return c

    # ------------------------------------------------------------------ simulação
    def vmin(self, cliente, sku):
        if (cliente, sku) in ACORDO:
            return ACORDO[(cliente, sku)]
        return CLIENTES[cliente][5] if CLIENTES[cliente][5] is not None else PA[sku]["vmin"]

    def estoque_inicial(self, d0: date):
        for i, (s, p) in enumerate(PA.items()):
            for k, idade in enumerate((8, 3)):
                lote = f"{s}-{d0 - timedelta(days=idade):%y%m%d}"
                self.e.validade[(s, lote)] = d0 - timedelta(days=idade) + timedelta(days=p["shelf"])
                q = p["cx"] * (60 if s == "IOG-170" else 30 if s == "BEB-1L" else 15)
                end = PICKING[(2 * i + k) % len(PICKING)]
                self.e.sistema[(s, lote, end)] += q
                self.e.fisico[(s, lote, end)] += q
        lote = f"LT-{d0:%y%m%d}"
        self.e.validade[("LEITE-L", lote)] = d0 + timedelta(days=5)
        for k, q in (((("LEITE-L", lote, END_LEITE)), 6000), (("EMB-POTE", "", END_POTE), 60000),
                     (("CX-PAP", "", END_CX), 3000)):
            self.e.sistema[k] += q
            self.e.fisico[k] += q

    def gerar(self) -> None:
        d0 = INICIO - timedelta(days=1)
        self.estoque_inicial(d0)
        self.omitir_dias = set(DIAS_OMITIDOS)
        self.fotografar(d0)
        for n in range(DIAS):
            d = INICIO + timedelta(days=n)
            self.dia(d)
            self.fotografar(d)

    def dia(self, d: date):
        self.receber(d)
        self.liberar_quarentena(d)
        if _util(d):
            self.expedir(d)
            self.entregar(d)
        self.pedidos_do_dia(d)
        self.produzir(d, "T1")
        if _util(d):
            self.contar(d)
        self.erros_fisicos(d)
        self.baixas(d)
        self.produzir(d, "T2")
        self.comprar(d)

    # --- pedidos de venda (eventos do cliente)
    def pedidos_do_dia(self, d: date):
        if not _util(d):
            return
        for cli, v in CLIENTES.items():
            numero = f"PV-{d:%y%m%d}-{cli}"
            item = 0
            desejada = _proximo_util(d, 1 + int(self.rng.random() < 0.3))
            for sku, media in v[6].items():
                prob = min(0.95, media / 2) if media < 1 else 0.85
                if self.rng.random() > prob:
                    continue
                cx = max(1, int(self.rng.poisson(max(media, 1))))
                item += 1
                qtd = cx * PA[sku]["cx"]
                inst = _dt(d, "10:00", int(self.rng.integers(0, 420)))
                ev = dict(numero_pedido=numero, item=item, cliente=cli, sku=sku, site=SITE, data_desejada=desejada)
                self.out["pedido_venda_evento"].append(dict(ev, numero_evento=1, tipo_evento="CRIACAO", delta_qtd=qtd,
                                                            instante_evento=inst, motivo=None))
                linha = dict(ev, qtd=qtd)
                r = self.rng.random()
                if r < 0.02:
                    self.out["pedido_venda_evento"].append(dict(ev, numero_evento=2, tipo_evento="CANCELAMENTO",
                                                                delta_qtd=-qtd, instante_evento=inst + timedelta(hours=2),
                                                                motivo="CANC_CLIENTE"))
                    linha["qtd"] = 0
                elif r < 0.06:
                    delta = PA[sku]["cx"] * (1 if self.rng.random() < 0.5 else -1)
                    if qtd + delta > 0:
                        self.out["pedido_venda_evento"].append(dict(ev, numero_evento=2, tipo_evento="ALTERACAO",
                                                                    delta_qtd=delta, instante_evento=inst + timedelta(hours=1),
                                                                    motivo=None))
                        linha["qtd"] = qtd + delta
                if linha["qtd"] > 0:
                    self.pedidos_abertos.append(linha)

    # --- expedição: alocação FEFO respeitando validade mínima do cliente
    def expedir(self, d: date):
        hoje = [p for p in self.pedidos_abertos if p["data_desejada"] == d]
        self.pedidos_abertos = [p for p in self.pedidos_abertos if p["data_desejada"] != d]
        self.remessas_hoje = []
        for cli in sorted({p["cliente"] for p in hoje}, key=lambda c: (CLIENTES[c][4], c)):  # prioridade 1 primeiro
            linhas = [p for p in hoje if p["cliente"] == cli]
            ordem = f"OS-{d:%y%m%d}-{cli}"
            nf_num = self.doc("NF")
            chave = chave_nf(nf_num, d)
            item_nf = 0
            peso = vol = 0.0
            for p in linhas:
                vmin_data = d + timedelta(days=self.vmin(cli, p["sku"]) + 1)
                restante = p["qtd"]
                conferido_total = 0.0
                for (s, lote, end), q in self.lotes_fefo(p["sku"], PICKING, vmin_data):
                    if restante <= 0:
                        break
                    solicitada = min(q, restante)
                    fisico = max(0.0, self.e.fisico[(s, lote, end)])
                    separada, conferida, motivo = solicitada, solicitada, None
                    if fisico < solicitada:                       # faltou no endereço (erro de saldo)
                        separada = conferida = math.floor(fisico)
                        motivo = "DIV_ENDERECAMENTO"
                    elif self.rng.random() < 0.02:                # erro de separação pego na conferência
                        separada = solicitada - min(solicitada, PA[s]["cx"])
                        motivo = "DIV_SEPARACAO"
                    tarefa = f"TS-{self.doc('TS'):06d}"
                    inst_sep = _dt(d, "05:00", int(self.rng.integers(0, 90)))
                    self.out["separacao"].append(dict(
                        numero_tarefa=tarefa, ordem_separacao=ordem, numero_pedido=p["numero_pedido"], item=p["item"],
                        sku=s, lote=lote, endereco=end, qtd_solicitada=solicitada, qtd_separada=separada,
                        qtd_conferida=conferida, matricula_separador="M004" if self.rng.random() < 0.5 else "M005",
                        matricula_conferente="M003", instante_separacao=inst_sep,
                        instante_conferencia=inst_sep + timedelta(minutes=20), motivo=motivo))
                    if conferida > 0:
                        self.mover("SAIDA_EXPEDICAO", s, lote, end, -conferida, d, _dt(d, "06:30"), "NF_SAIDA",
                                   chave[-12:], item_nf + 1)
                        item_nf += 1
                        self.out["faturamento"].append(dict(
                            chave_nf=chave, item_nf=item_nf, numero_pedido=p["numero_pedido"], item_pedido=p["item"],
                            ordem_separacao=ordem, cliente=cli, sku=s, site=SITE, qtd=conferida,
                            valor_mercadoria=round(conferida * CUSTO[s] * 1.45, 2), instante_emissao=_dt(d, "06:30")))
                        peso += conferida * PA[s]["peso"]
                        vol += conferida * PA[s]["vol"]
                        conferido_total += conferida
                    restante -= solicitada
            if item_nf:
                self.remessas_hoje.append(dict(remessa=ordem, cliente=cli, peso=peso, vol=vol, tentativa=1))

    def entregar(self, d: date):
        remessas = self.reentregas + getattr(self, "remessas_hoje", [])
        self.reentregas = []
        if not remessas:
            return
        cargas = {"QAA1A11": [], "QBB2B22": []}
        peso = {"QAA1A11": 0.0, "QBB2B22": 0.0}
        for r in sorted(remessas, key=lambda r: (CLIENTES[r["cliente"]][4], r["remessa"])):
            placa = "QAA1A11" if peso["QAA1A11"] + r["peso"] <= VEICULOS["QAA1A11"]["kg"] * 0.95 and r["cliente"] != "C05" \
                else "QBB2B22"
            cargas[placa].append(r)
            peso[placa] += r["peso"]
        for placa, rs in cargas.items():
            if not rs:
                continue
            v = VEICULOS[placa]
            viagem = f"VG-{d:%y%m%d}-{placa[-3:]}"
            saida = _dt(d, "07:00", int(self.rng.integers(0, 40)))
            relogio = saida
            for r in rs:
                relogio += timedelta(minutes=int(self.rng.integers(25, 75 if r["cliente"] != "C05" else 160)))
                ini, fim = CLIENTES[r["cliente"]][3]
                status, motivo = "ENTREGUE", None
                if relogio > _dt(d, fim):
                    status, motivo = "FRUSTRADA", "ENT_FORA_JANELA"
                elif self.rng.random() < 0.02:
                    status, motivo = "FRUSTRADA", "ENT_CLIENTE_FECHADO"
                chegada = max(relogio, _dt(d, ini))
                self.out["entrega"].append(dict(numero_viagem=viagem, remessa=r["remessa"], numero_tentativa=r["tentativa"],
                                                cliente=r["cliente"], status=status, motivo=motivo, instante_chegada=chegada,
                                                instante_conclusao=chegada + timedelta(minutes=20)))
                relogio = chegada + timedelta(minutes=20)
                if status != "ENTREGUE":
                    self.reentregas.append(dict(r, tentativa=r["tentativa"] + 1))
            self.out["viagem"].append(dict(numero_viagem=viagem, placa=placa,
                                           matricula_motorista="M010" if placa == "QAA1A11" else "M011", site=SITE,
                                           custo_viagem=v["fixo"] + v["por_parada"] * len(rs), instante_saida=saida,
                                           instante_retorno=relogio + timedelta(minutes=45)))

    # --- produção: programa congelado na véspera, apontamento por turno, entrada em quarentena
    def demanda_prevista(self, sku, d, dias=3):
        conhecida = sum(p["qtd"] for p in self.pedidos_abertos if p["sku"] == sku and d <= p["data_desejada"] <= d + timedelta(days=dias))
        media = sum(m * PA[sku]["cx"] for c in CLIENTES.values() for s, m in c[6].items() if s == sku) * 0.85
        return max(conhecida, media * dias)

    def produzir(self, d: date, turno: str):
        if not _util(d):
            return
        plano = {"T1": [("LINHA-1", "IOG-170"), ("PRENSA-1", "QJ-500")], "T2": [("LINHA-1", "BEB-1L")]}[turno]
        for seq, (rec, sku) in enumerate(plano, start=1):
            p = PA[sku]
            disponivel = self.estoque_sku(sku, PICKING + [END_QUAR])
            alvo = self.demanda_prevista(sku, d, 3) + 2 * self.demanda_prevista(sku, d, 1) - disponivel
            setup = 60 if (rec == "LINHA-1" and turno == "T2") else 45 if rec == "LINHA-1" else 20
            cap = max(0.0, (450 - setup) / p["min_un"])
            qtd = min(max(0.0, alvo), cap)
            qtd = math.ceil(qtd / p["cx"]) * p["cx"]
            if qtd <= 0:
                continue
            op = f"OP-{d:%y%m%d}-{sku}"
            self.out["programacao_op"].append(dict(numero_op=op, versao=1, congelada="S", data=d, turno=turno, recurso=rec,
                                                   sku=sku, sequencia=seq, qtd_programada=qtd,
                                                   tempo_padrao_min_un=p["min_un"], setup_min=setup))
            if self.rng.random() < 0.15:  # reprogramação depois do congelamento (não conta para a aderência)
                self.out["programacao_op"].append(dict(numero_op=op, versao=2, congelada="N", data=d, turno=turno,
                                                       recurso=rec, sku=sku, sequencia=seq,
                                                       qtd_programada=qtd + p["cx"] * 5, tempo_padrao_min_un=p["min_un"],
                                                       setup_min=setup))
            fim_turno = _dt(d, "14:00" if turno == "T1" else "22:00")
            # limite pela matéria-prima disponível
            leite_disp = self.estoque_sku("LEITE-L", [END_LEITE])
            boa = min(qtd * float(self.rng.uniform(0.85, 1.02)), leite_disp / p["leite"] * 0.98)
            boa = math.floor(boa / p["cx"]) * p["cx"]
            refugo = math.floor(boa * 0.01) if self.rng.random() < 0.5 else 0
            if boa <= 0:
                continue
            lote = f"{sku}-{d:%y%m%d}"
            self.e.validade[(sku, lote)] = d + timedelta(days=p["shelf"])
            self.out["apontamento"].append(dict(numero_op=op, numero_apontamento=1, recurso=rec, turno=turno, sku=sku,
                                                lote=lote, qtd_boa=boa, qtd_refugo=refugo,
                                                motivo_refugo="REF_QUALIDADE" if refugo else None,
                                                instante_apontamento=fim_turno))
            self.mover("ENTRADA_PRODUCAO", sku, lote, END_QUAR, boa, d, fim_turno, "OP", op)
            lanc_consumo = fim_turno + (timedelta(hours=18) if self.rng.random() < 0.08 else timedelta())  # retroativo
            self.consumir("LEITE-L", END_LEITE, (boa + refugo) * p["leite"], d, lanc_consumo, op)
            if p["pote"]:
                self.consumir("EMB-POTE", END_POTE, (boa + refugo) * p["pote"], d, fim_turno, op)
            self.consumir("CX-PAP", END_CX, boa / p["cx"], d, fim_turno, op)

    def liberar_quarentena(self, d: date):
        for (s, l, e), q in list(self.e.sistema.items()):
            if e == END_QUAR and q > 1e-9 and self.e.validade[(s, l)] - timedelta(days=PA[s]["shelf"]) < d:
                destino = min(PICKING, key=lambda x: sum(qq for (ss, _, ee), qq in self.e.sistema.items() if ee == x and qq > 0))
                doc = f"TR-{self.doc('TR'):06d}"
                inst = _dt(d, "07:00")
                self.mover("TRANSFERENCIA_SAIDA", s, l, e, -q, d, inst, "TRANSFERENCIA", doc)
                self.mover("TRANSFERENCIA_ENTRADA", s, l, destino, q, d, inst, "TRANSFERENCIA", doc)

    # --- compras e recebimento
    def comprar(self, d: date):
        consumo_leite = sum(PA[s]["leite"] * self.demanda_prevista(s, d, 1) for s in PA)
        aberto = sum(pc["qtd"] for pc in self.pcs_abertos if pc["sku"] == "LEITE-L")
        precisa = 2 * consumo_leite - self.estoque_sku("LEITE-L", [END_LEITE]) - aberto
        if precisa > 0:
            self.emitir_pc("LEITE-L", FORNECEDOR_LEITE, max(4000, math.ceil(precisa / 1000) * 1000), d, 1)
        for sku, rop, lote, end in (("EMB-POTE", 40000, 60000, END_POTE), ("CX-PAP", 1500, 2500, END_CX)):
            aberto = sum(pc["qtd"] for pc in self.pcs_abertos if pc["sku"] == sku)
            if self.estoque_sku(sku, [end]) + aberto < rop:
                self.emitir_pc(sku, FORNECEDOR_EMB, lote, d, 7)

    def emitir_pc(self, sku, fornecedor, qtd, d, lt):
        numero = f"PC-{self.doc('PC'):05d}"
        prevista = d + timedelta(days=lt)
        inst = _dt(d, "16:00")
        self.out["pedido_compra_evento"].append(dict(numero_pc=numero, item=1, numero_evento=1, tipo_evento="EMISSAO",
                                                     fornecedor_cnpj=fornecedor, sku=sku, site=SITE, delta_qtd=qtd,
                                                     data_prevista=prevista, instante_evento=inst, motivo=None))
        real = lt + (1 if self.rng.random() < 0.15 else 0) + (int(self.rng.integers(0, 3)) if lt > 1 else 0)
        if lt > 1 and self.rng.random() < 0.3:  # fornecedor avisa atraso
            self.out["pedido_compra_evento"].append(dict(numero_pc=numero, item=1, numero_evento=2,
                                                         tipo_evento="ALTERACAO", fornecedor_cnpj=fornecedor, sku=sku,
                                                         site=SITE, delta_qtd=0, data_prevista=prevista + timedelta(days=2),
                                                         instante_evento=inst + timedelta(days=1), motivo=None))
        self.pcs_abertos.append(dict(numero=numero, sku=sku, fornecedor=fornecedor, qtd=qtd,
                                     chegada=d + timedelta(days=real)))

    def receber(self, d: date):
        chegam = [pc for pc in self.pcs_abertos if pc["chegada"] <= d]
        self.pcs_abertos = [pc for pc in self.pcs_abertos if pc["chegada"] > d]
        for pc in chegam:
            sku = pc["sku"]
            rec = f"RC-{self.doc('RC'):05d}"
            recusada, motivo = 0.0, None
            if self.rng.random() < 0.04:
                recusada, motivo = pc["qtd"] * 0.1, "REC_AVARIA"
            recebida = pc["qtd"] - recusada
            lote = f"LT-{d:%y%m%d}" if sku == "LEITE-L" else ""
            if lote:
                self.e.validade[(sku, lote)] = d + timedelta(days=MP[sku]["shelf"])
            end = {"LEITE-L": END_LEITE, "EMB-POTE": END_POTE, "CX-PAP": END_CX}[sku]
            inst = _dt(d, "06:00", int(self.rng.integers(0, 120)))
            self.out["recebimento"].append(dict(
                numero_recebimento=rec, item=1, numero_pc=pc["numero"], item_pc=1,
                chave_nf_entrada=chave_nf(500000 + self.doc("NFE"), d), fornecedor_cnpj=pc["fornecedor"], sku=sku,
                lote=lote, data_validade=self.e.validade.get((sku, lote)) if lote else None, endereco=end,
                qtd_esperada=pc["qtd"], qtd_recebida=recebida, qtd_recusada=recusada, motivo=motivo,
                matricula_conferente="M003", instante_conferencia=inst))
            self.mover("ENTRADA_RECEBIMENTO", sku, lote, end, recebida, d, inst, "RECEBIMENTO", rec)

    # --- erros físicos (ocultos) e contagem cíclica
    def erros_fisicos(self, d: date):
        posicoes = [k for k, q in self.e.fisico.items() if k[2] in PICKING and q > 30]
        if not posicoes:
            return
        r = self.rng.random()
        if r < 0.10:
            k = posicoes[int(self.rng.integers(len(posicoes)))]
            perda = float(self.rng.integers(1, 13))
            self.e.fisico[k] -= perda
            causa = self.rng.choice(["SEPARACAO", "RECEBIMENTO", "ENDERECAMENTO"], p=[0.5, 0.2, 0.3])
            self.e.causas[k].append(str(causa))
        elif r < 0.14:  # troca de endereço: some de um, aparece em outro (ajuste bruto alto, líquido ~0)
            k = posicoes[int(self.rng.integers(len(posicoes)))]
            outro = [e for e in PICKING if e != k[2]][int(self.rng.integers(len(PICKING) - 1))]
            q = float(self.rng.integers(6, 25))
            self.e.fisico[k] -= q
            self.e.fisico[(k[0], k[1], outro)] += q
            self.e.causas[k].append("ENDERECAMENTO")
            self.e.causas[(k[0], k[1], outro)].append("ENDERECAMENTO")

    def contar(self, d: date):
        contaveis = PICKING + [END_LEITE, END_POTE, END_CX]
        posicoes = sorted({k for k, q in list(self.e.sistema.items()) + list(self.e.fisico.items())
                           if k[2] in contaveis and abs(q) > 1e-9})
        if not posicoes:
            return
        idx = self.rng.choice(len(posicoes), size=min(6, len(posicoes)), replace=False)
        for i in sorted(idx):
            s, l, e = posicoes[i]
            sistema = max(0.0, self.e.sistema[(s, l, e)])
            fisico = max(0.0, self.e.fisico[(s, l, e)])
            numero = f"CNT-{d:%y%m%d}-{i:02d}"
            congel = _dt(d, "15:00")
            base = dict(numero_contagem=numero, endereco=e, sku=s, lote=l, qtd_sistema_congelada=sistema,
                        instante_congelamento=congel, matricula="M001")
            self.out["contagem"].append(dict(base, numero_recontagem=0, qtd_contada=fisico,
                                             instante_contagem=congel + timedelta(minutes=10)))
            if abs(fisico - sistema) > 1e-9:
                self.out["contagem"].append(dict(base, numero_recontagem=1, qtd_contada=fisico,
                                                 instante_contagem=congel + timedelta(minutes=30)))
                causas = self.e.causas.pop((s, l, e), [])
                etapa = causas[-1] if causas and self.rng.random() > 0.15 else "DESCONHECIDA"
                motivo = {"SEPARACAO": "DIV_SEPARACAO", "RECEBIMENTO": "DIV_RECEBIMENTO",
                          "ENDERECAMENTO": "DIV_ENDERECAMENTO"}.get(etapa, "DESCONHECIDO")
                self.out["investigacao_divergencia"].append(dict(numero_contagem=numero, endereco=e, sku=s, lote=l,
                                                                 motivo=motivo, matricula="M002"))
                dif = fisico - sistema
                self.mover("AJUSTE_POSITIVO" if dif > 0 else "AJUSTE_NEGATIVO", s, l, e, dif, d,
                           _dt(d, "16:30"), "CONTAGEM", numero, fisico=False)

    def baixas(self, d: date):
        for (s, l, e), q in list(self.e.sistema.items()):
            if q <= 1e-9 or not l:
                continue
            val = self.e.validade[(s, l)]
            if s in PA:
                menor_vmin = min(self.vmin(c, s) for c in CLIENTES)
                vencido = val < d + timedelta(days=menor_vmin + 1)
            else:
                vencido = val < d
            if vencido:
                doc = f"BX-{self.doc('BX'):05d}"
                self.mover("BAIXA", s, l, e, -q, d, _dt(d, "20:00"), "AJUSTE", doc, motivo="BAIXA_VENCIMENTO")
                self.e.fisico[(s, l, e)] = 0.0

    # --- fotografia diária (extração do ERP às 00:30 do dia seguinte)
    def fotografar(self, d: date):
        ext = _dt(d + timedelta(days=1), "00:30")
        saldo = defaultdict(float)
        if d < INICIO:
            for k, q in self.e.sistema.items():
                saldo[k] += q
        else:
            base = self.saldo_inicial
            for k, q in base.items():
                saldo[k] += q
            for m in self.e.razao:
                if m["data_movimento"] <= d and m["instante_lancamento"] <= ext:
                    saldo[(m["sku"], m["lote"], m["endereco"])] += m["qtd"]
        if d < INICIO:
            self.saldo_inicial = dict(saldo)
        linhas = [dict(site=SITE, data_saldo=d, instante_extracao=ext, sku=s, lote=l,
                       data_validade=self.e.validade.get((s, l)) if l else None, endereco=e, qtd_fisica=round(q, 6),
                       qtd_bloqueada=0, qtd_reservada=0, custo_unit_medio=CUSTO[s])
                  for (s, l, e), q in sorted(saldo.items()) if q > 1e-9]
        self.saldos.append((d, _df(linhas)))

    # ------------------------------------------------------------------ saída
    def arquivos(self) -> list[tuple[str, pd.DataFrame]]:
        """Ordem de carga: cadastros, parâmetros, transacionais; fotografias uma por dia."""
        seq = list(self.cadastros().items())
        movs = []
        omitidos = set()
        for m in self.e.razao:
            if m["data_movimento"] in self.omitir_dias and m["data_movimento"] not in omitidos \
                    and m["tipo_movimento"] == "SAIDA_EXPEDICAO":
                omitidos.add(m["data_movimento"])   # o extrato "perdeu" este movimento
                continue
            movs.append(m)
        self.omitidos = omitidos
        for nome in ("pedido_venda_evento", "pedido_compra_evento", "recebimento", "programacao_op", "apontamento",
                     "separacao", "faturamento", "viagem", "entrega"):
            seq.append((nome, _df(self.out[nome])))
        seq.append(("mov_estoque", _df(movs)))
        for d, df in self.saldos:
            seq.append(("saldo_estoque", df))
        seq.append(("contagem", _df(self.out["contagem"])))
        seq.append(("investigacao_divergencia", _df(self.out["investigacao_divergencia"])))
        return seq


def gerar() -> Simulacao:
    s = Simulacao()
    s.gerar()
    return s


def carregar(con, usuario: str = "simulacao") -> list:
    """Carrega a simulação inteira (marcada sintética) e reconstrói o modelo uma única vez no fim."""
    from app import carga, transform
    resultados = []
    for nome, df in gerar().arquivos():
        r = carga.registrar(con, nome, df, usuario=usuario, fonte="UPLOAD", nome_arquivo=f"simulacao_{nome}",
                            sintetico=True, reconstruir=False)
        resultados.append((nome, r))
    transform.reconstruir(con)
    return resultados
