"""Gera dados SINTÉTICOS para validar a MECÂNICA da frente 1 (fórmula, fluxo, somatório).

Não valida parâmetro: nenhuma quantidade aqui representa operação real. Toda carga feita com estes
dados entra com sintetico = 1 e tudo o que deriva dela nasce provisório.

Cenário (determinístico):
- 1 site, 4 endereços, 3 SKUs (2 com lote/validade), 2 colaboradores.
- Fotografias de saldo em D0 e D1 e movimentos de D1 coerentes entre si, EXCETO:
  * um movimento de D1 que não veio no extrato (deve aparecer como exceção de reconciliação em D1);
  * um movimento retroativo (datado D0, lançado depois da extração de D0) — NÃO deve gerar exceção.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

D0 = date(2026, 10, 5)
D1 = D0 + timedelta(days=1)
EXT0 = datetime.combine(D1, datetime.min.time()).replace(hour=0, minute=30)   # extração do saldo de D0
EXT1 = datetime.combine(D1 + timedelta(days=1), datetime.min.time()).replace(hour=0, minute=30)


def cadastros() -> dict[str, pd.DataFrame]:
    return {
        "cad_site": pd.DataFrame([{"site": "CD01", "descricao": "CD sintético", "horario_corte": "00:00"}]),
        "cad_local": pd.DataFrame([
            {"endereco": "A-01-01", "site": "CD01", "zona": "A", "tipo": "PICKING", "classe_temperatura": "REFRIGERADO"},
            {"endereco": "A-01-02", "site": "CD01", "zona": "A", "tipo": "PICKING", "classe_temperatura": "REFRIGERADO"},
            {"endereco": "B-01-01", "site": "CD01", "zona": "B", "tipo": "PULMAO", "classe_temperatura": "SECO"},
            {"endereco": "Q-01", "site": "CD01", "zona": "Q", "tipo": "QUARENTENA", "classe_temperatura": "REFRIGERADO"},
        ]),
        "cad_sku": pd.DataFrame([
            {"sku": "IOG-170", "descricao": "Iogurte 170 g (sintético)", "tipo": "PA", "familia": "IOGURTE",
             "unidade_base": "UN", "controla_lote": "S", "shelf_life_dias": "35", "validade_minima_padrao_dias": "10",
             "classe_temperatura": "REFRIGERADO", "peso_bruto_kg_un_base": "0.18", "volume_m3_un_base": "0.00025",
             "codigo_barras": "7890000000017"},
            {"sku": "QJ-500", "descricao": "Queijo 500 g (sintético)", "tipo": "PA", "familia": "QUEIJO",
             "unidade_base": "UN", "controla_lote": "S", "shelf_life_dias": "60", "validade_minima_padrao_dias": "20",
             "classe_temperatura": "REFRIGERADO", "peso_bruto_kg_un_base": "0.52", "volume_m3_un_base": "0.0006",
             "codigo_barras": "7890000000024"},
            {"sku": "CX-PAP", "descricao": "Caixa de papelão (sintético)", "tipo": "EMBALAGEM", "familia": "EMB",
             "unidade_base": "UN", "controla_lote": "N", "shelf_life_dias": "", "validade_minima_padrao_dias": "",
             "classe_temperatura": "SECO", "peso_bruto_kg_un_base": "0.3", "volume_m3_un_base": "0.002",
             "codigo_barras": ""},
        ]),
        "cad_sku_unidade": pd.DataFrame([
            {"sku": "IOG-170", "unidade": "CX", "fator_para_base": "24", "e_unidade_palete": "N"},
            {"sku": "IOG-170", "unidade": "PL", "fator_para_base": "2400", "e_unidade_palete": "S"},
            {"sku": "QJ-500", "unidade": "CX", "fator_para_base": "12", "e_unidade_palete": "N"},
        ]),
        "cad_colaborador": pd.DataFrame([
            {"matricula": "M001", "funcao": "INVENTARIANTE", "turno": "T1", "site": "CD01"},
            {"matricula": "M002", "funcao": "SUPERVISOR", "turno": "T1", "site": "CD01"},
        ]),
    }


def _saldo(d: date, ext: datetime, linhas: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame([{
        "site": "CD01", "data_saldo": d.isoformat(), "instante_extracao": ext.strftime("%Y-%m-%d %H:%M:%S"),
        "sku": sku, "lote": lote, "data_validade": val, "endereco": end, "qtd_fisica": str(q),
        "qtd_bloqueada": "0", "qtd_reservada": "0", "custo_unit_medio": custo}
        for sku, lote, val, end, q, custo in linhas])


def saldo_d0() -> pd.DataFrame:
    return _saldo(D0, EXT0, [
        ("IOG-170", "L1001", "2026-10-20", "A-01-01", 480, "1.10"),
        ("IOG-170", "L1002", "2026-11-02", "A-01-02", 960, "1.10"),
        ("QJ-500", "Q2001", "2026-12-01", "A-01-02", 120, "9.50"),
        ("CX-PAP", "", "", "B-01-01", 1000, "0.80"),
    ])


def movimentos_d1() -> pd.DataFrame:
    def m(doc_tipo, doc, item, tipo, sku, lote, end, qtd, custo, dia, lanc, motivo=""):
        return {"documento_tipo": doc_tipo, "documento_numero": doc, "item": str(item), "sequencia": "1",
                "tipo_movimento": tipo, "sku": sku, "lote": lote, "data_validade": "", "endereco": end,
                "qtd": str(qtd), "custo_unit": custo, "data_movimento": dia.isoformat(),
                "instante_lancamento": lanc.strftime("%Y-%m-%d %H:%M:%S"), "motivo": motivo}
    t = lambda h: datetime.combine(D1, datetime.min.time()).replace(hour=h)  # noqa: E731
    return pd.DataFrame([
        m("NF_SAIDA", "NF-5001", 1, "SAIDA_EXPEDICAO", "IOG-170", "L1001", "A-01-01", -240, "1.10", D1, t(9)),
        m("NF_SAIDA", "NF-5002", 1, "SAIDA_EXPEDICAO", "QJ-500", "Q2001", "A-01-02", -24, "9.50", D1, t(10)),
        m("RECEBIMENTO", "REC-77", 1, "ENTRADA_RECEBIMENTO", "IOG-170", "L1003", "A-01-01", 480, "1.10", D1, t(11)),
        m("OP", "OP-300", 1, "SAIDA_CONSUMO", "CX-PAP", "", "B-01-01", -200, "0.80", D1, t(14)),
        # retroativo: datado D0, lançado em D1 depois da extração de D0 → entra na janela de D1, sem exceção
        m("AJUSTE", "AJ-9", 1, "AJUSTE_NEGATIVO", "IOG-170", "L1002", "A-01-02", -12, "1.10", D0, t(8)),
        # o extrato NÃO traz a saída NF-5003 de 48 un de L1002 → exceção esperada em D1 (A-01-02, L1002)
    ])


def saldo_d1() -> pd.DataFrame:
    return _saldo(D1, EXT1, [
        ("IOG-170", "L1001", "2026-10-20", "A-01-01", 240, "1.10"),
        ("IOG-170", "L1002", "2026-11-02", "A-01-02", 900, "1.10"),   # 960 − 12 (retroativo) − 48 (faltante)
        ("IOG-170", "L1003", "2026-11-10", "A-01-01", 480, "1.10"),
        ("QJ-500", "Q2001", "2026-12-01", "A-01-02", 96, "9.50"),
        ("CX-PAP", "", "", "B-01-01", 800, "0.80"),
    ])


def sequencia_demo() -> list[tuple[str, pd.DataFrame]]:
    """Ordem de carga do cenário: cadastros, fotografia D0, movimentos D1, fotografia D1."""
    return [*cadastros().items(), ("saldo_estoque", saldo_d0()), ("mov_estoque", movimentos_d1()),
            ("saldo_estoque", saldo_d1())]
