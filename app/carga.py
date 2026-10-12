"""Registro de cargas na camada bruta, com idempotência, e disparo da reconstrução.

Regras (Etapa 5, §0):
- Conteúdo idêntico a uma carga já aceita (mesmo hash de conteúdo, independe de formato e ordem) → DUPLICADA.
- Linha com chave já vista e mesmo hash → REPETIDA (ignorada); chave com hash diferente → CORRECAO.
- Política tudo ou nada: uma linha inválida recusa o arquivo; o bruto guarda tudo para auditoria.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

import duckdb
import pandas as pd

from app import transform
from app.config import EMPRESA_PADRAO
from app.validacao import ResultadoValidacao, layout, validar


@dataclass
class ResultadoCarga:
    carga_id: int
    status: str
    n_linhas: int
    n_novas: int
    n_correcoes: int
    n_repetidas: int
    validacao: ResultadoValidacao

    @property
    def mensagem(self) -> str:
        if self.status == "DUPLICADA":
            return "Conteúdo idêntico a uma carga já aceita. Nada foi alterado."
        if self.status == "RECUSADA":
            return f"Carga recusada: {self.validacao.n_erros} erro(s). Nada chegou ao modelo; o bruto guardou o arquivo."
        return (f"Carga aceita: {self.n_novas} nova(s), {self.n_correcoes} correção(ões), "
                f"{self.n_repetidas} repetida(s) ignorada(s).")


def pre_validar(con, nome_layout: str, df: pd.DataFrame) -> ResultadoValidacao:
    """Validação sem gravar nada — para a tela mostrar os erros antes de confirmar."""
    return validar(df, nome_layout, transform.cadastros(con))


def registrar(con: duckdb.DuckDBPyConnection, nome_layout: str, df: pd.DataFrame, *, usuario: str,
              fonte: str = "UPLOAD", nome_arquivo: str | None = None, sintetico: bool = False,
              empresa: str = EMPRESA_PADRAO) -> ResultadoCarga:
    if not usuario or not usuario.strip():
        raise ValueError("usuário é obrigatório para gravar no bruto")
    spec = layout(nome_layout)
    if not spec.get("implementado"):
        raise ValueError(f"layout {nome_layout} ainda não implementado")

    res = validar(df, nome_layout, transform.cadastros(con))
    if res.valido:
        hash_conteudo = hashlib.md5("".join(sorted(l.hash_linha for l in res.linhas)).encode()).hexdigest()
    else:
        hash_conteudo = hashlib.md5(json.dumps([l.origem for l in res.linhas], sort_keys=True).encode()).hexdigest()

    carga_id = con.execute("SELECT nextval('seq_carga')").fetchone()[0]
    agora = datetime.now()
    n_novas = n_correcoes = n_repetidas = 0
    status_linhas: list[str] = []

    if res.valido:
        ja = con.execute(
            "SELECT count(*) FROM bruto_carga WHERE empresa = ? AND layout = ? AND status = 'ACEITA' AND hash_conteudo = ?",
            [empresa, nome_layout, hash_conteudo]).fetchone()[0]
        if ja:
            status = "DUPLICADA"
        else:
            status = "ACEITA"
            if "snapshot" in spec:  # fotografia substitui a anterior por inteiro: toda linha é nova
                atuais = {}
            else:
                atuais = dict(con.execute(
                    """
                    SELECT chave_negocio, arg_max(hash_linha, carga_id * 1000000 + num_linha)
                    FROM bruto_linha JOIN bruto_carga USING (carga_id)
                    WHERE empresa = ? AND layout = ? AND bruto_carga.status = 'ACEITA'
                      AND bruto_linha.status IN ('NOVA', 'CORRECAO')
                    GROUP BY chave_negocio
                    """, [empresa, nome_layout]).fetchall())
            for l in res.linhas:
                if l.chave not in atuais:
                    status_linhas.append("NOVA"); n_novas += 1
                elif atuais[l.chave] == l.hash_linha:
                    status_linhas.append("REPETIDA"); n_repetidas += 1
                else:
                    status_linhas.append("CORRECAO"); n_correcoes += 1
    else:
        status = "RECUSADA"
        status_linhas = ["ERRO" if l.erros else "VALIDA_NAO_CARREGADA" for l in res.linhas]

    con.execute("BEGIN")
    try:
        con.execute(
            "INSERT INTO bruto_carga VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [carga_id, empresa, nome_layout, fonte, nome_arquivo, hash_conteudo, usuario.strip(), agora, sintetico,
             status, len(res.linhas), n_novas, n_correcoes, n_repetidas, res.n_erros])
        if status != "DUPLICADA":
            registros = [
                (carga_id, l.num_linha, json.dumps(l.origem, ensure_ascii=False),
                 json.dumps(l.tipada, default=str, ensure_ascii=False) if l.tipada else None,
                 l.chave, l.hash_linha, st, "; ".join(l.erros) or None)
                for l, st in zip(res.linhas, status_linhas)]
            if registros:
                con.executemany("INSERT INTO bruto_linha VALUES (?,?,?,?,?,?,?,?)", registros)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise

    if status == "ACEITA" and (n_novas or n_correcoes):
        transform.reconstruir(con, empresa)
    return ResultadoCarga(carga_id, status, len(res.linhas), n_novas, n_correcoes, n_repetidas, res)


def garantir_modelo(con) -> None:
    """Cria o modelo dimensional se ainda não existe (banco novo)."""
    existe = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'fato_movimento_estoque'").fetchone()[0]
    if not existe:
        transform.reconstruir(con)
