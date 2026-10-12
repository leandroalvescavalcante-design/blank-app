# Etapa 6 — Camada Semântica (onda 1)

**Entrada:** Etapas 0–5 aprovadas.
**Status:** proposta, aguardando validação.

Legenda: **[F]** fato · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto · **[P]** valor que só vem do real.

---

## 0. Onde mora a definição [D]

**`semantica/metricas.yaml` é a fonte única.** Toda métrica tem ali fórmula, unidade, dono, decisões, dimensões permitidas, data padrão e direção. Em conflito com `docs/02-kpis-formulas.md`, o YAML vence; o documento guarda só a justificativa.

Três níveis, e cada nível só pode usar o de baixo:

| Nível | O que é | Exemplo |
|---|---|---|
| **Funções compartilhadas** | regra de negócio usada por várias métricas | `validade_minima(cliente, sku, data)` |
| **Medidas base** | ligação direta com coluna de fato, com filtro e regra de agregação | `acertos_contagem` |
| **Métricas** | fórmula sobre medidas base e funções | K01 = `acertos_contagem / posicoes_contadas` |

`semantica/validar.py` checa a mecânica: campos obrigatórios, listas fechadas, referências existentes, diagnóstico sem meta e decisão da onda 1 sem métrica. Resultado atual: **20 métricas, 27 medidas base, 7 funções, todas as decisões da onda 1 cobertas.**

## 1. Regras globais

| # | Regra | Por quê |
|---|---|---|
| **R1** | **Uma métrica, uma definição.** Tela, relatório e exportação leem o YAML; ninguém reescreve fórmula | Duas fórmulas para o mesmo nome é a origem de "o meu número não bate com o seu" |
| **R2** | **Resultado indisponível é NULO com motivo**, nunca zero (`sem contagem`, `não verificável`, `acuracidade desconhecida`, `sem demanda`) | Zero é um valor; um zero falso parece bom resultado |
| **R3** | **Contagem é soma de `sinal`**, nunca `count(*)` | Estornos e correções duplicariam linhas contadas |
| **R4** | **Razão é razão das somas**, nunca média das razões. Exceção declarada: K18 (kg e m³ não somam) | **[F]** A média das razões dá o mesmo peso a um site com 10 contagens e a outro com 10.000 |
| **R5** | **Medida semiaditiva** (saldo, valor de estoque) no tempo usa **o último dia do período**. Saldo médio é métrica separada, se alguém pedir | Somar saldo de 30 dias dá 30 vezes o estoque |
| **R6** | **Percentil não se agrega.** Mediana e P90 (K17) são recalculados das linhas atômicas a cada nível de drill | **[F]** A mediana das medianas não é a mediana do conjunto |
| **R7** | **Quantidade entre SKUs só em unidade comum** (kg, m³, moeda ou caixa-equivalente declarada). Soma em `un` através de SKUs com unidades base diferentes é bloqueada | Somar "unidades" de iogurte e de saco de 25 kg não significa nada |
| **R8** | **Procedência propaga.** Todo resultado carrega a **menor** confiabilidade entre as linhas usadas e o **% vindo de `estimado`**. O gráfico marca quando há mistura | Invariante do briefing: não misturar fontes sem marcar |
| **R9** | **Provisório propaga.** Qualquer linha `sintetico = 1`, parâmetro não calibrado ou n abaixo do mínimo deixa o resultado `provisorio = 1` | Regra do dado fictício |
| **R10** | **Mudança de definição = nova versão** do YAML (`versao_camada`). Série histórica comparada entre versões diferentes aparece com quebra marcada | Mudar a fórmula em silêncio reescreve o passado |

## 2. Decisões que não são óbvias

1. **Métricas com termo não linear declaram `grao_calculo`.** K12 calcula `mín(produzido, programado)` por OP × dia antes de somar. Somar primeiro e tirar o mínimo depois deixaria o excesso de uma OP compensar a falta de outra, exatamente o que o `mín()` existe para impedir.
2. **OTIF (K15) é por linha de pedido, não por remessa.** F11 está no grão linha × remessa; a linha só conta como OK se **todas** as suas remessas forem OK. A remessa de corte tem `otif = 0`, então o corte reprova a linha.
3. **`meta: proibida`** em K01, K02 e K03. O validador recusa meta em métrica de diagnóstico. É o antipadrão "acuracidade como meta" impedido por construção, não por recomendação.
4. **K04 tem `aviso_exibicao` obrigatório:** "mede a integridade da carga contra o ERP, não a acuracidade física" (revisão da Etapa 5).
5. **Validade mínima em métrica por SKU × local** (K05, K10) usa o cliente **mais restritivo** que pediu o SKU naquele local numa janela **[P]**. A regra de precedência (acordo > cliente > SKU) fica numa única função.
6. **Dono = papel que responde pela métrica**: aprova mudança de definição e age sobre o resultado. A guarda técnica de todas é da engenharia de dados.

## 3. Posição contrária mais forte

**"Uma ferramenta de BI pronta (Power BI, Looker, dbt Semantic Layer) já é camada semântica. Escrever YAML próprio é reinventar."**
É o argumento certo para um sistema de uma empresa. Onde falha aqui: **[I]** o produto ficaria preso à ferramenta, e regras como R2 (nulo com motivo), R8 (procedência propagada) e R9 (provisório propagado) não existem como recurso nativo dessas ferramentas; teriam que ser reimplementadas em cada uma.
**[D]** O YAML é a **especificação**; quando a stack for escolhida, ele pode ser traduzido para a camada semântica da ferramenta (dbt, por exemplo) em vez de concorrer com ela. Custo: um tradutor a manter.

## 4. Referências — onde falham aqui

- **Kimball (fatos semiaditivos, métricas conformadas):** R3–R5 vêm dele. Falha por não tratar procedência e provisório como atributos do resultado; aqui são obrigatórios (R8, R9).
- **Goodhart / Deming:** viram regra executável (`meta: proibida`, checada pelo validador). Falha se alguém publicar a meta fora do sistema, numa planilha. Nenhum controle técnico impede isso.

## 5. O que não sei

1. **Janela de "clientes ativos"** para a validade mínima por SKU × local. Curta demais esquece cliente sazonal; longa demais mantém um cliente perdido travando o lote. Só o histórico real de pedidos mostra a frequência de compra.
2. **Rateio do frete por cliente (K19).** Usei peso entregue. **[I]** Em rota com muita parada pequena, o custo é puxado pelo número de paradas, não pelo peso, e o rateio por peso subsidia o cliente pequeno. A regra correta depende da estrutura de custo da frota.

## 6. Recalcular com dado real

| Parâmetro | Métrica |
|---|---|
| `janela_clientes_ativos` | K05, K10 |
| `limiar_k02b` | K02b |
| `n_min` (observações para sair de provisório) | K09 e derivadas |
| `z`, `metodo_ss` | K09 |
| `S`, `H`, `dias_parados`, `transito` | K10 |
| `janela_lead_time` | K13 |
| `limiar_ocupacao` | K18 |
| Regra de rateio do frete | K19 |
