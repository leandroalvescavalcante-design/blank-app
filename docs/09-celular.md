# 09 — Coleta pelo celular (Android), com e sem Wi-Fi

Um único app instalado no celular a partir do navegador (PWA, sem loja). Funciona **online** (no Wi-Fi da empresa,
envia na hora) e **offline** (sem rede, guarda no celular e envia quando o Wi-Fi volta). O celular só **coleta**:
a validação e a gravação continuam sendo as de sempre, feitas no computador.

## O que o celular faz

| Função | Quem | Offline? |
|---|---|---|
| Contagem cega (endereço, SKU por código de barras ou digitação, lote em ordem FEFO, quantidade) | inventariante, conferente, supervisor | sim |
| Recontagem de divergência pendente (sem ver a diferença) | idem | sim (lista da última sincronização) |
| Investigação de divergência (motivo / etapa de origem) | só supervisor | sim |
| Consulta das ações do painel (gatilhos dos últimos 30 dias de dados) | só supervisor | sim (última sincronização) |
| Meus envios: no celular → no computador → registrada / recusada (com o erro) | todos | sim |

## Arquitetura (por que é assim)

```
Celular (PWA)  ──HTTPS 8443──▶  servidor do celular  ──arquivos──▶  ferramenta (dona do banco)
 fila local                      (python -m app.movel.servidor)       vigia a cada 15 s:
 (localStorage)                   grava fila/<id>.json                  carga.registrar(...) → bruto
                                  lê referencias.json   ◀────────────  exporta referencias.json
```

- **Fato:** o DuckDB aceita um único processo gravando. O servidor do celular, por isso, **não abre o banco**:
  troca arquivos com a ferramenta (`dados/movel/fila`, `resultados`, `processados`, `referencias.json`).
  Escrita sempre atômica (arquivo temporário + troca), então nada é lido pela metade.
- **Idempotência em três pontos:** id único (UUID) gerado no celular; o servidor ignora reenvio do mesmo id;
  a ferramenta grava cada item com `nome_arquivo = celular:<id>` e não grava duas vezes, mesmo se cair no meio.
- **Contagem cega offline:** o celular registra só o **instante do congelamento** (no relógio do computador:
  o desvio do relógio do celular é medido a cada sincronização). O saldo do sistema é calculado no computador
  para aquele instante (`consultas.saldo_congelado`: fotografia do site + movimentos lançados depois).
  Quem conta não recebe saldo, diferença, nem a lista de ações (o K05 traz a quantidade do lote).
- **Recontagens feitas offline** por pessoas diferentes recebem número sequencial na ordem de chegada (1, 2, …).
- **Validação:** a mesma de `entrada/layouts.yaml`. Item recusado volta ao celular com o erro em "Meus envios".

## Segurança

- Login por **matrícula + PIN** (4 a 8 dígitos; recusa repetidos e sequências). PIN guardado só como hash scrypt.
- Sessão de 7 dias (permite trabalhar offline); 5 erros bloqueiam a matrícula por 5 minutos.
- `remover-pin` revoga na hora: o próximo envio daquele celular é recusado.
- A matrícula gravada no bruto vem da sessão, nunca do que o celular manda.
- Investigação só é aceita de SUPERVISOR (conferido no servidor, não só na tela).
- HTTPS obrigatório: o Chrome só libera modo offline, instalação e câmera em conexão segura. Como a rede da planta
  não tem domínio público, a ferramenta cria uma **CA local** (10 anos) e um certificado do servidor (825 dias)
  com os IPs do computador. A porta 8080 serve só a página para baixar o `ca.crt` (certificado público).

## Instalação

**No computador (administrador), uma vez:**

1. Abra a ferramenta pelo atalho de sempre: o servidor do celular sobe junto (janela minimizada no Windows).
   No Windows, se aparecer o aviso do Firewall, permita em **Redes privadas**.
2. Crie o PIN de cada pessoa (a matrícula precisa estar em `cad_colaborador`):
   `python -m app.admin definir-pin --matricula M001` (pede o PIN sem mostrar na tela).
3. Anote o endereço mostrado na janela do servidor, por exemplo `http://192.168.0.10:8080`.
4. **Recomendado:** fixe o IP do computador (reserva de DHCP no roteador). Se o IP mudar, o certificado do servidor
   é regerado sozinho ao abrir; os celulares não precisam reinstalar nada, só usar o novo endereço.

**Em cada celular, uma vez:**

1. No Wi-Fi da empresa, abra no Chrome `http://<IP>:8080` e toque em **Baixar o certificado**.
2. **Configurações → Segurança → Mais configurações → Instalar certificado → Certificado de CA** → escolha `ca.crt`.
3. Abra `https://<IP>:8443`, entre com matrícula e PIN.
4. Menu do Chrome → **Instalar app**. Daí em diante, abra pelo ícone "Coleta".

## Comandos

```
python -m app.admin definir-pin --matricula M001       # cria/troca PIN
python -m app.admin remover-pin --matricula M001       # revoga acesso
python -m app.admin processar-celular                  # processa a fila com a ferramenta FECHADA
python -m app.admin gerar-certificado                  # regera o certificado do servidor
python -m app.movel.servidor                           # sobe o servidor do celular (os iniciadores já fazem)
```

Portas: `GESTAO_PORTA_CELULAR` (padrão 8443) e `GESTAO_PORTA_CERTIFICADO` (padrão 8080).

## Limites conhecidos (o que pode dar errado)

- **Não verificado em aparelho real:** que o Chrome do seu modelo de Android aceite a CA instalada pelo usuário
  para sites (no Android 7+ o Chrome aceita CA do usuário; apps nativos não). Testado em Chromium emulando um Pixel 7.
  Se o seu aparelho recusar, a alternativa é ativar em `chrome://flags` a opção
  "Insecure origins treated as secure" com `http://<IP>:8080` — funciona, mas sem criptografia.
- **Leitura pela câmera** usa o leitor de código de barras do Chrome (BarcodeDetector). Se o aparelho não tiver,
  o app avisa e aceita digitação ou o gatilho de um coletor com leitor (que "digita" o código).
- **A fila só é processada com a ferramenta aberta** no computador (ou com `processar-celular`). Até lá, o item
  aparece como "no computador".
- **Offline por muito tempo:** a lista de divergências e lotes é a da última sincronização. Um lote novo pode ser
  digitado em "O lote físico não está na lista".
- **Celular compartilhado:** cada item fica preso à matrícula que o criou e só é enviado quando aquela pessoa entra.
- **Apagar os dados do navegador** apaga a fila ainda não enviada. Sincronize antes.
