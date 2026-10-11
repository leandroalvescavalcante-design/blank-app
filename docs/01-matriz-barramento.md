# Etapa 1 — Matriz de Barramento (onda 1)

**Entrada:** Etapa 0 aprovada (arquétipos A/B/C; frentes: estoque-lote-acuracidade, planejamento produção-compra, ciclo do pedido-expedição).
**Status:** proposta, aguardando validação.

Legenda: **[F]** fato · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto.
Na matriz: **X** = dimensão obrigatória no processo · **○** = alcançada indiretamente (via outra dimensão ou outro fato), não vira chave no fato · **–** = não se aplica.

---

## 1. Processos de negócio da onda 1

Processo = evento que acontece no mundo e gera medida, não departamento.

| Cód | Processo de negócio | Arquétipos | Decisões que alimenta |
|---|---|---|---|
| P01 | Recebimento (fornecedor → doca → estoque) | A, B, C | D05, D06, D08 |
| P02 | **Movimento de estoque (razão)**: toda variação de saldo (entrada, saída, transferência, ajuste, baixa) | A, B, C | D08, D18 |
| P03 | Saldo de estoque (fotografia diária) | A, B, C | D04, D06, D07, D18 |
| P04 | Contagem de inventário | A, B, C | D07, D08 |
| P05 | Pedido de compra (linha) | A, B, C | D03, D05 |
| P06 | Ordem de produção (programação + apontamento) | A, C | D01, D03 |
| P07 | Pedido de venda (linha) / carteira | A, B, C | D04 (demanda), D15 |
| P08 | Separação e conferência | A, B, C | D08, D15 |
| P09 | Faturamento (linha de nota) | A, B, C | ciclo do pedido |
| P10 | Transporte (carga → parada → entrega) | A, B, C | D14 |
| P11 | **Ciclo do pedido** (consolidado: pedido → faturamento → separação → carregamento → entrega) | A, B, C | D14, D15 |

**[D] P02 é o razão único.** Recebimento, apontamento, expedição e ajuste têm fato próprio, mas todo efeito sobre o saldo também lança em P02. Isso cria a invariante de reconciliação:

> saldo(d) = saldo(d−1) + Σ movimentos(d), por SKU × lote × local

Se a conta não fechar, o problema está na carga, não na operação. **[I]** É o poka-yoke do próprio dado: detecta movimento sem lançamento antes de alguém "ajustar para fechar".

**[I] P07 mede demanda pelo pedido, não pelo faturamento.** O faturamento é demanda censurada: quando falta saldo, o que não foi faturado some do histórico. Usar faturamento como demanda em D04 subestima o desvio exatamente onde há ruptura.

## 2. Matriz

| Processo | Empresa | Calendário | SKU | Lote | Local | Cliente | Fornecedor | Recurso | Veículo | Colaborador | Motivo | Procedência |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| P01 Recebimento | X | X | X | X | X | – | X | – | – | X | X | X |
| P02 Movimento (razão) | X | X | X | X | X | ○ | ○ | ○ | – | X | X | X |
| P03 Saldo diário | X | X | X | X | X | – | ○ | – | – | – | – | X |
| P04 Contagem | X | X | X | X | X | – | – | – | – | X | X | X |
| P05 Pedido de compra | X | X | X | – | X | – | X | – | – | – | X | X |
| P06 Ordem de produção | X | X | X | X | X | – | – | X | – | ○ | X | X |
| P07 Pedido de venda | X | X | X | – | X | X | – | – | – | – | X | X |
| P08 Separação/conferência | X | X | X | X | X | X | – | – | – | X | X | X |
| P09 Faturamento | X | X | X | ○ | X | X | – | – | – | – | – | X |
| P10 Transporte | X | X | ○ | – | X | X | X | – | X | X | X | X |
| P11 Ciclo do pedido | X | X | X | – | X | X | ○ | – | X | – | X | X |

Notas de linha:
- **P02 ○ Cliente/Fornecedor/Recurso:** o movimento referencia o documento de origem (degenerado: nº NF, nº OP, nº recebimento). Cliente, fornecedor e recurso são alcançados pelo fato de origem, não repetidos no razão.
- **P06 ○ Colaborador:** nenhuma decisão da onda 1 precisa saber quem apontou (R4). Entra na onda 2 com D12 (manutenção).
- **P09 ○ Lote:** o lote expedido é definido na separação (P08). **[I]** A NF-e só traz lote em alguns setores; não dá para depender dela.
- **P10 Fornecedor:** papel *transportadora* (ver §3).
- **P10 Colaborador:** motorista. **[F]** A jornada do motorista profissional tem limites legais (Lei 13.103/2015), que restringem a roteirização em D14.
- **P08 Colaborador:** necessário para D08 (a ação corretiva pode ser treinamento de um operador específico). **[D] Governança:** é dimensão de processo, não de ranking (exclusão da Etapa 0).

## 3. Dimensões conformadas — lista revisada

Partindo das 9 do briefing, a matriz exigiu **3 acréscimos** e **1 fusão**:

| Dimensão | Origem | Por quê |
|---|---|---|
| Calendário | briefing | **[F]** Feriados municipais variam por município. **[D]** Divido em duas: data global (semana ISO, mês fiscal) + calendário operacional por site (dia útil, turno) |
| SKU | briefing | Inclui fatores de conversão (un, cx, palete, kg, m³) e shelf life |
| Lote/validade | briefing | Dimensão própria; carrega fabricação, validade e origem (fornecedor ou OP) |
| Local | briefing | Hierarquia interna: empresa → site → zona → endereço. Endereço de entrega do cliente fica no Cliente, não aqui |
| Cliente | briefing | Inclui ponto de entrega (geo, janela) |
| Fornecedor → **Parceiro** | briefing, **fundida** | Fornecedor de MP e transportadora numa só dimensão, com papel. Usada por papel (role-playing) em P01/P05 vs P10 |
| Veículo | briefing | Capacidade em kg e m³, tipo, própria/terceira |
| Colaborador | briefing | Função e turno; sem atributo de avaliação |
| Motivo | briefing | Lista fechada, tipada por processo (divergência, corte, ajuste, parada, devolução) |
| **Empresa (tenant)** | acréscimo | Produto multiempresa: chave de isolamento em toda linha |
| **Recurso produtivo** | acréscimo | D01 e D21 dependem do gargalo. **[I]** Precisa permitir que o "recurso restritivo" seja configurável (Etapa 0, Goldratt) |
| **Procedência** | acréscimo | Invariante do briefing (ERP, formulário, upload, estimado + confiabilidade). Dimensão pequena (junk), não campo solto repetido |

Fora das dimensões: nº de pedido, NF, OP e recebimento ficam como **dimensão degenerada** no fato. Não têm atributo próprio que justifique tabela.

## 4. Posição contrária mais forte

**Fato único de movimentação (Kimball, *inventory transactions*)** em vez de P01, P04 e P08 separados: menos tabelas, um lugar só para olhar.
Por que não adotei: recebimento compara esperado × recebido, contagem compara contado × sistema, e conferência compara separado × conferido. São medidas que não existem num razão de movimentos. **[D]** Mantive os dois níveis: os fatos de processo têm as medidas de qualidade, e o razão P02 garante a reconciliação do saldo.
Custo dessa escolha: dupla escrita na carga (processo + razão), ou seja, mais um ponto de falha. A invariante de reconciliação é exatamente o que detecta isso.

## 5. Referências — onde falham aqui

- **Kimball (matriz de barramento):** pressupõe que todos os processos existem na empresa. Num produto multiempresa, P06 não existe no arquétipo B. **[D]** A coluna "Arquétipos" marca o que é opcional por tenant; a dimensão conformada continua igual para quem usa.
- **Little (L = λW):** P11 vai medir tempo de ciclo. A lei vale para média de longo prazo em sistema estável. **[I]** Com corte de pedido (D15), pedido cancelado sai do sistema sem completar o ciclo, o que distorce W se for excluído sem marcação. Tratar na Etapa 3 (grão de P11).

## 6. Premissas assumidas (validar)

1. Fundir fornecedor e transportadora em **Parceiro**. **[I]** Correto para conformidade (CNPJ único). Errado se o tenant tratar os dois em cadastros separados no ERP de origem.
2. **Validade mínima aceita pelo cliente** fica no Cliente. **[I]** Na prática pode variar por **cliente × SKU**; se for o caso, vira tabela de acordo (ponte), não atributo. Não sei qual é o caso mais comum; descobre-se perguntando a 2–3 operações reais de cada arquétipo.
3. Faturamento (P09) está na onda 1 só para datar o ciclo. Nenhuma decisão da onda 1 consome valor faturado.

## 7. Recalcular com dado real

Nada calculado nesta etapa.
