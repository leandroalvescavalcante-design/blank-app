# Etapa 0 — Inventário de Decisões

**Escopo:** PRODUTO genérico (multiempresa, metadados configuráveis).
**Status:** proposta, aguardando validação. Nenhum campo, tabela ou tela existe antes desta etapa ser aprovada.

Legenda epistemológica: **[F]** fato verificável · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto (escolha, não fato).

---

## 1. O problema que esta etapa resolve

Num produto genérico não existe um gestor real de quem extrair as decisões. **[I]** Sem isso, a regra "todo campo termina numa ação" vira letra morta e o esquema cresce sem limite. Por isso a etapa define três coisas:

1. **Arquétipos de operação**, que fazem as vezes de "clientes de referência".
2. **Decisões-tipo**, cada uma com quem decide, a frequência e a ação que muda.
3. **Critério de parada**, que diz o que entra no núcleo, o que vira extensão e o que fica fora.

## 2. Arquétipos de referência [D]

| Cód | Arquétipo | Por que entra |
|---|---|---|
| A | Manufatura **perecível** make-to-stock, com CD próprio e frota própria ou terceira | Força lote/validade, FEFO e teto de lote por shelf life |
| B | Distribuidor / CD **sem** transformação (compra → armazena → entrega) | Isola armazém + transporte, sem PPCP de fábrica |
| C | Manufatura **não perecível** make-to-order | Força a lógica de capacidade/gargalo sem validade |

**[I]** Três arquétipos bastam para testar a generalidade sem cair no "esquema universal". Mais que isso só aumenta o WIP de modelagem.

## 3. Critério de parada [D]

| Regra | Efeito |
|---|---|
| **R1** A decisão aparece em **≥ 2 arquétipos** | Entra no **núcleo** |
| **R2** A decisão aparece em 1 arquétipo só | Vira **extensão** (módulo opcional, tabela tipada própria, nunca EAV genérico) |
| **R3** Ninguém muda de ação por causa da decisão, ou ela depende de parâmetro que só vem do real e não tem dado | **Fora** |
| **R4** Um campo só entra se alimentar ao menos 1 decisão do núcleo ou de uma extensão ativa | Corta o "superset de campos" pela raiz |
| **R5** O núcleo v1 abre no máximo **3 frentes** (WIP ≤ 3) | As demais decisões do núcleo ficam na onda 2 |

**[I]** R4 contradiz em parte o texto do parâmetro ("superset de campos"). Vence R4: um superset sem critério é exatamente o antipadrão listado. Custo dessa escolha: o cliente que precisar de um campo fora do núcleo depende de extensão, ou seja, de mais trabalho de configuração.

## 4. Inventário de decisões-tipo

Freq.: D = diária · S = semanal · M = mensal · T = trimestral · A = anual · Ev = por evento.

| ID | Decisão | Decisor (papel) | Freq. | Ação que muda | Arquétipos | Informação mínima (candidata a campo) | Classe |
|---|---|---|---|---|---|---|---|
| D01 | Liberar / segurar / resequenciar ordens de produção | Programador PPCP | D | Sequência de OPs no recurso gargalo | A, C | Demanda firme, saldo disponível por lote, capacidade do gargalo, matriz de setup, disponibilidade de MP | Núcleo |
| D02 | Plano mestre por família (volume/semana, hora extra) | Gerente PPCP | S | Volume planejado e turnos | A, C | Previsão (marcada *estimado*), carteira, capacidade agregada | Núcleo · onda 2 |
| D03 | Tamanho de lote de produção/compra | PPCP / Compras | M (revisão de parâmetro) | Lote padrão por SKU | A, B, C | Demanda média, custo de pedido/setup, custo de manter, múltiplo de palete, **shelf life, validade mínima do cliente, trânsito, dias parados** | Núcleo |
| D04 | Parâmetros de reposição (ponto de pedido, estoque de segurança) | Analista de estoque | M | Parâmetro por SKU × local | A, B, C | Demanda e desvio, lead time e variância, nível de serviço-alvo, **acuracidade medida do SKU** (pré-condição) | Núcleo |
| D05 | Emitir / antecipar / postergar pedido de compra | Comprador | D | Data e quantidade do PC | A, B, C | Posição projetada, parâmetros de D04, lead time do fornecedor | Núcleo |
| D06 | Destino de lote em risco de validade (priorizar saída, transferir, rebaixar, descartar) | Analista de estoque + Qualidade | D | Prioridade de expedição / baixa | A, B | Saldo por lote × endereço, validade, validade mínima por cliente | Núcleo |
| D07 | O que contar hoje (inventário cíclico) | Líder de armazém | D | Lista de contagem | A, B, C | Classe ABC, divergência histórica, última contagem | Núcleo |
| D08 | Divergência: aceitar ajuste ou investigar causa | Supervisor de armazém | Ev | Ajuste vs. análise de causa (recebimento, endereçamento, separação, conferência) | A, B, C | Contagem, saldo do sistema, **etapa de origem provável**, motivo | Núcleo |
| D09 | Reendereçamento / slotting | Líder de armazém | M | Endereço por SKU | B (A parcial) | Giro, cubagem, distância de picking | Extensão |
| D10 | Liberar / reter lote produzido ou recebido | Qualidade | Ev | Status do lote | A, C | Resultado de inspeção, lote, fornecedor | Núcleo · onda 2 |
| D11 | Qual causa de não conformidade atacar | Gerente de qualidade | S | Plano de ação | A, B, C | Ocorrência × motivo × etapa × custo | Núcleo · onda 2 |
| D12 | Priorizar OS / parar equipamento para preventiva | PCM | D/S | Sequência de OS | A, C | Criticidade, falhas, tempo parado, ligação com o gargalo | Núcleo · onda 2 |
| D13 | Revisar frequência do plano preventivo | PCM | T | Intervalo da preventiva | A, C | Histórico de falha (MTBF/MTTR) | Núcleo · onda 2 |
| D14 | Formar carga e roteiro do dia | Programador de transporte | D | Pedido → veículo → sequência | A, B, C | Peso, m³, janela do cliente, local, capacidade do veículo | Núcleo |
| D15 | Corte / atendimento parcial quando falta saldo | Líder de expedição + Comercial | D | Atender, cortar, segurar | A, B, C | Carteira, saldo disponível, prioridade do cliente | Núcleo |
| D16 | Dimensionar frota, turnos e mão de obra | Gerente de logística | M | Quantidade de recursos | A, B, C | Volume por dia, produtividade por recurso | Núcleo · onda 2 |
| D17 | Realocar volume entre transportadoras / fornecedores | Gerente de logística / Compras | M | Participação de volume | A, B, C | OTIF por parceiro, custo | Núcleo · onda 2 |
| D18 | Fechamento mensal: valor do estoque, perdas, aprovação de baixas | Controller / CFO | M | Provisão e aprovação de baixa | A, B, C | Saldo valorizado, perdas por motivo (vencimento, avaria, ajuste) | Núcleo (consome a onda 1) |
| D19 | Reduzir cobertura de quais SKUs (capital de giro) | CFO | M | Meta de cobertura por classe | A, B, C | Cobertura em dias, valor parado, giro | Núcleo · onda 2 |
| D20 | Custo de servir por cliente / rota | CFO + Comercial | T | Pedido mínimo, frequência, frete | A, B | Custo de transporte rateado, volume, devoluções | Núcleo · onda 2 |
| D21 | Investir em capacidade do gargalo | CEO / CFO | A / Ev | Capex | A, C | Utilização do gargalo, throughput perdido | Núcleo · onda 2 |

### Fora do escopo (R3)

| Decisão | Por quê |
|---|---|
| Método de previsão de demanda | Escolher método depende de série real. O sistema **armazena** a previsão como entrada marcada *estimado*, mas não a gera |
| Precificação | Não é decisão de operação; nenhuma ação de PPCP ou logística muda por ela |
| Avaliação de desempenho individual de colaborador | **[I]** Usar dado operacional para isso gera incentivo a mascarar registro (Deming, ponto 12). O colaborador entra como dimensão de **processo**, não de ranking |

## 5. Onda 1 — as 3 frentes (R5) [D]

| Frente | Decisões | Por que primeiro |
|---|---|---|
| 1. Estoque, lote e acuracidade | D04, D06, D07, D08 | **[I]** Todo o resto depende de saldo confiável. Sem acuracidade medida, D04 viola o antipadrão |
| 2. Planejamento de produção e compra | D01, D03, D05 | Primeira consumidora do saldo |
| 3. Ciclo do pedido e expedição | D14, D15 | Fecha o snapshot acumulado pedido → entrega |

D18 (fechamento) entra como **consumidor** da onda 1, sem frente própria: não cria captura nova, só lê o que as três frentes produzem.

## 6. Referências — onde falham aqui

- **Kimball:** a matriz de barramento parte dos processos de **uma** empresa. Num produto multiempresa, a dimensão "conformada" entre tenants é suposição. **[I]** Mitigação: conformidade garantida *dentro* do tenant; entre tenants só se compara métrica com definição idêntica.
- **Goldratt (TOC):** D01 e D21 assumem gargalo físico estável. **[I]** No arquétipo A a restrição pode ser a vida útil ou o mercado, e não a máquina. Por isso o modelo precisa permitir que o "recurso restritivo" seja configurável, não fixo.
- **Hopp & Spearman / EOQ:** o EOQ supõe demanda estável e custo de manter linear. Falha no perecível: o custo de manter salta no vencimento. Já tratado pelo teto de D03.
- **Anthony (operacional / tático / estratégico):** usei a classificação para cobrir os três níveis. Falha porque, em planta pequena, a mesma pessoa decide nos três níveis. O papel ≠ pessoa precisa estar no modelo.

## 7. Premissas assumidas (validar)

1. Os três arquétipos A, B e C representam o mercado-alvo. **[E]** Não tenho dado de mercado que confirme isso.
2. Os papéis da coluna "Decisor" existem como funções distintas. **[I]** Em operações pequenas, eles se acumulam numa pessoa só.
3. As frequências são típicas, não medidas. **[I]**
4. Stack: o repositório é um template Streamlit **[F]**. Nenhuma decisão de banco ou stack foi tomada; isso pertence a etapas posteriores.

## 8. Recalcular com dado real

Nada calculado nesta etapa. Bloco reservado.
