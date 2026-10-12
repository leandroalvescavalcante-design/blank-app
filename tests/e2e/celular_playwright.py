"""Ponta a ponta num Pixel 7 emulado (manual, fora do pytest): offline -> fila -> Wi-Fi -> computador grava.

Uso: suba `python -m app.movel.servidor` com GESTAO_PORTA_CELULAR=18443 e GESTAO_DB apontando para um banco
com o cenário demo e PIN 4826 para M001; confie a ca.crt no NSS de E2E_HOME; rode com a pasta do banco como argumento.
"""
import json, subprocess, sys, os
from playwright.sync_api import sync_playwright
S = sys.argv[1]; BASE = "https://localhost:18443"
shots = os.path.join(S, "shots"); os.makedirs(shots, exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM"), env={**os.environ, "HOME": os.environ.get("E2E_HOME", os.environ["HOME"])})
    ctx = b.new_context(**p.devices["Pixel 7"], locale="pt-BR")
    pg = ctx.new_page()
    pg.goto(BASE + "/")
    pg.fill("#mat", "M001"); pg.fill("#pin", "4826"); pg.click("#entrar")
    pg.wait_for_selector("#b-contagem:not([disabled])")
    pg.wait_for_function("document.querySelector('#rede').textContent.startsWith('online')")
    pg.screenshot(path=f"{shots}/1_inicio_online.png")
    assert pg.locator("#b-acoes").count() == 0  # inventariante não vê ações
    pg.evaluate("navigator.serviceWorker.ready.then(() => true)")
    pg.reload(); pg.wait_for_selector("#b-contagem")  # SW controla a página
    # ---- sem Wi-Fi
    ctx.set_offline(True)
    pg.reload(); pg.wait_for_selector("#b-contagem")   # abre do cache, sem rede
    pg.click("#b-contagem")
    pg.fill("#end", "A-01-01"); pg.dispatch_event("#end", "change")
    pg.fill("#sku", "7890000000017"); pg.dispatch_event("#sku", "change")   # código de barras
    pg.select_option("#lote", "L1001")
    pg.screenshot(path=f"{shots}/2_posicao.png")
    pg.click("#iniciar")
    pg.fill("#qtd", "1.500"); pg.click("#registrar")
    assert "inválida" in pg.inner_text("#aviso")     # poka-yoke do ponto de milhar
    pg.fill("#qtd", "230"); pg.click("#registrar")
    pg.wait_for_timeout(500)
    pg.click("#voltar")
    pg.wait_for_function("document.querySelector('#rede').textContent.includes('1 na fila')")
    pg.screenshot(path=f"{shots}/3_offline_fila.png")
    fila = json.loads(pg.evaluate("localStorage.getItem('coleta.fila')"))
    assert len(fila) == 1 and fila[0]["situacao"] == "PENDENTE", fila
    # ---- volta o Wi-Fi
    ctx.set_offline(False)
    pg.click("#b-sinc")
    pg.wait_for_function("JSON.parse(localStorage.getItem('coleta.fila'))[0].situacao === 'RECEBIDO'")
    # computador processa a fila (o vigia faz isso a cada 15 s com a ferramenta aberta)
    out = subprocess.run([sys.executable, "-m", "app.admin", "processar-celular"], capture_output=True, text=True,
                         env={**os.environ, "GESTAO_DB": os.path.join(S, "gestao.duckdb")})
    print(out.stdout, out.stderr)
    pg.click("#b-sinc")
    pg.wait_for_function("JSON.parse(localStorage.getItem('coleta.fila'))[0].situacao === 'ACEITA'")
    pg.click("#b-envios"); pg.screenshot(path=f"{shots}/4_envios.png")
    txt = pg.inner_text("main"); print(txt)
    assert "230" in txt and "registrada" in txt
    pg.click("#voltar"); pg.click("#b-recontagem"); pg.screenshot(path=f"{shots}/5_recontagem.png")
    assert "-10" not in pg.inner_text("main")   # cega
    b.close()
print("E2E OK")
