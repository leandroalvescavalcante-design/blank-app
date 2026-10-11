# Etapa 3 — Grão Declarado (onda 1)

**Entrada:** Etapas 0–2 aprovadas; grão do ciclo = linha de pedido × remessa.
**Status:** proposta, aguardando validação.

Legenda: **[F]** fato · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto.

---

## 0. Regras gerais de grão [D]

1. **Grão atômico na camada dimensional.** Agregado é visão, nunca tabela-fonte.
2. **Correção é estorno, nunca update.** Um evento errado gera uma linha inversa e uma linha correta. Exceção única: o snapshot acumulado (P11), que é **derivado** e reconstruível a partir do bruto.
3. **Instante** = timestamp com fuso. **Dia operacional** = dia definido pelo horário de corte do site (calendário operacional), não meia-noite.
4. **Chave de negócio** = o que identifica a linha no mundo real. Junto com o hash do conteúdo, garante a idempotência: recarregar o mesmo arquivo não duplica nada, e uma linha com a mesma chave e hash diferente é tratada como **correção** (estorno + nova), nunca sobrescrita.
5. Todo fato carrega **empresa (tenant)** e **procedência**. Ficam omitidos das tabelas abaixo para não repetir.

## 1. Grão por processo

| Fato | Processo | Tipo | Grão — "uma linha =" | Chave de negócio |
|---|---|---|---|---|
| F01 `recebimento` | P01 | Transacional | um SKU × lote recebido numa linha de documento de recebimento, conferido por um colaborador num instante | nº recebimento + item + lote |
| F02 `movimento_estoque` | P02 | Transacional (razão) | uma variação de saldo de um SKU × lote num endereço, de um tipo de movimento, num instante | documento de origem + item + sequência + tipo de movimento |
| F03 `saldo_diario` | P03 | Snapshot periódico | o saldo de um SKU × lote × endereço no corte do dia operacional do site | SKU + lote + endereço + dia |
| F04 `contagem` | P04 | Transacional | uma contagem de uma posição (SKU × lote × endereço) por um colaborador num instante, com o saldo do sistema congelado naquele instante | nº contagem + posição + nº da recontagem |
| F05 `pedido_compra_linha` | P05 | Snapshot acumulado | uma linha de pedido de compra, do momento da emissão ao encerramento | nº PC + item |
| F06a `programacao_op` | P06 | Snapshot periódico (por versão) | uma OP alocada a um recurso num turno, numa versão do programa | OP + recurso + turno + versão |
| F06b `apontamento` | P06 | Transacional | um apontamento de produção de uma OP num recurso, num instante | OP + recurso + nº apontamento |
| F07 `evento_pedido_venda` | P07 | Transacional | um evento do **cliente** sobre uma linha de pedido de venda (criação, alteração de quantidade/data, cancelamento) | pedido + item + nº do evento |
| F08 `separacao` | P08 | Transacional | uma tarefa de separação de um SKU × lote, de um endereço, para uma linha de pedido × remessa | nº tarefa |
| F09 `faturamento` | P09 | Transacional | um item de nota fiscal de saída ligado a uma linha de pedido × remessa | chave da NF + item |
| F10a `viagem` | P10 | Transacional | uma viagem de um veículo, da saída do site ao retorno | nº viagem |
| F10b `entrega` | P10 | Transacional | uma **tentativa** de entrega de uma remessa a um cliente, numa viagem | nº viagem + remessa + nº tentativa |
| F11 `ciclo_pedido` | P11 | Snapshot acumulado (derivado) | uma linha de pedido × remessa, com o instante de cada marco do ciclo configurado pelo tenant | pedido + item + remessa |
| F12 `planejamento_sku` | derivado de K01/K09/K14 | Snapshot periódico (derivado) | o estado de planejamento de um SKU num local num dia: aptidão, demanda usada, SS, ROP e dias até ruptura vigentes | SKU + local + dia |

## 2. Decisões de grão que não são óbvias

### F02 — transferência = duas linhas
Uma saída no endereço de origem e uma entrada no destino, com soma zero. **[I]** É o único jeito de a reconciliação (K04) fechar por endereço.

### F03 — saldo esparso e semiaditivo
- **[D]** Não grava linha de saldo zero. A ausência significa zero. Sem isso, o snapshot cresce com SKU × lote × endereço × dia, mesmo vazios.
- Medidas físico, bloqueado e reservado ficam em colunas separadas. **Semiaditivas:** somam entre SKUs e endereços, **nunca entre dias**. A camada semântica (Etapa 6) precisa impor isso.

### F04 — saldo do sistema congelado no instante da contagem
**[I]** Contar enquanto há movimento gera divergência falsa. Sem o saldo congelado e o instante, K01 e K02 medem o ruído do fluxo, não o erro do processo. Só a **última** recontagem de uma posição gera ajuste em F02.

### F05 — data prevista original e atual
O acumulado guarda `data_prevista_original` e `data_prevista_atual`. A antecipação/postergação (D05) muda a atual; a original serve para medir a confiabilidade do fornecedor. O histórico completo de alterações fica no bruto.

### F06a — versão do programa
**[D]** K12 (aderência) compara o apontado com a **versão congelada no início do turno**. Comparar com a última versão faria a aderência sempre parecer boa: basta reprogramar depois do fato.

### F07 — demanda só com eventos do cliente
O corte feito por nós **não** é evento de F07; ele aparece em F08/F11. Assim, a demanda (d, σ_d) vem limpa de ruptura: é o que o cliente pediu, líquido do que o próprio cliente alterou ou cancelou. Isso materializa a decisão da Etapa 1 (demanda pelo pedido, não pelo faturamento).

### F10b — tentativa, não entrega
**[I]** Uma remessa pode ter entrega frustrada e reentrega. Gravar só "a entrega" apaga o custo e a causa da tentativa falha. O OTIF (K15) usa a **última** tentativa; o diagnóstico usa todas.

### F11 — corte vira remessa com status
Quando parte de uma linha de pedido é cortada, a quantidade cortada vira uma "remessa" própria com status `cortada`. Invariante:

> Σ qtd das remessas de uma linha = qtd pedida líquida (F07)

**Por quê:** resolve o problema de Little levantado na Etapa 1. Nada sai do sistema sem registro: toda quantidade pedida termina em `entregue`, `cortada` ou `cancelada_cliente`, e o tempo de ciclo e o WIP fecham.

### F12 — planejamento como fato
**[D]** Grava o ROP e os parâmetros **usados** em cada dia. Responde "com que número a decisão de ontem foi tomada", o que nenhuma tabela de parâmetros com vigência responde sozinha quando a demanda calculada muda diariamente.

## 3. Posição contrária mais forte

**"F11 e F12 são derivados. Derivado é visão, não tabela. Materializar é duplicar verdade."**
Correto em princípio, e é a regra 1 acima. Por que materializei mesmo assim:
- **F11:** montar o ciclo exige juntar 5 fatos com remessa parcial e corte. **[I]** Recalcular isso a cada consulta do dashboard é caro e difícil de testar.
- **F12:** a demanda média de ontem, recalculada hoje com dado corrigido, dá outro número. Uma visão não reproduz o que foi visto na hora da decisão.

**[D]** Os dois ficam marcados como `derivado`, são reconstruídos do bruto por processo único e nunca recebem digitação. Custo: mais um processo de carga para manter.

## 4. Referências — onde falham aqui

- **Kimball (grão atômico, três tipos de fato):** os três tipos aparecem (F02, F03 e F11). Falha onde Kimball trata o snapshot acumulado como atualizado no lugar. Aqui ele precisa ser reconstruível do bruto imutável, ou viola a invariante de três camadas.
- **Little:** tratado pela invariante de F11.

## 5. O que não sei

1. **Quem gera o identificador de remessa.** Muitos ERPs não têm o conceito de remessa; têm ordem de separação ou NF. **[I]** Provavelmente o produto precisa gerá-lo: remessa = agrupamento de saída (ordem de separação, ou NF quando não houver ordem). Descobre-se olhando o modelo de dados de 2–3 ERPs usados pelos arquétipos.
2. **Se o apontamento (F06b) existe nos arquétipos A e C com essa granularidade.** Em planta sem coletor, o apontamento costuma ser por turno, em papel. Se for o caso, o grão real é OP × recurso × turno, e K12 fica limitado a isso.

## 6. Recalcular com dado real

Nada calculado nesta etapa.
