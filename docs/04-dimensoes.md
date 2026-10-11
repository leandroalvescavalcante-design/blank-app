# Etapa 4 — Dimensões Conformadas (onda 1)

**Entrada:** Etapas 0–3 aprovadas; identificador de remessa gerado pelo produto (por ordem de separação; por NF quando não houver ordem).
**Status:** proposta, aguardando validação.

Legenda: **[F]** fato · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto · **[P]** valor que só vem do real.
SCD (*slowly changing dimension*): **T1** = sobrescreve, sem histórico · **T2** = nova versão com vigência · **T0** = imutável.

---

## 0. Regras comuns [D]

1. **Chave substituta** (inteira, global) em toda dimensão. A **chave natural** é única **dentro do tenant**. Duas empresas podem ter o SKU "1001" sem colisão.
2. **Isolamento por tenant:** toda dimensão carrega `empresa_sk`. Conformidade vale dentro do tenant (Etapa 1).
3. **Membros especiais** em toda dimensão: `-1 desconhecido` (a origem não informou) e `-2 não se aplica` (ex.: lote em SKU sem controle de lote). Fato nunca tem chave nula.
4. **Membro inferido:** se o fato chega antes do cadastro (SKU novo), cria-se uma linha `inferido = 1` com só a chave natural. O cadastro, quando chegar, completa a linha (T1) em vez de criar outra. **[I]** Sem isso, ou a carga rejeita o fato (perde dado) ou o carrega no `-1` (perde rastro).
5. **R4 continua valendo:** cada atributo abaixo cita a métrica ou decisão que o consome. Atributo sem consumidor não entra.
6. **Classificação derivada não é atributo de dimensão.** Classe ABC, aptidão para reposição e cobertura são calculadas e mudam com a medida; ficam no fato F12 (planejamento), com data. **[I]** Pôr ABC na dimensão SKU como T2 gera uma versão nova do SKU a cada reclassificação mensal.

## 1. Dimensões

### D-01 `dim_empresa` (tenant)
| Atributo | SCD | Consumidor |
|---|---|---|
| código, razão social | T1 | isolamento, rótulos |
| fuso horário padrão | T1 | dia operacional (Etapa 3, regra 3) |
| mês de início do ano fiscal | T2 | mês fiscal no calendário |
| regra de OTIF (janela, tolerância) | T2 | K15 — comparação só entre tenants com regra igual |

### D-02 Calendário — duas tabelas
**`dim_data`** (global, T0) — uma linha = um dia civil.
Atributos: data, dia da semana, semana ISO, ano ISO, mês, trimestre, ano, feriado nacional. **[F]** A semana ISO 8601 começa na segunda e a semana 1 contém a primeira quinta-feira do ano; o ano ISO difere do civil nos dias de borda.

**`dim_calendario_operacional`** — uma linha = um dia × site do tenant.
| Atributo | SCD | Consumidor |
|---|---|---|
| dia útil (s/n) | T1 | K13 (opção dias úteis), K17 |
| feriado local (municipal/estadual) | T1 | dia útil |
| mês fiscal, ano fiscal | T1 | D18 |
| horário de corte do dia operacional | T2 | F03 (saldo no corte) |

**`dim_turno`** (satélite) — uma linha = um turno de um site.
Atributos: código, início, fim, horas disponíveis. Consumidor: K11 (tempo disponível), F06a.
Exceção por dia (turno extra, parada programada) fica numa tabela de **calendário de recurso** (recurso × dia × turno × horas), não na dimensão.

### D-03 `dim_sku`
| Atributo | SCD | Consumidor |
|---|---|---|
| código, descrição | T1 | rótulo |
| tipo (MP, PA, embalagem, revenda) | T1 | filtro por arquétipo |
| família | T2 | matriz de setup (K11), MPS (onda 2) |
| unidade base | T0 | todas as quantidades |
| controla lote (s/n) | T2 | `-2 não se aplica` em lote |
| shelf life (dias) | T2 | K05, K10 |
| validade mínima padrão (dias) | T2 | fallback de K05/K10 (ver §2) |
| classe de temperatura | T2 | compatibilidade com veículo (D14) |
| peso bruto por unidade base (kg) | T2 | K18, K19 |
| volume por unidade base (m³) | T2 | K18 |

**Fatores de conversão** — tabela ponte `sku_unidade` (uma linha = um SKU × unidade de medida, T2):
`unidade ∈ {un, cx, fardo, palete, kg, …}`, `fator_para_base`, `é_unidade_de_palete`.
- **[D] Por que ponte e não colunas fixas (un/cx, cx/palete):** produto genérico. Há SKUs com fardo, display ou caixa master. Coluna fixa obriga o tenant a encaixar o que não cabe.
- **Poka-yoke:** `fator > 0`; o palete deve ser múltiplo inteiro da caixa; peso e volume do palete são conferidos contra a soma das caixas, com tolerância.
- **[I] Por que T2:** troca de embalagem muda caixas por palete. Recalcular a ocupação de viagens antigas (K18) com o fator novo falsifica o histórico.

### D-04 `dim_lote`
Uma linha = um lote de um SKU. Chave natural: SKU + nº lote (o mesmo nº pode existir em SKUs diferentes).
| Atributo | SCD | Consumidor |
|---|---|---|
| nº lote | T0 | rastreio |
| data de fabricação | T0 | rastreio |
| data de validade | T0* | K05 |
| origem (parceiro ou OP) | T0 | diagnóstico de qualidade (onda 2) |

\* Correção de validade digitada errada gera nova versão marcada `correção`, nunca sobrescrita. **[I]** Validade alterada sem rastro é exatamente como se esconde vencimento.
O **status de qualidade** (liberado/retido) é estado, não atributo: aparece como quantidade bloqueada no saldo (F03).

### D-05 `dim_local`
Uma linha = um endereço. Hierarquia: empresa → site → zona → endereço.
| Atributo | SCD | Consumidor |
|---|---|---|
| site, zona, código do endereço | T1 | drill, filtro |
| tipo (picking, pulmão, doca, quarentena, expedição, produção) | T2 | saldo disponível (quarentena ≠ disponível), K02 (etapa de origem) |
| classe de temperatura | T2 | compatibilidade SKU × endereço |

Capacidade de endereço e distância de picking ficam fora: só servem a D09 (slotting), que é extensão.

### D-06 `dim_cliente`
| Atributo | SCD | Consumidor |
|---|---|---|
| código, nome | T1 | rótulo |
| ponto de entrega (lat, long, município, UF) | T2 | D14 (roteiro); T2 para não mover entregas antigas de lugar |
| janela de entrega (início, fim) | T2 | K15, D14 |
| prioridade de atendimento | T2 | D15 (quem é cortado primeiro) |
| validade mínima aceita (dias) | T2 | K05, K10 (ver §2) |

### D-07 `dim_parceiro` (fornecedor + transportadora)
| Atributo | SCD | Consumidor |
|---|---|---|
| CNPJ, razão social | T1 | rótulo, conformidade |
| papéis (fornecedor, transportadora) | T1 | role-playing em F01/F05 × F10 |

**Condição de fornecimento** — ponte `parceiro_sku` (uma linha = um parceiro × SKU, T2): lote mínimo, múltiplo de compra, lead time contratado. Consumidor: K10 (alerta "teto < lote mínimo"), K13 (contratado × realizado).

### D-08 `dim_recurso`
| Atributo | SCD | Consumidor |
|---|---|---|
| código, descrição, site | T1 | rótulo |
| tipo (linha, máquina, célula) | T1 | filtro |
| é restritivo (s/n) | T2 | K11; **configurável** (Etapa 0, Goldratt) |

**Matriz de setup** — tabela de referência (recurso × família de origem × família de destino → minutos, T2). Consumidor: K11. **[P]** Valores só vêm de cronoanálise ou apontamento.

### D-09 `dim_veiculo`
| Atributo | SCD | Consumidor |
|---|---|---|
| placa, tipo | T1 | rótulo |
| capacidade kg, capacidade m³ | T2 | K18 |
| classe de temperatura (seco, refrigerado, congelado) | T2 | D14 |
| própria / terceira, transportadora (→ parceiro) | T2 | K19 |

### D-10 `dim_colaborador`
| Atributo | SCD | Consumidor |
|---|---|---|
| matrícula | T0 | chave |
| função (conferente, separador, operador, motorista…) | T2 | K02, F10 |
| turno, site | T2 | K02 por turno |

- **[F]** Nome e documento de colaborador são dados pessoais pela LGPD (Lei 13.709/2018), que exige finalidade e minimização.
- **[D]** Não armazena CPF. Nome é opcional e fica fora da camada analítica. Nenhum atributo de avaliação (exclusão da Etapa 0).

### D-11 `dim_motivo`
Uma linha = um motivo de uma lista fechada.
| Atributo | SCD | Consumidor |
|---|---|---|
| código, descrição | T1 | rótulo |
| processo aplicável (recebimento, contagem, ajuste, corte, parada, devolução, entrega frustrada…) | T1 | poka-yoke: a tela só oferece os motivos do processo |
| etapa de origem (recebimento, endereçamento, separação, conferência, desconhecida) | T1 | K02, K02b |
| gera baixa (s/n) e categoria de perda (vencimento, avaria, ajuste, outro) | T1 | K06 |
| controlável (s/n) | T1 | D11 (onda 2) |

**[D]** "Outro" com texto livre **não existe**. Se a lista não cobre o caso, ele vai para `desconhecido`, que aparece em K02b como sinal de lista incompleta. **[I]** Campo livre vira o motivo mais usado em semanas.

### D-12 `dim_procedencia` (junk)
Uma linha = uma combinação de:
| Atributo | Valores |
|---|---|
| fonte | ERP, formulário, upload, estimado, derivado |
| sistema de origem | código configurável por tenant |
| confiabilidade | alta, média, baixa |

**[D] Confiabilidade é atribuída por regra, nunca por julgamento.** Proposta inicial: ERP com integração = alta; formulário com leitura de código = alta; formulário digitado = média; upload de planilha = média; estimado = baixa; derivado herda a **menor** confiabilidade entre as fontes de entrada.

## 2. Validade mínima aceita — pendência da Etapa 1, resolvida
Precedência, da mais específica para a mais geral:
```
validade_mínima(cliente, SKU) =
    acordo_cliente_sku.dias          se existir    (ponte cliente × SKU, T2)
    senão dim_cliente.validade_mínima se preenchida
    senão dim_sku.validade_mínima_padrão
```
**[I]** Atende os dois casos sem obrigar nenhum tenant a cadastrar a ponte. Custo: três lugares para olhar; a camada semântica (Etapa 6) define essa regra **uma vez**, numa função única.

## 3. Parâmetros de planejamento (configuração, não dimensão)
Tabela `parametro_sku_local` (uma linha = SKU × local, T2):
nível de serviço (z), método de SS, dias parados, trânsito típico, custos S e H, tolerância de contagem.
São **entradas** do gestor ([P]). Os valores **calculados** a partir deles (SS, ROP, Q) ficam em F12, com data.

## 4. Remessa
Dimensão **degenerada** em F08, F09, F10b e F11: só identificador, sem atributos próprios. Gerada pelo produto conforme aprovado (ordem de separação; NF quando não houver ordem).

## 5. Posição contrária mais forte

**"T2 em tudo: auditoria completa, nunca se perde histórico."**
Por que não: **[I]** cada atributo T2 multiplica versões e obriga toda junção a filtrar por vigência; um erro de digitação corrigido vira "histórico" falso. **[D]** T2 só onde mudar o valor muda a leitura de fatos passados (fator de conversão, capacidade, janela, validade mínima). O histórico completo de qualquer alteração continua no bruto imutável. Custo: quem quiser auditar um T1 tem que ir à camada bruta.

## 6. Referências — onde falham aqui

- **Kimball (dimensões conformadas, junk, role-playing, membro inferido):** usado como está. Falha em supor conformidade empresa inteira; aqui é por tenant. E falha em tratar classificações derivadas (ABC) como atributo T2; aqui vão para o fato (regra 6).

## 7. O que não sei

1. **Se a confiabilidade "upload = média" é justa.** Uma planilha exportada do ERP é mais confiável que uma digitada, e o sistema não distingue as duas pelo canal. **[E]** Talvez precise de um campo "planilha gerada por sistema" declarado no upload, mas isso é julgamento do usuário, o que o poka-yoke proíbe. Sem dado real de taxa de erro por canal, não sei calibrar.
2. **Granularidade de temperatura** (3 classes) — suficiente para alimentos; **[E]** farmacêutico exige faixas numéricas e registro contínuo, que é outro escopo.

## 8. Recalcular com dado real
Nenhum cálculo. Valores [P]: matriz de setup, parâmetros de `parametro_sku_local`, validade mínima por cliente/SKU, condições de fornecimento.
