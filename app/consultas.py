"""Consultas usadas pelas telas de entrada (não é o dashboard — esse é a Etapa 8)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.transform import NAO_SE_APLICA, sk
from app.config import EMPRESA_PADRAO


def saldo_congelado(con, endereco: str, sku: str, lote: str | None, agora: datetime,
                    empresa: str = EMPRESA_PADRAO) -> tuple[float, str] | None:
    """Saldo do sistema na posição, no instante: última fotografia do site + movimentos lançados depois dela.

    Retorna None se o site do endereço não tem fotografia — sem base, a contagem não pode ser comparada.
    """
    linha = con.execute(
        """
        SELECT c.data_saldo, c.instante_extracao
        FROM cobertura_saldo c JOIN dim_local l ON l.site = c.site
        WHERE l.endereco = ? AND c.instante_extracao <= ?
        ORDER BY c.instante_extracao DESC LIMIT 1
        """, [endereco, agora]).fetchone()
    if linha is None:
        return None
    data_saldo, ext = linha
    sku_sk, local_sk = sk(empresa, "sku", sku), sk(empresa, "local", endereco)
    lote_sk = NAO_SE_APLICA if not lote else sk(empresa, "lote", sku, lote)
    base = con.execute(
        "SELECT coalesce(sum(qtd_fisica), 0) FROM fato_saldo_diario WHERE data_saldo = ? AND sku_sk = ? AND lote_sk = ? AND local_sk = ?",
        [data_saldo, sku_sk, lote_sk, local_sk]).fetchone()[0]
    mov = con.execute(
        """SELECT coalesce(sum(qtd), 0) FROM fato_movimento_estoque
           WHERE sku_sk = ? AND lote_sk = ? AND local_sk = ? AND instante_lancamento > ? AND instante_lancamento <= ?""",
        [sku_sk, lote_sk, local_sk, ext, agora]).fetchone()[0]
    return float(base + mov), f"fotografia de {data_saldo} (extraída {ext:%Y-%m-%d %H:%M}) + movimentos lançados depois"


def lotes_do_sku(con, sku: str) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT lote FROM dim_lote WHERE sku = ? AND lote_sk > 0 ORDER BY data_validade NULLS LAST, lote", [sku]).fetchall()]


def proximo_numero_recontagem(con, numero_contagem: str, endereco: str, sku: str, lote: str | None) -> int:
    r = con.execute(
        """SELECT max(c.numero_recontagem) FROM fato_contagem c
           JOIN dim_local l USING (local_sk) JOIN dim_sku s USING (sku_sk)
           LEFT JOIN dim_lote lt ON lt.lote_sk = c.lote_sk AND c.lote_sk > 0
           WHERE c.numero_contagem = ? AND l.endereco = ? AND s.sku = ? AND coalesce(lt.lote, '') = ?""",
        [numero_contagem, endereco, sku, lote or ""]).fetchone()[0]
    return 0 if r is None else int(r) + 1


def divergencias_pendentes(con) -> pd.DataFrame:
    return con.execute("SELECT * FROM v_divergencias_pendentes ORDER BY instante_contagem").df()


def historico_cargas(con, limite: int = 200) -> pd.DataFrame:
    return con.execute(
        """SELECT carga_id, layout, fonte, status, nome_arquivo, usuario, instante, sintetico,
                  n_linhas, n_novas, n_correcoes, n_repetidas, n_erros
           FROM bruto_carga ORDER BY carga_id DESC LIMIT ?""", [limite]).df()


def erros_da_carga(con, carga_id: int) -> pd.DataFrame:
    return con.execute(
        "SELECT num_linha AS linha, status, erros FROM bruto_linha WHERE carga_id = ? AND erros IS NOT NULL ORDER BY num_linha",
        [carga_id]).df()


def resumo_reconciliacao(con) -> pd.DataFrame:
    """K04 por site × dia: exceções onde há fotografia no dia e na véspera; sem isso, 'não verificável'."""
    return con.execute(
        """
        SELECT c.site, CAST(c.data_saldo AS VARCHAR) AS data_saldo,
               CASE WHEN p.site IS NULL THEN NULL
                    ELSE (SELECT count(*) FROM v_reconciliacao r
                          WHERE r.site = c.site AND r.data_saldo = c.data_saldo AND abs(r.dif_reconciliacao) > 1e-6)
               END AS excecoes,
               CASE WHEN p.site IS NULL THEN 'não verificável (sem fotografia da véspera)' ELSE 'verificado' END AS situacao,
               c.sintetico
        FROM cobertura_saldo c
        LEFT JOIN cobertura_saldo p ON p.site = c.site AND p.data_saldo = c.data_saldo - 1
        ORDER BY c.site, c.data_saldo
        """).df()


def excecoes_reconciliacao(con) -> pd.DataFrame:
    return con.execute(
        """SELECT r.site, CAST(r.data_saldo AS VARCHAR) AS data_saldo, s.sku, coalesce(lt.lote, '') AS lote, l.endereco,
                  r.saldo_vespera, r.movimentos, r.saldo_dia, r.dif_reconciliacao
           FROM v_reconciliacao r
           JOIN dim_sku s USING (sku_sk) JOIN dim_local l USING (local_sk)
           LEFT JOIN dim_lote lt ON lt.lote_sk = r.lote_sk AND r.lote_sk > 0
           WHERE abs(r.dif_reconciliacao) > 1e-6
           ORDER BY r.site, r.data_saldo, s.sku""").df()


def colaboradores(con, funcoes: tuple[str, ...]) -> list[str]:
    marcadores = ",".join("?" * len(funcoes))
    return [r[0] for r in con.execute(
        f"SELECT matricula FROM dim_colaborador WHERE funcao IN ({marcadores}) ORDER BY matricula", list(funcoes)).fetchall()]
