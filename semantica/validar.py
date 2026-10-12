"""Valida a consistência da camada semântica (semantica/metricas.yaml).

Checa mecânica, não parâmetro: campos obrigatórios, listas fechadas,
referências a medidas/funções existentes e cobertura das decisões da onda 1.
Uso: python semantica/validar.py
"""
import re
import sys
from pathlib import Path

import yaml

ARQUIVO = Path(__file__).with_name("metricas.yaml")

CAMPOS_OBRIGATORIOS = ["nome", "classe", "formula", "usa", "unidade", "data_padrao",
                       "dimensoes", "dono", "decisoes", "direcao"]
CLASSES = {"decisao", "diagnostico", "integridade"}
DIRECOES = {"maior_melhor", "menor_melhor", "alvo_zero", "gatilho"}
AGREGACOES = {"soma", "ultimo_no_periodo", "nenhuma"}
DIMENSOES = {"data", "sku", "lote", "local", "site", "cliente", "parceiro", "recurso", "turno",
             "veiculo", "colaborador", "motivo", "procedencia"}
DECISOES_ONDA_1 = {"D01", "D03", "D04", "D05", "D06", "D07", "D08", "D14", "D15", "D18"}
# Referências a colunas de fatos derivados ou a outras métricas são permitidas.
REFERENCIA_EXTERNA = re.compile(r"^(F\d+[a-z]?\.\w+|K\d+[a-z]?)$")


def validar(spec):
    erros = []
    medidas = spec.get("medidas_base", {})
    funcoes = spec.get("funcoes", {})
    metricas = spec.get("metricas", {})

    for nome, m in medidas.items():
        for campo in ("fato", "expr", "agregacao", "unidade"):
            if campo not in m:
                erros.append(f"medida {nome}: falta '{campo}'")
        if m.get("agregacao") not in AGREGACOES:
            erros.append(f"medida {nome}: agregação inválida '{m.get('agregacao')}'")

    cobertas = set()
    for kid, k in metricas.items():
        for campo in CAMPOS_OBRIGATORIOS:
            if campo not in k:
                erros.append(f"{kid}: falta '{campo}'")
        if k.get("classe") not in CLASSES:
            erros.append(f"{kid}: classe inválida '{k.get('classe')}'")
        if k.get("direcao") not in DIRECOES:
            erros.append(f"{kid}: direção inválida '{k.get('direcao')}'")
        if k.get("direcao") == "gatilho" and k.get("classe") == "decisao" and "gatilho" not in k \
                and "nulo_quando" not in k:
            erros.append(f"{kid}: métrica de decisão com direção 'gatilho' sem regra de gatilho")
        if k.get("classe") == "diagnostico" and k.get("meta") not in (None, "proibida"):
            erros.append(f"{kid}: diagnóstico não pode ter meta")
        for d in k.get("dimensoes", []):
            if d not in DIMENSOES:
                erros.append(f"{kid}: dimensão desconhecida '{d}'")
        for ref in k.get("usa", []):
            if ref not in medidas and ref not in funcoes and not REFERENCIA_EXTERNA.match(ref):
                erros.append(f"{kid}: referência inexistente '{ref}'")
            if REFERENCIA_EXTERNA.match(ref) and ref.startswith("K") and ref not in metricas:
                erros.append(f"{kid}: métrica referenciada inexistente '{ref}'")
        cobertas.update(k.get("decisoes", []))

    for d in sorted(DECISOES_ONDA_1 - cobertas):
        erros.append(f"decisão {d} da onda 1 sem métrica")
    return erros


def main():
    spec = yaml.safe_load(ARQUIVO.read_text(encoding="utf-8"))
    erros = validar(spec)
    if erros:
        print("\n".join(erros))
        sys.exit(1)
    print(f"OK: {len(spec['metricas'])} métricas, {len(spec['medidas_base'])} medidas base, "
          f"{len(spec['funcoes'])} funções; decisões da onda 1 cobertas.")


if __name__ == "__main__":
    main()
