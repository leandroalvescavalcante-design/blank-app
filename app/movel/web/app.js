/* Coleta no celular — funciona com e sem Wi-Fi.
 *
 * O celular só COLETA. Cada contagem/investigação vira um item na fila local (localStorage) com um id único;
 * quando há rede, a fila é enviada ao servidor (idempotente: reenviar não duplica) e o computador valida e grava
 * no bruto com a mesma validação das telas de sempre. O saldo do sistema NUNCA chega ao celular: ele registra só
 * o instante do congelamento, e o computador calcula o saldo congelado para aquele instante.
 */
"use strict";

const API_TIMEOUT_MS = 8000;
const SINCRONIZAR_A_CADA_MS = 30000;
const K = { sessao: "coleta.sessao", ref: "coleta.referencias", fila: "coleta.fila", desvio: "coleta.desvio_relogio" };

// ------------------------------------------------------------------ armazenamento local
function ler(chave, padrao) {
  try { const v = localStorage.getItem(chave); return v === null ? padrao : JSON.parse(v); }
  catch (e) { return padrao; }
}
function gravar(chave, valor) { localStorage.setItem(chave, JSON.stringify(valor)); }

const estado = {
  online: false,
  sincronizando: false,
  tarefa: null,          // contagem em andamento (posição congelada, aguardando a quantidade)
  camera: null,          // stream da câmera aberta
};

const sessao = () => ler(K.sessao, null);
const ref = () => ler(K.ref, null);
const fila = () => ler(K.fila, []);
const ehSupervisor = () => (sessao() || {}).funcao === "SUPERVISOR";

function sessaoValida() {
  const s = sessao();
  return !!(s && s.token && s.expira_em > Date.now());
}

// ------------------------------------------------------------------ relógio: instante no horário do computador
// Todo instante enviado usa o relógio do COMPUTADOR (desvio medido a cada contato), para o congelamento bater com
// os movimentos do ERP mesmo se o relógio do celular estiver errado ou em outro fuso.
function medirDesvio(horaServidor) {
  const servidor = new Date(horaServidor).getTime();   // ISO sem fuso = hora local do computador
  if (!isNaN(servidor)) gravar(K.desvio, servidor - Date.now());
}
function agoraServidor() {
  const d = new Date(Date.now() + ler(K.desvio, 0));
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
const compacto = (iso) => iso.replace(/[-T:]/g, "");

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40; b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// ------------------------------------------------------------------ utilidades de tela
const $ = (sel) => document.querySelector(sel);
function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
let avisoTimer;
function avisar(texto, erro = false) {
  const a = $("#aviso");
  a.textContent = texto; a.className = erro ? "erro" : ""; a.hidden = false;
  clearTimeout(avisoTimer); avisoTimer = setTimeout(() => { a.hidden = true; }, erro ? 6000 : 3500);
}
function dataHora(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? esc(iso) : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}
function atualizarSelo() {
  const s = $("#rede");
  const pend = filaDoUsuario().filter((i) => i.situacao === "PENDENTE").length;
  if (estado.sincronizando) { s.textContent = "sincronizando…"; s.className = "selo"; return; }
  s.textContent = estado.online ? (pend ? `online · ${pend} a enviar` : "online") : (pend ? `offline · ${pend} na fila` : "offline");
  s.className = "selo " + (estado.online ? "on" : "off");
}

// ------------------------------------------------------------------ API
async function api(caminho, opcoes = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), API_TIMEOUT_MS);
  const s = sessao();
  const cab = { "Content-Type": "application/json" };
  if (s && s.token) cab.Authorization = "Bearer " + s.token;
  try {
    const r = await fetch(caminho, { ...opcoes, headers: cab, signal: ctrl.signal, cache: "no-store" });
    let corpo = null;
    try { corpo = await r.json(); } catch (e) { /* corpo vazio */ }
    estado.online = true;
    return { ok: r.ok, status: r.status, corpo: corpo || {} };
  } catch (e) {
    estado.online = false;
    return { ok: false, status: 0, corpo: { erro: "Sem conexão com o computador." } };
  } finally {
    clearTimeout(t);
    atualizarSelo();
  }
}

// ------------------------------------------------------------------ fila e sincronização
function filaDoUsuario() {
  const s = sessao();
  return s ? fila().filter((i) => i.matricula === s.matricula) : [];
}

function enfileirar(tipo, dados, resumo) {
  const s = sessao();
  const f = fila();
  f.push({ id_cliente: uuid(), tipo, dados, resumo, matricula: s.matricula, criado_em: agoraServidor(),
           situacao: "PENDENTE", mensagem: "", erros: [] });
  gravar(K.fila, f);
  atualizarSelo();
}

function atualizarItens(alterar) {
  const f = fila();
  f.forEach(alterar);
  // guarda no máximo 300 itens já resolvidos, para não lotar o armazenamento do celular
  const abertos = f.filter((i) => i.situacao === "PENDENTE" || i.situacao === "RECEBIDO");
  const fechados = f.filter((i) => !(i.situacao === "PENDENTE" || i.situacao === "RECEBIDO")).slice(-300);
  gravar(K.fila, [...fechados, ...abertos].sort((a, b) => a.criado_em.localeCompare(b.criado_em)));
}

async function sincronizar(manual = false) {
  if (estado.sincronizando || !sessaoValida()) return;
  estado.sincronizando = true; atualizarSelo();
  let msg = null, erro = false;
  try {
    // 1) envia o que está pendente (lotes de até 200 itens)
    const pend = filaDoUsuario().filter((i) => i.situacao === "PENDENTE");
    for (let i = 0; i < pend.length; i += 200) {
      const lote = pend.slice(i, i + 200).map((x) => ({ id_cliente: x.id_cliente, tipo: x.tipo, dados: x.dados, criado_em: x.criado_em }));
      const r = await api("/api/enviar", { method: "POST", body: JSON.stringify({ itens: lote }) });
      if (r.status === 401) return sessaoExpirada();
      if (!r.ok) { if (manual) { msg = r.corpo.erro || "Falha ao enviar."; erro = true; } break; }
      const recebidos = new Set(r.corpo.recebidos || []);
      const recusados = Object.fromEntries((r.corpo.recusados || []).map((x) => [x.id_cliente, x.erro]));
      atualizarItens((it) => {
        if (recebidos.has(it.id_cliente)) it.situacao = "RECEBIDO";
        else if (recusados[it.id_cliente]) { it.situacao = "RECUSADA"; it.mensagem = recusados[it.id_cliente]; }
      });
    }
    // 2) busca o resultado do que o computador já processou
    const aguardando = filaDoUsuario().filter((i) => i.situacao === "RECEBIDO").map((i) => i.id_cliente);
    for (let i = 0; i < aguardando.length; i += 200) {
      const r = await api("/api/status?ids=" + aguardando.slice(i, i + 200).join(","));
      if (r.status === 401) return sessaoExpirada();
      if (!r.ok) break;
      atualizarItens((it) => {
        const res = r.corpo[it.id_cliente];
        if (res) { it.situacao = res.status; it.mensagem = res.mensagem; it.erros = res.erros || []; }
      });
    }
    // 3) atualiza endereços, SKUs, lotes, divergências e ações
    const r = await api("/api/referencias");
    if (r.status === 401) return sessaoExpirada();
    if (r.ok) {
      gravar(K.ref, r.corpo);
      medirDesvio(r.corpo.hora_servidor);
      const s = sessao(); s.funcao = r.corpo.funcao; gravar(K.sessao, s);
      if (manual) msg = "Sincronizado.";
    } else if (manual) {
      msg = r.corpo.erro || "Sem conexão com o computador. Os dados continuam salvos no celular."; erro = true;
    }
  } finally {
    estado.sincronizando = false; atualizarSelo();
  }
  if (msg) avisar(msg, erro);
  // só redesenha telas de consulta: nunca apaga o que a pessoa está digitando
  if (["inicio", "envios", "acoes", "recontagem"].includes(telaAtual)) desenhar();
}

function sessaoExpirada() {
  const s = sessao();
  gravar(K.sessao, s ? { matricula: s.matricula } : null);   // a fila fica guardada para quando entrar de novo
  estado.sincronizando = false;
  avisar("Sessão expirada. Entre de novo; nada do que está no celular foi perdido.", true);
  ir("login");
}

// ------------------------------------------------------------------ navegação
const telas = {};
let telaAtual = "inicio";
function ir(nome) {
  if (estado.camera) pararCamera();
  if (nome !== "contar") estado.tarefa = null;
  telaAtual = nome;
  if (location.hash !== "#" + nome) history.pushState(null, "", "#" + nome);
  desenhar();
}
window.addEventListener("popstate", () => {
  if (estado.camera) pararCamera();
  telaAtual = (location.hash || "#inicio").slice(1);
  if (telaAtual !== "contar") estado.tarefa = null;
  desenhar();
});

function desenhar() {
  if (!sessaoValida()) telaAtual = "login";
  else if (telaAtual === "login" || !telas[telaAtual]) telaAtual = "inicio";
  if (telaAtual === "contar" && !estado.tarefa) telaAtual = "contagem";
  const t = telas[telaAtual];
  $("#titulo").textContent = t.titulo;
  $("#voltar").hidden = telaAtual === "login" || telaAtual === "inicio";
  $("#tela").innerHTML = t.html();
  if (t.ligar) t.ligar();
  atualizarSelo();
  window.scrollTo(0, 0);
}
$("#voltar").addEventListener("click", () => ir("inicio"));

// ------------------------------------------------------------------ tela: login
telas.login = {
  titulo: "Entrar",
  html: () => {
    const m = (sessao() || {}).matricula || "";
    return `<div class="cartao">
      <p>Entre com a sua matrícula e o PIN entregue pelo administrador da ferramenta.</p>
      <label for="mat">Matrícula</label><input id="mat" autocomplete="username" autocapitalize="characters" value="${esc(m)}">
      <label for="pin">PIN</label><input id="pin" type="password" inputmode="numeric" autocomplete="current-password" maxlength="8">
      <button id="entrar">Entrar</button>
      <p><small>Precisa estar no Wi-Fi da empresa só para entrar. Depois, funciona sem rede por até 7 dias.</small></p>
    </div>`;
  },
  ligar: () => {
    const entrar = async () => {
      const matricula = $("#mat").value.trim(), pin = $("#pin").value;
      if (!matricula || !pin) return avisar("Informe matrícula e PIN.", true);
      $("#entrar").disabled = true;
      const r = await api("/api/login", { method: "POST", body: JSON.stringify({ matricula, pin }) });
      $("#entrar").disabled = false;
      if (!r.ok) return avisar(r.corpo.erro || "Não foi possível entrar.", true);
      gravar(K.sessao, { token: r.corpo.token, matricula: r.corpo.matricula, funcao: r.corpo.funcao,
                         expira_em: Date.now() + 7 * 24 * 3600 * 1000 - 60000 });
      ir("inicio");
      sincronizar();
    };
    $("#entrar").addEventListener("click", entrar);
    $("#pin").addEventListener("keydown", (e) => { if (e.key === "Enter") entrar(); });
  },
};

// ------------------------------------------------------------------ tela: início
function divergenciasAbertas() {
  // esconde as que já recontei/investiguei e ainda aguardam o computador
  const r = ref(); if (!r) return [];
  const feitas = new Set(filaDoUsuario().filter((i) => i.situacao === "PENDENTE" || i.situacao === "RECEBIDO")
    .map((i) => [i.dados.recontagem_de || i.dados.numero_contagem, i.dados.endereco, i.dados.sku, i.dados.lote || ""].join("|")));
  return (r.divergencias || []).filter((d) => !feitas.has([d.numero_contagem, d.endereco, d.sku, d.lote || ""].join("|")));
}

telas.inicio = {
  titulo: "Coleta",
  html: () => {
    const s = sessao(), r = ref(), itens = filaDoUsuario();
    const pend = itens.filter((i) => i.situacao === "PENDENTE").length;
    const recusadas = itens.filter((i) => i.situacao === "RECUSADA" || i.situacao === "ERRO").length;
    const outros = fila().filter((i) => i.matricula !== s.matricula && i.situacao === "PENDENTE").length;
    const div = divergenciasAbertas().length;
    let faixas = "";
    if (!r) faixas += `<div class="faixa erro">Ainda não há dados no celular. Conecte ao Wi-Fi da empresa e toque em Sincronizar.</div>`;
    else if (r.sintetico) faixas += `<div class="faixa">Dados de TREINAMENTO (fictícios).</div>`;
    if (recusadas) faixas += `<div class="faixa erro">${recusadas} envio(s) recusado(s) pelo computador. Veja em Meus envios.</div>`;
    if (outros) faixas += `<div class="faixa">${outros} item(ns) de outra matrícula aguardam aquela pessoa entrar neste celular.</div>`;
    return `${faixas}
    <div class="cartao">
      <div class="linha"><span class="rotulo">Matrícula</span><b>${esc(s.matricula)}${s.funcao ? " · " + esc(s.funcao.toLowerCase()) : ""}</b></div>
      <div class="linha"><span class="rotulo">Dados do computador de</span><span>${r ? dataHora(r.gerado_em) : "—"}</span></div>
      <div class="linha"><span class="rotulo">Na fila do celular</span><span class="numero">${pend}</span></div>
    </div>
    <div class="menu">
      <button id="b-contagem" ${r ? "" : "disabled"}>Nova contagem <span>›</span></button>
      <button id="b-recontagem" class="sec" ${r ? "" : "disabled"}>Recontagem de divergência <span class="cont">${div}</span></button>
      ${ehSupervisor() ? `<button id="b-investigacao" class="sec" ${r ? "" : "disabled"}>Investigar divergência <span class="cont">${div}</span></button>` : ""}
      ${ehSupervisor() ? `<button id="b-acoes" class="sec" ${r ? "" : "disabled"}>Ações do painel <span class="cont">${r ? (r.acoes || []).length : 0}</span></button>` : ""}
      <button id="b-envios" class="sec">Meus envios <span>›</span></button>
      <button id="b-sinc" class="acento">Sincronizar agora</button>
      <button id="b-sair" class="sec">Sair</button>
    </div>`;
  },
  ligar: () => {
    const b = (id, f) => { const e = $(id); if (e) e.addEventListener("click", f); };
    b("#b-contagem", () => ir("contagem"));
    b("#b-recontagem", () => ir("recontagem"));
    b("#b-investigacao", () => ir("investigacao"));
    b("#b-acoes", () => ir("acoes"));
    b("#b-envios", () => ir("envios"));
    b("#b-sinc", () => sincronizar(true));
    b("#b-sair", () => {
      const pend = filaDoUsuario().filter((i) => i.situacao === "PENDENTE").length;
      if (pend && !confirm(`Há ${pend} item(ns) seus ainda não enviados. Eles ficam guardados e serão enviados quando você entrar de novo. Sair?`)) return;
      gravar(K.sessao, { matricula: sessao().matricula });
      ir("login");
    });
  },
};

// ------------------------------------------------------------------ câmera (código de barras)
async function lerCodigo(alvo) {
  if (!("BarcodeDetector" in window) || !navigator.mediaDevices) {
    return avisar("Este celular não lê código pela câmera no navegador. Digite o código ou use o leitor do coletor.", true);
  }
  const caixa = $("#camera");
  caixa.innerHTML = `<video playsinline muted></video><button class="sec" id="cam-fechar">Fechar câmera</button>`;
  $("#cam-fechar").addEventListener("click", pararCamera);
  try {
    estado.camera = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
  } catch (e) {
    caixa.innerHTML = "";
    return avisar("Sem permissão para usar a câmera.", true);
  }
  const video = caixa.querySelector("video");
  video.srcObject = estado.camera;
  await video.play();
  const detector = new BarcodeDetector();
  const laco = async () => {
    if (!estado.camera) return;
    try {
      const achados = await detector.detect(video);
      if (achados.length) {
        alvo.value = achados[0].rawValue.trim();
        alvo.dispatchEvent(new Event("change"));
        if (navigator.vibrate) navigator.vibrate(80);
        return pararCamera();
      }
    } catch (e) { /* quadro ainda não pronto */ }
    setTimeout(laco, 200);
  };
  laco();
}
function pararCamera() {
  if (estado.camera) estado.camera.getTracks().forEach((t) => t.stop());
  estado.camera = null;
  const c = $("#camera"); if (c) c.innerHTML = "";
}

// ------------------------------------------------------------------ tela: nova contagem (escolha da posição)
function acharSku(leitura) {
  const v = leitura.trim().toUpperCase();
  return (ref().skus || []).find((s) => s.sku.toUpperCase() === v || (s.codigo_barras && String(s.codigo_barras).toUpperCase() === v));
}
function acharEndereco(leitura) {
  const v = leitura.trim().toUpperCase();
  return (ref().enderecos || []).find((e) => e.endereco.toUpperCase() === v);
}

telas.contagem = {
  titulo: "Nova contagem",
  html: () => `
    <div class="cartao">
      <label for="end">Endereço</label>
      <div class="campo-leitura"><input id="end" list="lista-end" autocapitalize="characters" placeholder="leia a etiqueta ou digite">
      <button class="sec" id="cam-end" aria-label="Ler etiqueta pela câmera">&#128247;</button></div>
      <datalist id="lista-end">${(ref().enderecos || []).map((e) => `<option value="${esc(e.endereco)}">`).join("")}</datalist>
      <label for="sku">SKU</label>
      <div class="campo-leitura"><input id="sku" autocapitalize="characters" placeholder="leia o código de barras ou digite">
      <button class="sec" id="cam-sku" aria-label="Ler código pela câmera">&#128247;</button></div>
      <div id="sku-desc"><small></small></div>
      <div id="bloco-lote" hidden>
        <label for="lote">Lote</label>
        <select id="lote"></select>
        <input id="lote-livre" placeholder="lote como impresso na embalagem" autocapitalize="characters" hidden>
      </div>
      <div id="camera"></div>
      <button id="iniciar" disabled>Iniciar contagem (congela o saldo)</button>
    </div>
    <p><small>O saldo do sistema é congelado no instante em que você toca em Iniciar e nunca aparece no celular.</small></p>`,
  ligar: () => {
    let sku = null;
    const validar = () => {
      const end = acharEndereco($("#end").value);
      let loteOk = true;
      if (sku && sku.controla_lote === "S") {
        loteOk = $("#lote").value === "__outro__" ? !!$("#lote-livre").value.trim() : !!$("#lote").value;
      }
      $("#iniciar").disabled = !(end && sku && loteOk);
    };
    let skuMostrado = null;
    $("#sku").addEventListener("change", () => {
      sku = acharSku($("#sku").value);
      if (sku && skuMostrado === sku.sku) return validar();   // mesmo SKU: não recria a lista (manteria o lote)
      skuMostrado = sku ? sku.sku : null;
      const desc = $("#sku-desc small");
      $("#bloco-lote").hidden = true;
      if (!$("#sku").value.trim()) { desc.textContent = ""; }
      else if (!sku) { desc.textContent = "Código não corresponde a nenhum SKU cadastrado."; desc.style.color = "var(--erro)"; }
      else {
        desc.textContent = `${sku.sku} · ${sku.descricao || ""} (${sku.unidade_base || "un"})`; desc.style.color = "";
        if (sku.controla_lote === "S") {
          const lotes = (ref().lotes || {})[sku.sku] || [];
          $("#lote").innerHTML = `<option value="">— escolha —</option>` +
            lotes.map((l) => `<option value="${esc(l.lote)}">${esc(l.lote)}${l.validade ? " · vence " + esc(l.validade) : ""}</option>`).join("") +
            `<option value="__outro__">O lote físico não está na lista</option>`;
          $("#lote-livre").hidden = true;
          $("#bloco-lote").hidden = false;
        }
      }
      validar();
    });
    $("#sku").addEventListener("input", () => { sku = null; skuMostrado = null; $("#iniciar").disabled = true; });
    $("#sku").addEventListener("blur", () => $("#sku").dispatchEvent(new Event("change")));
    $("#end").addEventListener("input", validar);
    $("#end").addEventListener("change", () => {
      const e = acharEndereco($("#end").value);
      if (e) $("#end").value = e.endereco;
      else if ($("#end").value.trim()) avisar("Endereço não cadastrado (ou em quarentena).", true);
      validar();
    });
    $("#lote").addEventListener("change", () => { $("#lote-livre").hidden = $("#lote").value !== "__outro__"; validar(); });
    $("#lote-livre").addEventListener("input", validar);
    $("#cam-end").addEventListener("click", () => lerCodigo($("#end")));
    $("#cam-sku").addEventListener("click", () => lerCodigo($("#sku")));
    $("#iniciar").addEventListener("click", () => {
      const end = acharEndereco($("#end").value);
      let lote = "";
      if (sku.controla_lote === "S") lote = $("#lote").value === "__outro__" ? $("#lote-livre").value.trim() : $("#lote").value;
      const instante = agoraServidor();
      const s = sessao();
      const sufixo = Math.random().toString(36).slice(2, 6).toUpperCase();
      estado.tarefa = { numero_contagem: `CEL-${s.matricula}-${compacto(instante)}-${sufixo}`.slice(0, 40),
                        recontagem_de: null, endereco: end.endereco, sku: sku.sku, lote, unidade: sku.unidade_base || "un",
                        descricao: sku.descricao || "", instante_congelamento: instante };
      ir("contar");
    });
  },
};

// ------------------------------------------------------------------ tela: informar a quantidade
// Poka-yoke: "1.500" é ambíguo (mil e quinhentos ou um e meio?) e é recusado; vírgula ou ponto só como decimal.
function lerQuantidade(valor) {
  const t = valor.trim();
  if (/^\d{1,3}([.,]\d{3}){2,}$/.test(t) || /^\d{1,3}\.\d{3}$/.test(t)) return null;
  const n = t.replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(n)) return null;
  return Number(n);
}
telas.contar = {
  titulo: "Contar",
  html: () => {
    const t = estado.tarefa;
    return `<div class="cartao posicao">
      <div class="rotulo">${t.recontagem_de ? "Recontagem de " + esc(t.recontagem_de) : "Contagem " + esc(t.numero_contagem)}</div>
      <div><b>${esc(t.endereco)}</b></div>
      <div><b>${esc(t.sku)}</b> ${esc(t.descricao)}</div>
      ${t.lote ? `<div>Lote <b>${esc(t.lote)}</b></div>` : ""}
      <div class="rotulo">Congelado em ${dataHora(t.instante_congelamento)}</div>
    </div>
    <div class="cartao">
      <label for="qtd">Quantidade contada (${esc(t.unidade)})</label>
      <input id="qtd" inputmode="decimal" autocomplete="off" placeholder="0">
      <button id="registrar">Registrar contagem</button>
      <button id="cancelar" class="sec">Cancelar</button>
    </div>`;
  },
  ligar: () => {
    $("#qtd").focus();
    $("#cancelar").addEventListener("click", () => ir("inicio"));
    $("#registrar").addEventListener("click", () => {
      const qtd = lerQuantidade($("#qtd").value);
      if (qtd === null) return avisar("Quantidade inválida. Use só números e, se precisar, vírgula para decimais (sem ponto de milhar).", true);
      const t = estado.tarefa;
      enfileirar("contagem", {
        numero_contagem: t.numero_contagem, recontagem_de: t.recontagem_de, endereco: t.endereco, sku: t.sku, lote: t.lote,
        qtd_contada: qtd, instante_congelamento: t.instante_congelamento, instante_contagem: agoraServidor(),
      }, `${t.recontagem_de ? "Recontagem" : "Contagem"} · ${t.endereco} · ${t.sku}${t.lote ? " " + t.lote : ""} · ${qtd} ${t.unidade}`);
      const era = t.recontagem_de ? "recontagem" : "contagem";
      estado.tarefa = null;
      avisar(estado.online ? "Contagem salva. Enviando…" : "Contagem salva no celular. Será enviada quando houver Wi-Fi.");
      ir(era);
      sincronizar();
    });
  },
};

// ------------------------------------------------------------------ tela: recontagem
telas.recontagem = {
  titulo: "Recontagem",
  html: () => {
    const lista = divergenciasAbertas();
    if (!lista.length) return `<div class="cartao vazio">Nenhuma divergência pendente de recontagem.</div>`;
    return `<p><small>Recontagem cega: a diferença não é mostrada a quem reconta.</small></p><div class="cartao">` +
      lista.map((d, i) => `<div class="item"><div class="t">${esc(d.endereco)} · ${esc(d.sku)}${d.lote ? " · lote " + esc(d.lote) : ""}</div>
        <div class="s">${esc(d.numero_contagem)}</div>
        <button class="sec" data-i="${i}">Recontar</button></div>`).join("") + `</div>`;
  },
  ligar: () => {
    const lista = divergenciasAbertas();
    document.querySelectorAll("[data-i]").forEach((b) => b.addEventListener("click", () => {
      const d = lista[Number(b.dataset.i)];
      const sku = (ref().skus || []).find((s) => s.sku === d.sku) || {};
      estado.tarefa = { numero_contagem: d.numero_contagem, recontagem_de: d.numero_contagem, endereco: d.endereco,
                        sku: d.sku, lote: d.lote || "", unidade: sku.unidade_base || "un", descricao: sku.descricao || "",
                        instante_congelamento: agoraServidor() };
      ir("contar");
    }));
  },
};

// ------------------------------------------------------------------ tela: investigação (só supervisor)
telas.investigacao = {
  titulo: "Investigação",
  html: () => {
    if (!ehSupervisor()) return `<div class="cartao vazio">Só supervisores investigam divergências.</div>`;
    const lista = divergenciasAbertas(), motivos = ref().motivos_divergencia || [];
    if (!lista.length) return `<div class="cartao vazio">Nenhuma divergência final pendente.</div>`;
    return `<div class="cartao">
      <label for="div">Divergência</label>
      <select id="div">${lista.map((d, i) => `<option value="${i}">${esc(d.endereco)} · ${esc(d.sku)} ${esc(d.lote || "")} · dif. ${d.diferenca > 0 ? "+" : ""}${esc(d.diferenca)}</option>`).join("")}</select>
      <label for="motivo">Etapa de origem (motivo)</label>
      <select id="motivo"><option value="">— escolha —</option>${motivos.map((m) => `<option value="${esc(m.codigo)}">${esc(m.codigo)} — ${esc(m.descricao)}</option>`).join("")}</select>
      <button id="registrar">Registrar investigação</button>
    </div>`;
  },
  ligar: () => {
    const b = $("#registrar"); if (!b) return;
    b.addEventListener("click", () => {
      const d = divergenciasAbertas()[Number($("#div").value)], motivo = $("#motivo").value;
      if (!motivo) return avisar("Escolha o motivo.", true);
      enfileirar("investigacao", { numero_contagem: d.numero_contagem, endereco: d.endereco, sku: d.sku, lote: d.lote || "", motivo },
                 `Investigação · ${d.endereco} · ${d.sku} · ${motivo}`);
      avisar(estado.online ? "Investigação salva. Enviando…" : "Investigação salva no celular.");
      desenhar();
      sincronizar();
    });
  },
};

// ------------------------------------------------------------------ tela: ações (consulta)
telas.acoes = {
  titulo: "Ações do painel",
  html: () => {
    const a = ref().acoes || [];
    if (!a.length) return `<div class="cartao vazio">Nenhum gatilho acionado nos últimos 30 dias de dados.</div>`;
    return `<p><small>Gatilhos dos últimos 30 dias de dados, como no painel. Consulta: a decisão é tomada no computador.</small></p>
      <div class="cartao">${a.map((x) => `<div class="item"><div class="t">${esc(x["métrica"])} · ${esc(x.objeto)}</div>
      <div>${esc(x.detalhe)}</div><div class="s">${esc(x.nome)} · dono: ${esc(x.dono)} · decide: ${esc(x["decisão"])}</div></div>`).join("")}</div>`;
  },
};

// ------------------------------------------------------------------ tela: meus envios
telas.envios = {
  titulo: "Meus envios",
  html: () => {
    const itens = filaDoUsuario().slice().reverse();
    if (!itens.length) return `<div class="cartao vazio">Nada enviado ainda.</div>`;
    const nome = { PENDENTE: "no celular", RECEBIDO: "no computador", ACEITA: "registrada", RECUSADA: "recusada",
                   ERRO: "erro", DUPLICADA: "já existia" };
    return `<p><small>"No celular" = aguarda Wi-Fi. "No computador" = recebida, aguardando a ferramenta registrar.</small></p>
      <div class="cartao">${itens.map((i) => `<div class="item">
        <div class="linha"><span class="t">${esc(i.resumo)}</span><span class="st ${esc(i.situacao)}">${esc(nome[i.situacao] || i.situacao)}</span></div>
        <div class="s">${dataHora(i.criado_em)}${i.mensagem ? " · " + esc(i.mensagem) : ""}</div>
        ${(i.erros || []).length ? `<div class="s" style="color:var(--erro)">${i.erros.map(esc).join("<br>")}</div>` : ""}</div>`).join("")}</div>`;
  },
};

// ------------------------------------------------------------------ início
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
window.addEventListener("online", () => sincronizar());
window.addEventListener("offline", () => { estado.online = false; atualizarSelo(); });
setInterval(() => { if (!estado.tarefa) sincronizar(); }, SINCRONIZAR_A_CADA_MS);
telaAtual = (location.hash || "#inicio").slice(1);
desenhar();
sincronizar();
