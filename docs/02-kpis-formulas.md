# Etapa 2 — KPIs e Fórmulas (onda 1)

**Entrada:** Etapas 0 e 1 aprovadas.
**Status:** proposta, aguardando validação.
**Regra:** o KPI define o grão. Cada métrica abaixo declara o **grão mínimo** que exige; a Etapa 3 só pode escolher grão igual ou mais fino.

Legenda: **[F]** fato · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto · **[P]** parâmetro que só vem do dado real (provisório com sintético).

---

## 0. Três classes de métrica [D]

Misturar as três no mesmo painel é o que gera "meta de acuracidade":

| Classe | Função | Tem meta? |
|---|---|---|
| **Decisão** | Dispara uma ação da Etapa 0 | Sim, como limiar de gatilho |
| **Diagnóstico** | Explica por que a métrica de decisão está ruim | **Não.** Perseguida como meta, vira manipulação |
| **Integridade** | Diz se o dado é confiável o bastante para decidir | Sim: deve ser zero / 100% |

---

## 1. Frente 1 — Estoque, lote e acuracidade

### K01 · Acuracidade de inventário (por posição) — *Diagnóstico + pré-condição*
```
posição = SKU × lote × endereço contado
acerto(posição) = 1 se |contado − sistema| ≤ tolerância_SKU, senão 0
K01 = Σ acerto / Σ posições contadas            [%]
```
- **Decisão que alimenta:** D07 (o que contar) e **pré-condição de D04**: o SKU só recebe ponto de pedido calculado se `apto_reposicao = 1`, isto é, ter ≥ N contagens nos últimos M dias com K01 ≥ limiar. **[P]** N, M, limiar e tolerância.
- **Por que por posição e não por quantidade:** `1 − Σ|dif|/Σsistema` deixa um erro grande num SKU barato e de alto volume esconder vários erros pequenos. **[I]**
- **Não é meta (antipadrão).** É saída de K02.
- **Grão mínimo:** uma contagem de uma posição.
- **Dono:** líder de armazém.

### K02 · Divergência por etapa de origem — *Diagnóstico*
```
K02(etapa) = Σ |dif_qtd| × custo_unit   agrupado por etapa_origem ∈
             {recebimento, endereçamento, separação, conferência, desconhecida}   [R$]
K02b = Σ dif da etapa "desconhecida" / Σ dif total     [%]
```
- **Decisão:** D08 (onde atacar a causa).
- K02b alto significa que a investigação não está sendo feita. É o alarme de "ajuste sem causa". **[I]**
- **Grão mínimo:** uma divergência de uma posição, com motivo e etapa.
- **Dono:** supervisor de armazém.

### K03 · Ajuste bruto × líquido — *Diagnóstico*
```
bruto   = Σ |ajuste| × custo_unit     [R$]
líquido = Σ  ajuste  × custo_unit     [R$]
```
- **[I]** Bruto alto com líquido perto de zero indica troca de endereço/SKU (sobra num lugar e falta noutro), não perda. Isso muda a ação de D08: endereçamento em vez de segurança.
- **Grão mínimo:** um movimento de ajuste no razão (P02).
- **Dono:** controller.

### K04 · Reconciliação do razão — *Integridade*
```
dif_rec(SKU, lote, local, d) = saldo(d) − [saldo(d−1) + Σ movimentos(d)]
K04 = nº de combinações com dif_rec ≠ 0          [contagem; alvo = 0]
```
- **Decisão:** bloquear o uso do saldo em D04, D05 e D06 para combinações com exceção.
- **Grão mínimo:** SKU × lote × local × dia.
- **Dono:** engenharia de dados.

### K05 · Quantidade em risco de vencimento (FEFO) — *Decisão*
Por SKU × local, com os lotes ordenados por validade (i = 1 é o mais antigo):
```
t_i  = dias vendáveis = validade_i − validade_mínima_cliente − trânsito − hoje      [dias]
d    = demanda diária média do SKU no local                                   [P]
consumível_i = mín( saldo_i ; máx(0 ; d × t_i − Σ_{j<i} consumível_j) )
risco_i      = saldo_i − consumível_i                                          [un e R$]
```
- **Decisão:** D06 (priorizar, transferir, rebaixar, descartar). Gatilho: `risco_i > 0`.
- **Por que `Σ consumível_j` e não `Σ saldo_j`:** a parte de um lote anterior que vence é descartada, não consumida; a demanda daqueles dias passa ao lote seguinte. Subtrair o saldo inteiro superestimaria o risco dos lotes novos.
- **[I]** Supõe consumo FEFO perfeito e demanda constante. Superestima o risco se houver um pico previsto e subestima se a separação não respeitar o FEFO. Por isso K05 precisa conviver com uma métrica de **aderência FEFO** (onda 2).
- **Dependência aberta (Etapa 1):** `validade_mínima_cliente` por cliente ou por cliente × SKU. Até decidir, uso o **mais restritivo** entre os clientes ativos do SKU. É conservador e gera mais alerta.
- **Grão mínimo:** saldo por SKU × lote × local × dia (P03).
- **Dono:** analista de estoque.

### K06 · Perdas por motivo — *Decisão (D18) / Diagnóstico (D06)*
```
K06(motivo) = Σ qtd_baixada × custo_unit   para motivo ∈ {vencimento, avaria, ajuste, outro}   [R$]
K06% = K06 / custo das saídas do período                                                        [%]
```
- **Grão mínimo:** um movimento de baixa no razão.
- **Dono:** controller.

### K07 · Cobertura — *Decisão (D05) / Diagnóstico (D19)*
```
K07 = saldo_disponível / d          [dias]
saldo_disponível = saldo físico − bloqueado − reservado
```
- **Grão mínimo:** SKU × local × dia.
- **Dono:** analista de estoque.

### K08 · Valor do estoque — *Decisão (D18)*
```
K08 = Σ saldo × custo_unit_médio     [R$]
```
- **[D]** O método de custeio (médio, por lote) vem do ERP do tenant. O produto não recalcula custo contábil; ele **lê** e marca a procedência.
- **Grão mínimo:** SKU × lote × local × dia.
- **Dono:** controller.

---

## 2. Frente 2 — Planejamento de produção e compra

### K09 · Estoque de segurança e ponto de pedido — *Parâmetro de decisão (D04)*
```
SS  = z × √( L × σ_d² + d² × σ_L² )      [un]     L, σ_L em dias; d, σ_d em un/dia
ROP = d × L + SS                          [un]
```
- **[P]** d, σ_d, L, σ_L, z (nível de serviço). **Todo valor calculado com sintético nasce provisório.**
- **Calculado apenas se `apto_reposicao = 1`** (K01). Caso contrário, o campo fica nulo com motivo "acuracidade desconhecida". Antipadrão evitado.
- **Onde a fórmula falha:** supõe demanda e lead time independentes e aproximadamente normais. **[F]** Demanda intermitente (muitos dias zero) viola isso. Para esses SKUs, não sei qual método é adequado sem a série real. Candidatos a testar: Croston e quantil empírico. **[D]** O modelo grava `metodo_ss` por SKU, para não fixar a fórmula.
- **Grão mínimo:** demanda por SKU × local × dia (P07) e lead time por linha de PC recebida (P05/P01).
- **Dono:** analista de estoque.

### K10 · Lote de compra/produção com teto de vida útil — *Parâmetro de decisão (D03)*
```
Q*        = √( 2 × D × S / H )                                  [un]   D anual, S R$/pedido, H R$/un/ano
Q_palete  = ⌈ Q* / un_por_palete ⌉ × un_por_palete               [un]
cob_max   = shelf_life − validade_mínima_cliente − trânsito − dias_parados     [dias]
teto      = ⌊ d × cob_max / un_por_palete ⌋ × un_por_palete     [un]
Q         = mín( Q_palete ; teto )
```
- **Correção à fórmula do briefing [D]:** arredondei também o teto **para baixo**, a múltiplo de palete. Sem isso, `mín()` pode devolver uma fração de palete justamente quando o teto prevalece.
- **Caso de falha que precisa de alerta:** se `teto < lote_mínimo` (do fornecedor ou da linha), ou se `teto = 0`, o item é **inviável no regime atual**. O sistema não deve arredondar para cima calado; gera alerta para D03 (negociar lote mínimo, mudar embalagem ou aceitar perda planejada).
- **[F]** Para itens não perecíveis (arquétipo C), `shelf_life` é nulo e o teto não se aplica.
- **[P]** D, S, H, d.
- **Grão mínimo:** parâmetro por SKU × local (vigência), mais demanda diária.
- **Dono:** PPCP / Compras.

### K11 · Carga do recurso restritivo — *Decisão (D01)*
```
K11 = Σ_OP ( qtd_i × tempo_padrão_i + setup_i ) / tempo_disponível_turno     [%]
```
- **Gatilho:** K11 > 100% força resequenciamento ou retenção de OP.
- **[P]** tempo_padrão e setup. A matriz de setup é sequência-dependente: o setup de A→B ≠ B→A.
- **Grão mínimo:** OP × recurso × turno (programado).
- **Dono:** programador PPCP.

### K12 · Aderência ao programa — *Diagnóstico (D01)*
```
K12 = Σ mín(produzido_i ; programado_i) / Σ programado_i       [%]   por OP × dia
```
- **[I]** `mín()` impede que excesso numa OP compense falta noutra. Produzir além do programa é desperdício (Ohno), não crédito.
- **Grão mínimo:** apontamento por OP × dia.
- **Dono:** gerente PPCP.

### K13 · Lead time realizado de fornecedor — *Insumo de K09*
```
L_k   = data_recebimento_k − data_emissão_PC_k      [dias corridos]
L, σ_L = média e desvio de L_k por fornecedor × SKU (janela móvel)   [P] tamanho da janela
```
- **[D]** Dias **corridos**, porque o fornecedor não para no feriado do comprador. Trocar por dias úteis é configurável por tenant.
- Recebimento parcial: cada recebimento é um L_k, ponderado pela quantidade.
- **Grão mínimo:** uma linha de recebimento ligada à linha do PC.
- **Dono:** comprador.

### K14 · Dias até ruptura projetada — *Decisão (D05)*
```
demanda(τ) = máx( comprometida(τ) ; d )        por dia τ   (não somar as duas: a carteira já é parte da demanda)
posição_projetada(t) = saldo_disponível + Σ_{τ≤t} entradas_previstas(τ) − Σ_{τ≤t} demanda(τ)
K14 = menor t com posição_projetada(t) < SS         [dias]
```
- **Gatilho:** K14 < L, ou seja, emitir ou antecipar o PC.
- **Grão mínimo:** SKU × local × dia, com PCs e OPs abertos.
- **Dono:** comprador.

---

## 3. Frente 3 — Ciclo do pedido e expedição

### K15 · OTIF por linha — *Decisão (D14, D15)*
```
OK(linha) = 1 se  entregue dentro da janela prometida
                 E  |qtd_entregue − qtd_pedida| ≤ tolerância
K15 = Σ OK / Σ linhas devidas no período        [%]
```
- **Denominador [D]:** inclui linhas cortadas por nós (falta de saldo) e exclui apenas as canceladas pelo cliente, marcadas com motivo. Excluir o corte próprio infla o OTIF. **[I]**
- **[F]** Não existe uma definição única de OTIF no mercado. Por isso o produto grava a regra (janela, tolerância) como metadado do tenant, e comparações entre tenants só valem com regra idêntica.
- **Grão mínimo:** linha de pedido × entrega.
- **Dono:** gerente de logística.

### K16 · Fill rate e corte por motivo — *Decisão (D15)*
```
K16  = Σ qtd_atendida / Σ qtd_pedida                [%]
corte(motivo) = Σ (qtd_pedida − qtd_atendida)      [un, cx]
```
- **Grão mínimo:** linha de pedido.
- **Dono:** líder de expedição.

### K17 · Tempo de ciclo por etapa — *Diagnóstico (D14, D15)*
```
etapas: pedido → faturamento → separação → carregamento → entrega
Δ_etapa = t_fim − t_início          [horas]
reporte: mediana e P90 (não média)
```
- **[D] Mediana e P90:** a distribuição de tempo de ciclo tem cauda longa. A média é puxada por poucos pedidos travados e esconde o que o cliente típico vive. **[I]**
- **Checagem de consistência (Little):** `WIP médio ≈ throughput × tempo médio de ciclo`. A lei usa **média**, então ela é calculada também, só para a checagem. Se não bater, há pedido entrando ou saindo sem registro.
- **Ordem das etapas é configurável [D]:** em muitas operações a separação vem antes do faturamento. O briefing fixa uma ordem; o produto não deve.
- **Grão mínimo:** linha de pedido × remessa (ver alerta da §5).
- **Dono:** gerente de logística.

### K18 · Ocupação do veículo — *Decisão (D14)*
```
K18 = máx( peso_carga / cap_kg ; volume_carga / cap_m³ )     [%]  por viagem
```
- **[I]** O `máx()` identifica a restrição ativa. Carga leve e volumosa enche no m³; carga densa, no kg. Medir só por peso esconde caminhão "cheio de ar".
- **Fonte de peso e volume:** fatores de conversão da dimensão SKU.
- **Grão mínimo:** viagem (com as linhas carregadas).
- **Dono:** programador de transporte.

### K19 · Custo de frete por unidade — *Decisão (D14)*
```
K19 = custo_viagem / Σ kg entregues      [R$/kg]   (alternativa configurável: R$/cx, R$/entrega)
```
- **Grão mínimo:** viagem.
- **Dono:** gerente de logística.

---

## 4. Rastreabilidade KPI → decisão (onda 1)

| Decisão | Métrica de decisão | Diagnóstico | Integridade |
|---|---|---|---|
| D04 Parâmetros de reposição | K09 | K13 | K01 (apto), K04 |
| D05 Pedido de compra | K14, K07 | K13 | K04 |
| D06 Lote em risco | K05 | K06 | K04 |
| D07 O que contar | — (lista gerada) | K01 | K04 |
| D08 Divergência | — (por evento) | K02, K02b, K03 | K04 |
| D01 Sequenciar OP | K11 | K12 | — |
| D03 Tamanho de lote | K10 | — | — |
| D14 Carga e roteiro | K18, K19 | K17 | — |
| D15 Corte | K16, K15 | K17 | K04 |
| D18 Fechamento | K08, K06 | K03 | K04 |

Toda decisão da onda 1 tem pelo menos uma métrica. Toda métrica serve a pelo menos uma decisão. Nada sobrou.

## 5. Consequências para o grão (entrada da Etapa 3)

1. **Remessa parcial quebra o grão "linha de pedido".** Uma linha pode ser faturada e entregue em duas vezes. K15 e K17 exigem **linha de pedido × remessa**. O snapshot acumulado (P11) precisa desse grão, ou terá datas sobrescritas.
2. **Contagem é por posição** (SKU × lote × endereço), não por SKU.
3. **Saldo diário precisa de lote e endereço**, porque K05 e K04 exigem.
4. **Parâmetros (K09, K10) têm vigência.** Precisam guardar histórico, para saber com qual ROP a decisão de ontem foi tomada.

## 6. Posição contrária mais forte

**"Adote SCOR (APICS/ASCM) como catálogo de métricas: dá benchmark entre empresas, que é o valor de um produto."**
É o argumento certo para um produto. Onde falha: **[F]** o SCOR padroniza nomes e hierarquia, mas cada empresa implementa janela, tolerância e exclusões do seu jeito. **[I]** Benchmark sem definição idêntica compara coisas diferentes com o mesmo nome.
**[D]** Uso o nome SCOR quando a definição coincide e gravo a regra como metadado; o benchmark só sai entre tenants com regra igual. Custo: menos benchmark disponível no início.

## 7. Referências — onde falham aqui

- **Silver, Pyke & Peterson (SS com variância do lead time):** pressupõe normalidade e independência. Falha em demanda intermitente e quando atraso do fornecedor e pico de demanda andam juntos.
- **Harris/Wilson (EOQ):** custo de manter linear. Falha no perecível, porque o custo salta no vencimento. Tratado com o teto em K10.
- **Little:** vale para médias em regime estável. Falha com sazonalidade forte dentro da janela medida. Por isso K17 o usa só como checagem.
- **Deming / Goodhart:** justifica K01 como diagnóstico. Falha se ninguém investigar a causa, e por isso existe K02b.

## 8. Recalcular com dado real

| Parâmetro | Usado em | Origem obrigatória |
|---|---|---|
| d, σ_d (demanda diária) | K05, K07, K09, K10, K14 | Série de pedidos (P07), não de faturamento |
| L, σ_L (lead time) | K09, K14 | Recebimentos reais (K13) |
| z / nível de serviço | K09 | Decisão do gestor por classe de SKU |
| S, H (custo de pedir/manter) | K10 | Contabilidade de custos do tenant |
| shelf_life, validade mínima, trânsito, dias parados | K05, K10 | Cadastro do SKU, contratos de cliente, rotas reais |
| Tolerância de contagem, N, M, limiar de aptidão | K01 | Política do tenant; calibrar após 1º ciclo de contagens |
| Tempo padrão, matriz de setup | K11 | Cronoanálise ou apontamento real |
| Janela e tolerância de OTIF | K15 | Contrato/política comercial |
| Método de SS para itens intermitentes | K09 | Teste sobre série real |
