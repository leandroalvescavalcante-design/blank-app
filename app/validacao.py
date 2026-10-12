"""Validação poka-yoke das entradas, guiada por entrada/layouts.yaml.

Mesma validação para upload e formulário. Nenhum campo depende de julgamento:
tipo, faixa, lista fechada e referência a cadastro são checados linha a linha.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache

import pandas as pd
import yaml

from app.config import ARQ_LAYOUTS

RE_DATA = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?: 00:00:00)?$")
RE_INSTANTE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?$")
RE_HORA = re.compile(r"^(\d{2}):(\d{2})(?::\d{2})?$")


@lru_cache(maxsize=1)
def especificacao() -> dict:
    return yaml.safe_load(ARQ_LAYOUTS.read_text(encoding="utf-8"))


def layout(nome: str) -> dict:
    return especificacao()["layouts"][nome]


def modelo_csv(nome: str) -> bytes:
    """Arquivo-modelo vazio do layout (cabeçalho apenas), separador ';'."""
    return (";".join(layout(nome)["campos"].keys()) + "\n").encode("utf-8")


def ler_arquivo(conteudo: bytes, nome_arquivo: str) -> pd.DataFrame:
    """Lê CSV (';' ou ',') ou XLSX, tudo como texto: a tipagem é da validação, não do leitor."""
    if nome_arquivo.lower().endswith((".xlsx", ".xlsm")):
        df = pd.read_excel(io.BytesIO(conteudo), dtype=str, keep_default_na=False)
    else:
        texto = conteudo.decode("utf-8-sig")
        primeira = texto.splitlines()[0] if texto else ""
        sep = ";" if primeira.count(";") >= primeira.count(",") else ","
        df = pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, keep_default_na=False)
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


@dataclass
class LinhaValidada:
    num_linha: int
    origem: dict
    tipada: dict | None = None
    chave: str | None = None
    hash_linha: str | None = None
    erros: list[str] = field(default_factory=list)


@dataclass
class ResultadoValidacao:
    layout: str
    linhas: list[LinhaValidada]
    erros_arquivo: list[str]

    @property
    def n_erros(self) -> int:
        return len(self.erros_arquivo) + sum(1 for l in self.linhas if l.erros)

    @property
    def valido(self) -> bool:
        return self.n_erros == 0 and len(self.linhas) > 0

    def tabela_erros(self) -> pd.DataFrame:
        linhas = [{"linha": 0, "erro": e} for e in self.erros_arquivo]
        linhas += [{"linha": l.num_linha, "erro": e} for l in self.linhas for e in l.erros]
        return pd.DataFrame(linhas, columns=["linha", "erro"])


def _vazio(x) -> bool:
    return x is None or (isinstance(x, str) and x.strip() == "")


def _converter(valor: str, spec: dict, nome: str, listas: dict):
    """Converte texto → tipo do campo. Retorna (valor, erro)."""
    texto = "" if valor is None else str(valor).strip()
    if texto == "":
        return (None, f"{nome}: obrigatório") if spec.get("obrigatorio") else (None, None)
    tipo = spec["tipo"]
    try:
        if tipo == "texto":
            v = texto
            if "max_len" in spec and len(v) > spec["max_len"]:
                return None, f"{nome}: mais de {spec['max_len']} caracteres"
        elif tipo == "sim_nao":
            v = texto.upper()
            if v not in ("S", "N"):
                return None, f"{nome}: use S ou N"
        elif tipo == "inteiro":
            f = float(texto.replace(",", "."))
            if f != int(f):
                return None, f"{nome}: deve ser inteiro"
            v = int(f)
        elif tipo == "decimal":
            if "," in texto and "." in texto:
                return None, f"{nome}: use só um separador decimal, sem separador de milhar"
            v = float(texto.replace(",", "."))
        elif tipo == "data":
            m = RE_DATA.match(texto)
            if not m:
                return None, f"{nome}: data deve ser AAAA-MM-DD"
            v = date(int(m[1]), int(m[2]), int(m[3]))
        elif tipo == "instante":
            m = RE_INSTANTE.match(texto)
            if not m:
                return None, f"{nome}: instante deve ser AAAA-MM-DD HH:MM[:SS]"
            v = datetime(int(m[1]), int(m[2]), int(m[3]), int(m[4]), int(m[5]), int(m[6] or 0))
        elif tipo == "hora":
            m = RE_HORA.match(texto)
            if not m or int(m[1]) > 23 or int(m[2]) > 59:
                return None, f"{nome}: hora deve ser HH:MM"
            v = f"{m[1]}:{m[2]}"
        else:
            return None, f"{nome}: tipo de campo desconhecido '{tipo}'"
    except ValueError:
        return None, f"{nome}: valor '{texto}' não é {tipo}"

    if "min" in spec and v < spec["min"]:
        return None, f"{nome}: {v} abaixo do mínimo {spec['min']}"
    if "max" in spec and v > spec["max"]:
        return None, f"{nome}: {v} acima do máximo {spec['max']}"
    if "lista" in spec:
        permitidos = listas[spec["lista"]]
        if v not in permitidos:
            return None, f"{nome}: '{v}' fora da lista ({', '.join(map(str, permitidos))})"
    return v, None


def hash_linha(tipada: dict) -> str:
    return hashlib.md5(json.dumps(tipada, sort_keys=True, default=str).encode()).hexdigest()


def chave_negocio(tipada: dict, campos_chave: list[str]) -> str:
    return "|".join("" if tipada.get(c) is None else str(tipada[c]) for c in campos_chave)


def validar(df: pd.DataFrame, nome_layout: str, refs: dict[str, dict[str, dict]]) -> ResultadoValidacao:
    """refs: cadastro → {código: atributos}. Usado para referência e para regras dependentes de cadastro."""
    spec_total = especificacao()
    spec = spec_total["layouts"][nome_layout]
    campos = spec["campos"]
    listas = dict(spec_total["listas"])
    listas["tipos_movimento"] = list(spec_total["tipos_movimento"].keys())
    sinais = {k: v["sinal"] for k, v in spec_total["tipos_movimento"].items()}

    erros_arquivo = []
    faltantes = [c for c in campos if c not in df.columns and campos[c].get("obrigatorio")]
    extras = [c for c in df.columns if c not in campos]
    if faltantes:
        erros_arquivo.append(f"colunas obrigatórias ausentes: {', '.join(faltantes)}")
    if extras:
        erros_arquivo.append(f"colunas fora do layout (layout errado?): {', '.join(extras)}")
    if df.empty:
        erros_arquivo.append("arquivo sem linhas")
    if erros_arquivo:
        return ResultadoValidacao(nome_layout, [], erros_arquivo)

    linhas: list[LinhaValidada] = []
    for i, registro in enumerate(df.to_dict(orient="records"), start=2):  # linha 1 = cabeçalho
        origem = {c: ("" if registro.get(c) is None else str(registro.get(c))) for c in campos}
        lv = LinhaValidada(num_linha=i, origem=origem)
        tipada = {}
        for nome, cspec in campos.items():
            v, erro = _converter(origem.get(nome, ""), cspec, nome, listas)
            if erro:
                lv.erros.append(erro)
            tipada[nome] = v
            ref = cspec.get("ref")
            if ref and v is not None and v not in refs.get(ref["cadastro"], {}):
                if ref.get("ausente", "rejeitar") == "rejeitar":
                    lv.erros.append(f"{nome}: '{v}' não existe no cadastro {ref['cadastro']}")

        if not lv.erros:
            lv.erros.extend(_regras_de_cadastro(nome_layout, tipada, refs))
        if not lv.erros:
            ns = dict(tipada, vazio=_vazio, sinal_tipo=lambda t: sinais[t])
            for regra in spec.get("regras", []):
                try:
                    if not eval(regra["expr"], {"__builtins__": {}}, ns):  # expressões vêm do YAML versionado
                        lv.erros.append(regra["msg"])
                except Exception as exc:  # noqa: BLE001 — regra não avaliável é erro da linha
                    lv.erros.append(f"regra não avaliável ({regra['msg']}): {exc}")

        if not lv.erros:
            lv.tipada = tipada
            lv.chave = chave_negocio(tipada, spec["chave"])
            lv.hash_linha = hash_linha(tipada)
        linhas.append(lv)

    vistos: dict[str, int] = {}
    for lv in linhas:
        if lv.chave is None:
            continue
        if lv.chave in vistos:
            lv.erros.append(f"chave de negócio repetida no arquivo (igual à linha {vistos[lv.chave]})")
        else:
            vistos[lv.chave] = lv.num_linha

    if "snapshot" in spec:
        por = spec["snapshot"]["por"]
        grupos = {tuple(l.tipada[c] for c in por) for l in linhas if l.tipada}
        if len(grupos) > 1:
            erros_arquivo.append(f"fotografia deve ter um único {' × '.join(por)}; o arquivo tem {len(grupos)}")

    return ResultadoValidacao(nome_layout, linhas, erros_arquivo)


def _regras_de_cadastro(nome_layout: str, t: dict, refs: dict) -> list[str]:
    """Regras que dependem de atributo de cadastro (não expressáveis só com a linha)."""
    erros = []
    if "sku" in t and "lote" in t and nome_layout not in ("cad_lote",):
        sku = refs.get("cad_sku", {}).get(t["sku"])
        if sku is not None:  # SKU inferido: sem cadastro, não há como exigir
            if sku.get("controla_lote") == "S" and _vazio(t["lote"]):
                erros.append(f"lote: obrigatório para o SKU {t['sku']} (controla lote)")
            if sku.get("controla_lote") == "N" and not _vazio(t["lote"]):
                erros.append(f"lote: SKU {t['sku']} não controla lote; deixe vazio")
    if nome_layout == "saldo_estoque":
        local = refs.get("cad_local", {}).get(t.get("endereco"))
        if local is not None and local.get("site") != t.get("site"):
            erros.append(f"endereco: {t['endereco']} pertence ao site {local.get('site')}, não a {t['site']}")
    if nome_layout == "investigacao_divergencia":
        motivo = refs.get("cad_motivo", {}).get(t.get("motivo"))
        if motivo is not None and motivo.get("processo") != "DIVERGENCIA":
            erros.append("motivo: use um motivo do processo DIVERGENCIA")
    return erros
