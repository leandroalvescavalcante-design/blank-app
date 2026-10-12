"""Servidor do app do celular. Rode: python -m app.movel.servidor

- HTTPS na porta 8443: o app (arquivos de web/) e a API, sempre com login (matrícula + PIN).
- HTTP na porta 8080: só a página de instalação do certificado da rede local (ca.crt).
Não abre o banco: lê referencias.json e grava cada envio em fila/ (ver integracao.py).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from app.movel import acesso, caminhos

PORTA_HTTPS = int(os.environ.get("GESTAO_PORTA_CELULAR", "8443"))
PORTA_HTTP = int(os.environ.get("GESTAO_PORTA_CERTIFICADO", "8080"))
MAX_CORPO = 1_000_000
MAX_ITENS = 200
RE_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
CAMPOS = {
    "contagem": {"numero_contagem", "recontagem_de", "endereco", "sku", "lote", "qtd_contada",
                 "instante_congelamento", "instante_contagem"},
    "investigacao": {"numero_contagem", "endereco", "sku", "lote", "motivo"},
}


def _referencias() -> dict:
    p = caminhos.referencias()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _funcao(matricula: str, ref: dict | None = None) -> str | None:
    ref = ref if ref is not None else _referencias()
    return next((c["funcao"] for c in ref.get("colaboradores", []) if c["matricula"] == matricula), None)


def _sessao(req: Request) -> str | None:
    cab = req.headers.get("authorization", "")
    return acesso.validar_token(cab[7:] if cab.lower().startswith("bearer ") else None)


async def _json(req: Request):
    if int(req.headers.get("content-length") or 0) > MAX_CORPO:
        return None
    try:
        return json.loads(await req.body())
    except ValueError:
        return None


async def login(req: Request):
    corpo = await _json(req) or {}
    matricula = str(corpo.get("matricula", "")).strip()
    if acesso.bloqueada(matricula):
        return JSONResponse({"erro": "Muitas tentativas. Aguarde 5 minutos."}, status_code=429)
    token = acesso.entrar(matricula, str(corpo.get("pin", "")))
    if token is None:
        return JSONResponse({"erro": "Matrícula ou PIN incorretos."}, status_code=401)
    return JSONResponse({"token": token, "matricula": matricula, "funcao": _funcao(matricula)})


async def hora(req: Request):
    return JSONResponse({"agora": datetime.now().isoformat(timespec="seconds")})


async def referencias(req: Request):
    m = _sessao(req)
    if not m:
        return JSONResponse({"erro": "sessão inválida"}, status_code=401)
    ref = _referencias()
    if not ref:
        return JSONResponse({"erro": "A ferramenta no computador ainda não publicou os dados. Abra-a e aguarde."},
                            status_code=503)
    funcao = _funcao(m, ref)
    if funcao != "SUPERVISOR":
        # contagem cega: quem conta não recebe a diferença nem as ações (o K05 traz a quantidade do lote)
        ref = dict(ref, acoes=[], divergencias=[{k: v for k, v in d.items() if k != "diferenca"}
                                                for d in ref["divergencias"]])
    return JSONResponse(dict(ref, funcao=funcao, matricula=m, hora_servidor=datetime.now().isoformat(timespec="seconds")))


async def enviar(req: Request):
    m = _sessao(req)
    if not m:
        return JSONResponse({"erro": "sessão inválida"}, status_code=401)
    corpo = await _json(req)
    itens = corpo.get("itens") if isinstance(corpo, dict) else None
    if not isinstance(itens, list) or len(itens) > MAX_ITENS:
        return JSONResponse({"erro": "envio inválido"}, status_code=400)
    funcao = _funcao(m)
    recebidos, recusados = [], []
    for it in itens:
        if not isinstance(it, dict):
            continue
        idc, tipo, dados = str(it.get("id_cliente", "")), it.get("tipo"), it.get("dados")
        if not RE_ID.match(idc) or tipo not in CAMPOS or not isinstance(dados, dict):
            recusados.append({"id_cliente": idc, "erro": "item malformado"})
            continue
        if tipo == "investigacao" and funcao != "SUPERVISOR":
            recusados.append({"id_cliente": idc, "erro": "investigação é só para supervisor"})
            continue
        destino = caminhos.fila() / f"{idc}.json"
        ja = destino.exists() or (caminhos.resultados() / f"{idc}.json").exists() \
            or (caminhos.raiz() / "processados" / f"{idc}.json").exists()
        if not ja:  # idempotente: reenviar o mesmo item não duplica
            limpo = {k: dados[k] for k in CAMPOS[tipo] if k in dados}
            tmp = destino.with_suffix(".tmp")
            tmp.write_text(json.dumps({"id_cliente": idc, "tipo": tipo, "matricula": m, "dados": limpo,
                                       "criado_no_celular": it.get("criado_em"),
                                       "recebido_em": datetime.now().isoformat(timespec="seconds")},
                                      ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, destino)
        recebidos.append(idc)
    return JSONResponse({"recebidos": recebidos, "recusados": recusados})


async def status(req: Request):
    if not _sessao(req):
        return JSONResponse({"erro": "sessão inválida"}, status_code=401)
    ids = [i for i in req.query_params.get("ids", "").split(",") if RE_ID.match(i)][:MAX_ITENS]
    saida = {}
    for i in ids:
        p = caminhos.resultados() / f"{i}.json"
        saida[i] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return JSONResponse(saida)


def app_https() -> Starlette:
    return Starlette(routes=[
        Route("/api/login", login, methods=["POST"]),
        Route("/api/hora", hora),
        Route("/api/referencias", referencias),
        Route("/api/enviar", enviar, methods=["POST"]),
        Route("/api/status", status),
        Mount("/", StaticFiles(directory=caminhos.WEB, html=True)),
    ])


# ----------------------------------------------------------------------------- página do certificado (HTTP)

PAGINA_CA = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Instalar certificado</title>
<style>body{font-family:system-ui,sans-serif;margin:24px;line-height:1.5;color:#15181B;background:#EDEFF1}
a.b{display:block;background:#1A1E22;color:#fff;padding:16px;border-radius:8px;text-align:center;text-decoration:none;margin:16px 0}
li{margin:8px 0}</style></head><body>
<h1>Gestão Industrial no celular</h1>
<p>Faça isto <b>uma vez</b> em cada celular.</p>
<a class="b" href="/ca.crt">1. Baixar o certificado da rede</a>
<ol><li>Abra <b>Configurações → Segurança → Mais configurações → Instalar certificado → Certificado de CA</b>
(o caminho muda um pouco conforme o fabricante; procure por "certificado CA").</li>
<li>Escolha o arquivo <b>ca.crt</b> baixado e confirme.</li>
<li>Abra no Chrome: <b>https://{host}:{porta}</b></li>
<li>No menu do Chrome, toque em <b>Instalar app</b> (ou "Adicionar à tela inicial").</li></ol>
</body></html>"""


async def pagina_ca(req: Request):
    host = req.url.hostname or "localhost"
    return HTMLResponse(PAGINA_CA.replace("{host}", host).replace("{porta}", str(PORTA_HTTPS)))


async def baixar_ca(req: Request):
    return FileResponse(caminhos.tls() / "ca.crt", media_type="application/x-x509-ca-cert", filename="ca.crt")


async def para_https(req: Request):
    return RedirectResponse(f"https://{req.url.hostname}:{PORTA_HTTPS}/")


def app_http() -> Starlette:
    return Starlette(routes=[Route("/", pagina_ca), Route("/ca.crt", baixar_ca), Route("/app", para_https)])


def main() -> None:
    import uvicorn

    from app.movel import certificado
    certificado.garantir_ca()
    ips = certificado.garantir_servidor()
    tls = caminhos.tls()
    print("Servidor do celular ativo. No celular, na mesma rede Wi-Fi:")
    for ip in ips:
        if ip != "127.0.0.1":
            print(f"  1ª vez (certificado): http://{ip}:{PORTA_HTTP}    app: https://{ip}:{PORTA_HTTPS}")
    s1 = uvicorn.Server(uvicorn.Config(app_https(), host="0.0.0.0", port=PORTA_HTTPS, log_level="warning",
                                       ssl_certfile=str(tls / "servidor.crt"), ssl_keyfile=str(tls / "servidor.key")))
    s2 = uvicorn.Server(uvicorn.Config(app_http(), host="0.0.0.0", port=PORTA_HTTP, log_level="warning"))

    async def ambos():
        await asyncio.gather(s1.serve(), s2.serve())

    asyncio.run(ambos())


if __name__ == "__main__":
    main()
