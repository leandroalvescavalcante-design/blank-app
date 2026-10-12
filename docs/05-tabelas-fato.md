# Etapa 5 — Tabelas Fato (onda 1)

**Entrada:** Etapas 0–4 aprovadas; regra de confiabilidade por fonte aprovada.
**Status:** proposta, aguardando validação. Especificação **lógica**: tipos genéricos, sem SGBD escolhido.

Legenda: **[F]** fato · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto · **[P]** valor que só vem do real.
Aditividade: **A** = soma em qualquer dimensão · **SA** = semiaditiva (não soma no tempo) · **NA** = não aditiva (razão, preço, flag).

---

## 0. Camada bruta (referenciada por todo fato) [D]

Append-only. Nada é atualizado ou apagado.

| Tabela | Uma linha = | Colunas |
|---|---|---|
| `bruto_carga` | um arquivo, chamada de API ou lote de formulários recebido | `carga_id`, empresa, fonte, sistema de origem, nome do arquivo, `hash_arquivo`, usuário, instante, `sintetico` (s/n) |
| `bruto_linha` | uma linha recebida, como veio | `carga_id`, nº da linha, `payload` (texto/JSON original), `chave_negocio`, `hash_linha`, `status_validacao`, `erro` |

**Idempotência:**
- Arquivo com o mesmo `hash_arquivo` → recusado como duplicado.
- Linha com `chave_negocio` já vista e mesmo `hash_linha` → ignorada.
- Mesma chave com hash diferente → **correção**: o fato recebe um estorno da versão anterior mais a versão nova.

## 1. Colunas comuns a todo fato [D]

| Coluna | Função |
|---|---|
| `empresa_sk`, `procedencia_sk` | tenant e fonte/confiabilidade (Etapa 4) |
| `carga_id`, `bruto_linha_id` | rastro até o bruto |
| `chave_negocio`, `hash_linha` | idempotência |
| `tipo_registro` | `normal`, `estorno`, `correcao`. Estorno tem medidas com sinal invertido |
| `sintetico` | herdado da carga. **Todo valor derivado de linha sintética nasce `provisorio = 1`** |

Quantidades sempre na **unidade base** do SKU; conversão só na camada semântica. Valores monetários na **moeda única do tenant** **[D]**.

## 2. Ajustes nas etapas anteriores, provocados por esta

1. **Nova dimensão pequena `dim_tipo_movimento`** (lista fechada): entrada por recebimento, entrada por produção, entrada por devolução, saída por expedição, saída por consumo, transferência (saída/entrada), ajuste (+/−), baixa. Atributos: sinal esperado, afeta disponível (s/n). **[I]** Sem ela, o razão F02 depende do motivo para saber se a quantidade entra ou sai, o que mistura "por quê" com "o quê".
2. **Contagem (F04) perde o motivo.** A causa da divergência é atribuída depois, na investigação, e entra no **ajuste** em F02 (ligado pelo nº da contagem). Manter o motivo em F04 exigiria atualizar a linha, o que viola a regra de estorno. A matriz da Etapa 1 muda: P04 × Motivo passa de X para ○.

---

## 3. Fatos transacionais

### F01 `fato_recebimento`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `sku_sk`, `lote_sk`, `local_sk` (endereço de destino), `parceiro_sk` (fornecedor), `colaborador_sk` (conferente), `motivo_sk` (recusa/divergência; `-2` se nenhum) |
| Degeneradas | nº recebimento, item, chave NF de entrada, nº PC + item (liga a F05) |
| Instante | `instante_conferencia` |
| Medidas | `qtd_esperada` A · `qtd_recebida` A · `qtd_recusada` A |

### F02 `fato_movimento_estoque` (razão)
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk` (dia operacional), `sku_sk`, `lote_sk`, `local_sk`, `tipo_movimento_sk`, `colaborador_sk`, `motivo_sk` |
| Degeneradas | tipo + nº do documento de origem (recebimento, OP, tarefa de separação, contagem, NF), item, sequência |
| Instante | `instante_movimento` |
| Medidas | `qtd` (com sinal) A · `custo_unit` NA · `valor` (= qtd × custo_unit) A |

- **[D]** `custo_unit` é lido do ERP no instante do movimento, não recalculado (Etapa 2, K08).
- Transferência = 2 linhas de soma zero (Etapa 3).
- Devolução de cliente entra aqui (`entrada por devolução`), ligada ao item de NF. É de onde sai a quantidade recusada por linha de pedido (ver F11).

### F04 `fato_contagem`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `sku_sk`, `lote_sk`, `local_sk`, `colaborador_sk` |
| Degeneradas | nº contagem, nº recontagem |
| Instantes | `instante_contagem`, `instante_congelamento` |
| Medidas | `qtd_contada` SA · `qtd_sistema_congelada` SA · `e_final` (s/n) NA |

- **[D]** O `acerto` de K01 **não é gravado**: é calculado na camada semântica com a tolerância vigente na data da contagem (parâmetro T2). Gravar fixaria a tolerância da época da carga, não a política daquela data.

### F06b `fato_apontamento`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `turno_sk`, `recurso_sk`, `sku_sk`, `lote_sk` (gerado), `colaborador_sk` (aceita `-1` na onda 1), `motivo_sk` (refugo) |
| Degeneradas | nº OP, nº apontamento |
| Instante | `instante_apontamento` |
| Medidas | `qtd_boa` A · `qtd_refugo` A |

Tempo de parada fica para a onda 2 (manutenção, D12), em fato próprio: uma parada tem início, fim e motivo, e não cabe em colunas do apontamento.

### F07 `fato_evento_pedido_venda`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_evento_sk`, `data_desejada_sk`, `cliente_sk`, `sku_sk`, `local_sk` (CD que atende), `motivo_sk` (cancelamento do cliente) |
| Degeneradas | nº pedido, item, nº evento, tipo de evento (criação, alteração, cancelamento) |
| Instante | `instante_evento` |
| Medidas | `delta_qtd` (com sinal) A |

- Quantidade pedida líquida = Σ `delta_qtd` da linha.
- **[D]** A demanda diária (d, σ_d) é datada pela **data desejada de entrega**, não pela data do evento. **[I]** É quando o estoque precisa existir. Contra: em pedidos com antecedência muito variável, a série por data desejada só fica completa depois que todos os pedidos daquela data chegaram. A data do evento fica gravada para permitir a troca.

### F08 `fato_separacao`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `sku_sk`, `lote_sk`, `local_sk` (endereço de retirada), `cliente_sk`, `colaborador_separador_sk`, `colaborador_conferente_sk`, `motivo_sk` |
| Degeneradas | nº tarefa, nº pedido, item, remessa |
| Instantes | `instante_separacao`, `instante_conferencia` |
| Medidas | `qtd_solicitada` A · `qtd_separada` A · `qtd_conferida` A |

**[I]** As três quantidades separam as etapas de K02 sem julgamento:
- `separada < solicitada` → faltou no endereço → **erro de saldo/endereçamento**.
- `conferida ≠ separada` → **erro de separação**.

### F09 `fato_faturamento`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `cliente_sk`, `sku_sk`, `local_sk` |
| Degeneradas | chave da NF, item, nº pedido, item do pedido, remessa |
| Instante | `instante_emissao` |
| Medidas | `qtd` A · `valor_mercadoria` A |

NF cancelada = estorno.

### F10a `fato_viagem`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk` (saída), `veiculo_sk`, `colaborador_sk` (motorista), `parceiro_sk` (transportadora), `local_sk` (site de origem) |
| Degeneradas | nº viagem |
| Instantes | `instante_saida`, `instante_retorno` |
| Medidas | `peso_kg` A · `volume_m3` A · `custo_viagem` A · `qtd_remessas` A |

- **[D]** Peso e volume são **calculados na carga** a partir das linhas e dos fatores de conversão **vigentes na data** (T2), com procedência `derivado`. Recalcular na consulta com o fator atual falsificaria K18 histórico.

### F10b `fato_entrega`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `cliente_sk`, `motivo_sk` (entrega frustrada) |
| Degeneradas | nº viagem, remessa, nº tentativa |
| Instantes | `instante_chegada`, `instante_conclusao` |
| Medidas | `status` (entregue, parcial, frustrada) NA · `e_ultima_tentativa` NA |

Recusa de linhas dentro da remessa não é medida aqui: aparece como devolução em F02. Assim F10b fica no grão aprovado (remessa × tentativa).

## 4. Fatos de snapshot periódico

### F03 `fato_saldo_diario`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `sku_sk`, `lote_sk`, `local_sk` |
| Instante | `instante_extracao` |
| Medidas | `qtd_fisica` SA · `qtd_bloqueada` SA · `qtd_reservada` SA · `custo_unit_medio` NA · `valor` SA · `dif_reconciliacao` SA |

**Ponto crítico [I]:** a reconciliação (K04) só tem sentido se F03 vier **de uma fonte independente** de F02. Se o saldo for calculado somando F02, a diferença é zero por construção e o indicador mente.
**[D]** Quando o tenant não tiver fonte de saldo independente, F03 é gerado de F02 com procedência `derivado`, e K04 aparece como **"não verificável"**, nunca como zero.

**Revisão após informação do usuário:** a maioria dos ERPs exporta o relatório de saldo por SKU e o extrato (kardex) por SKU. Isso resolve a existência da fonte, mas muda o que K04 mede:
- **[I]** No ERP, o relatório de saldo costuma ser calculado a partir da mesma tabela de movimentos do extrato. Os dois não são independentes **entre si**; são independentes **da nossa carga**.
- Portanto K04 mede a **integridade da carga contra o ERP**: movimento que não veio, arquivo cortado, corte de data diferente, lançamento retroativo. **Não** mede erro operacional (ERP × realidade física). Esse só a contagem (K01/K02) mede.
- **Lançamento retroativo:** um movimento lançado hoje com data de ontem muda o saldo de ontem. **[D]** F03 grava o `instante_extracao`; a reconciliação compara saldo e movimentos **do mesmo corte de extração**, e a diferença entre duas extrações do mesmo dia vira o indicador "retroativo" (alerta de fechamento, D18).
- **Grão da reconciliação:** **[I]** o relatório de saldo do ERP costuma vir por SKU × depósito, não por lote × endereço (isso é WMS). A reconciliação roda no **grão comum mais grosso** entre as duas fontes; abaixo dele, K04 é "não verificável".

### F06a `fato_programacao_op`
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `turno_sk`, `recurso_sk`, `sku_sk` |
| Degeneradas | nº OP, versão do programa, sequência no turno |
| Medidas | `qtd_programada` A · `tempo_padrao_min_un` NA · `setup_min` A · `congelada` (s/n) NA |

- **[D]** Tempo padrão e setup são **copiados** no momento da programação. A carga do recurso (K11) de um turno passado precisa usar o padrão daquele dia, não o atual.

### F12 `fato_planejamento_sku` (derivado)
| Tipo | Colunas |
|---|---|
| Dimensões | `data_sk`, `sku_sk`, `local_sk` |
| Medidas | `apto_reposicao` NA · `classe_abc` NA · `d` NA · `sigma_d` NA · `n_obs_demanda` NA · `L` NA · `sigma_L` NA · `n_obs_lead_time` NA · `z` NA · `metodo_ss` NA · `ss` SA · `rop` SA · `q_lote` NA · `teto_lote` NA · `alerta_lote_inviavel` NA · `cobertura_dias` NA · `dias_ate_ruptura` NA · `provisorio` NA |

- **[D] `n_obs_*` é obrigatório.** Um σ calculado com 5 observações não vale o mesmo que com 200. A tela mostra o n ao lado do número. Abaixo de um mínimo **[P]**, `provisorio = 1` mesmo com dado real.

## 5. Fatos de snapshot acumulado

### F05 `fato_pedido_compra_linha` (reconstruído do bruto)
| Tipo | Colunas |
|---|---|
| Dimensões | `sku_sk`, `local_sk` (destino), `parceiro_sk`, `motivo_sk` (cancelamento/alteração) |
| Datas (role-playing) | `data_emissao_sk`, `data_prevista_original_sk`, `data_prevista_atual_sk`, `data_primeiro_receb_sk`, `data_ultimo_receb_sk`, `data_encerramento_sk` |
| Degeneradas | nº PC, item |
| Medidas | `qtd_pedida` A · `qtd_recebida_acum` A · `qtd_cancelada` A · `status` NA |

### F11 `fato_ciclo_pedido` (derivado)
| Tipo | Colunas |
|---|---|
| Dimensões | `cliente_sk`, `sku_sk`, `local_sk`, `veiculo_sk` (última tentativa), `motivo_sk` (corte ou cancelamento) |
| Datas (role-playing) | `data_pedido_sk`, `data_prometida_sk`, `data_faturamento_sk`, `data_separacao_sk`, `data_carregamento_sk`, `data_entrega_sk` |
| Instantes | um por marco configurado pelo tenant |
| Degeneradas | nº pedido, item, remessa |
| Medidas | `qtd_alocada` A · `qtd_entregue` A (faturada − devolvida) · `status_final` NA (entregue, cortada, cancelada_cliente, em_aberto) · `no_prazo` NA · `completo` NA · `otif` NA · `versao_regra_otif` NA |

- **[I] Marco "carregamento":** poucos sistemas registram o fim do carregamento. Na ausência dele, uso `instante_saida` da viagem, com procedência `estimado`. Caso contrário, Δ(separação → carregamento) mede outra coisa sem aviso.
- `otif` é gravado com a **versão da regra** usada (Etapa 4, regra de OTIF T2 no tenant).

## 6. Posição contrária mais forte

**"Uma tabela única de eventos (event store, payload JSON) é mais flexível para um produto multiempresa do que 14 fatos tipados."**
É verdade para captura, e por isso a camada bruta é exatamente isso. Onde falha como modelo analítico: **[I]** cada consulta precisaria interpretar o payload, a tipagem e as unidades ficariam por conta de quem consulta, e duas pessoas calculariam o mesmo KPI de formas diferentes, que é o que a camada semântica existe para impedir.
**[D]** Bruto genérico e modelo dimensional tipado. Custo: um mapeamento bruto → fato por fonte, que precisa ser mantido.

## 7. Referências — onde falham aqui

- **Kimball (três tipos de fato, semiaditividade):** aplicado. Falha no snapshot acumulado atualizado no lugar (aqui é reconstruído) e em não tratar a reconciliação snapshot × transações como métrica de integridade. Aqui ela é o centro da frente 1.

## 8. O que não sei

1. **~~Fonte e formato do saldo/extrato~~ — resolvido.** Para o tenant de referência, o usuário monta os relatórios no formato que o produto pedir. **[D]** Para o produto, isso vira um **layout canônico de entrada** por fato (detalhado na Etapa 7), com adaptador por ERP. O produto nunca depende de alguém customizar o relatório do ERP para funcionar. Layout ideal desde já:
   - **Saldo:** uma linha por SKU × lote × endereço (ou SKU × depósito, se o ERP não tiver endereço), com `instante_extracao`, qtd física, bloqueada, reservada, custo unitário.
   - **Movimentos:** todos os SKUs do período num arquivo, uma linha por movimento, com tipo, documento de origem, lote, endereço, qtd com sinal, **data do movimento e instante do lançamento** (os dois: a diferença entre eles é o que revela o retroativo).
2. **Data da demanda (desejada × evento):** a escolha correta depende da distribuição da antecedência dos pedidos, que só vem do real.

## 9. Recalcular com dado real

| Item | Onde |
|---|---|
| Mínimo de observações para `provisorio = 0` | F12 |
| Escolha da data da demanda | F07 → F12 |
| Peso/volume (dependem dos fatores reais) | F10a |
| Tempo padrão e setup | F06a |
