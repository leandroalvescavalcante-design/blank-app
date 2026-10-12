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
    d = sub.add_parser("definir-pin", help="cria ou troca o PIN de uma matrícula para o app do celular")
    d.add_argument("--matricula", required=True)
    d.add_argument("--pin", help="4 a 8 dígitos; sem esta opção, é pedido sem aparecer na tela")
    r = sub.add_parser("remover-pin", help="revoga o acesso de uma matrícula ao celular (vale na hora)")
    r.add_argument("--matricula", required=True)
    sub.add_parser("processar-celular", help="processa a fila do celular agora (com a ferramenta FECHADA)")
    sub.add_parser("gerar-certificado", help="regera o certificado HTTPS do servidor (ex.: mudou o IP do computador)")
    a = p.parse_args(argv)
    if a.comando in ("definir-pin", "remover-pin", "gerar-certificado"):
        return _comando_celular(a)
    con = conectar()
    if a.comando == "processar-celular":
        from app.carga import garantir_modelo
        from app.movel import integracao
        garantir_modelo(con)
        res = integracao.processar_fila(con)
        print(f"{len(res)} item(ns) processado(s): " + ", ".join(f"{r.get('status')}" for r in res) if res else "Fila vazia.")
        return
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


def _comando_celular(a) -> None:
    from app.movel import acesso, certificado
    if a.comando == "definir-pin":
        import getpass
        pin = a.pin or getpass.getpass("PIN (4 a 8 dígitos): ")
        if a.pin is None and getpass.getpass("Repita o PIN: ") != pin:
            raise SystemExit("Os PINs não conferem.")
        try:  # com a ferramenta aberta o banco está travado: o PIN é definido assim mesmo, sem esta conferência
            con = conectar()
            if not con.execute("SELECT 1 FROM dim_colaborador WHERE matricula = ? AND colaborador_sk > 0",
                               [a.matricula.strip()]).fetchone():
                print("Aviso: matrícula ainda não cadastrada (cad_colaborador); os envios serão recusados até o cadastro.")
            con.close()
        except Exception:  # noqa: BLE001
            pass
        acesso.definir_pin(a.matricula, pin)
        print(f"PIN definido para {a.matricula.strip()}.")
    elif a.comando == "remover-pin":
        print("Acesso revogado." if acesso.remover(a.matricula.strip()) else "Matrícula sem PIN.")
    else:
        ips = certificado.gerar_servidor()
        print("Certificado do servidor gerado para: " + ", ".join(ips) + ". Os celulares não precisam reinstalar a CA.")


if __name__ == "__main__":
    main()
