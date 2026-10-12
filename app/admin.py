"""Administração: expurgo do histórico SINTÉTICO antes da entrada de dados reais.

Uso: python -m app.admin limpar-sinteticos --usuario NOME --confirmar
Apaga apenas cargas com sintetico = true (e suas linhas), registra o expurgo em bruto_expurgo e
reconstrói o modelo. Cargas reais nunca são tocadas: a imutabilidade do bruto vale para elas.
"""
from __future__ import annotations

import argparse
from datetime import datetime

from app import transform
from app.db import conectar

FRASE_CONFIRMACAO = "APAGAR SINTETICOS"


def resumo_sinteticos(con) -> tuple[int, int]:
    n_cargas = con.execute("SELECT count(*) FROM bruto_carga WHERE sintetico").fetchone()[0]
    n_linhas = con.execute(
        "SELECT count(*) FROM bruto_linha WHERE carga_id IN (SELECT carga_id FROM bruto_carga WHERE sintetico)").fetchone()[0]
    return n_cargas, n_linhas


def limpar_sinteticos(con, usuario: str, motivo: str = "troca do cenário sintético por dados reais") -> tuple[int, int]:
    if not usuario or not usuario.strip():
        raise ValueError("usuário é obrigatório para o expurgo")
    n_cargas, n_linhas = resumo_sinteticos(con)
    con.execute("BEGIN")
    try:
        con.execute("DELETE FROM bruto_linha WHERE carga_id IN (SELECT carga_id FROM bruto_carga WHERE sintetico)")
        con.execute("DELETE FROM bruto_carga WHERE sintetico")
        con.execute("INSERT INTO bruto_expurgo VALUES (?, ?, ?, ?, ?)",
                    [datetime.now(), usuario.strip(), n_cargas, n_linhas, motivo])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    transform.reconstruir(con)
    return n_cargas, n_linhas


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    l = sub.add_parser("limpar-sinteticos", help="apaga as cargas sintéticas e reconstrói o modelo")
    l.add_argument("--usuario", required=True)
    l.add_argument("--confirmar", action="store_true", help="sem esta opção, só mostra o que seria apagado")
    s = sub.add_parser("carregar-simulacao", help="carrega o cenário sintético de 8 semanas")
    s.add_argument("--usuario", required=True)
    a = p.parse_args(argv)
    con = conectar()
    if a.comando == "limpar-sinteticos":
        n_cargas, n_linhas = resumo_sinteticos(con)
        if not a.confirmar:
            print(f"Seriam apagadas {n_cargas} cargas sintéticas ({n_linhas} linhas). Repita com --confirmar.")
            return
        print("Apagadas {} cargas ({} linhas).".format(*limpar_sinteticos(con, a.usuario)))
    else:
        from app.carga import garantir_modelo
        from dados_sinteticos import simulacao
        garantir_modelo(con)
        res = simulacao.carregar(con, a.usuario)
        print(f"{sum(1 for _, r in res if r.status == 'ACEITA')} de {len(res)} cargas aceitas.")


if __name__ == "__main__":
    main()
