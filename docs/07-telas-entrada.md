# Etapa 7 — Telas de Entrada (onda 1, frente 1)

**Entrada:** Etapas 0–6 aprovadas; stack aprovada para o protótipo: **Streamlit + DuckDB** (migração para PostgreSQL quando houver multiempresa real).
**Status:** construída e testada. Atualizações posteriores em [08-painel-e-fechamento.md](08-painel-e-fechamento.md).

Legenda: **[F]** fato · **[I]** inferência · **[E]** especulação · **[D]** decisão de projeto · **[P]** valor que só vem do real.

---

## 0. Escopo construído (WIP ≤ 3)

| Camada | O que existe | Onde |
|---|---|---|
| Contrato de entrada | 20 layouts canônicos, todos derivados de um fato ou dimensão. **11 implementados** (7 cadastros + 4 da frente 1); 9 especificados (frentes 2 e 3) | `entrada/layouts.yaml` |
| Bruto imutável | `bruto_carga`, `bruto_linha` (append-only, origem, instante, usuário) | `sql/bruto.sql` |
| Validação poka-yoke | tipo, faixa, lista fechada, referência a cadastro, regras entre campos, regras que dependem do cadastro | `app/validacao.py` |
| Carga idempotente | hash de conteúdo, classificação NOVA / REPETIDA / CORRECAO, tudo ou nada | `app/carga.py` |
| Modelo dimensional | dimensões, F02, F03, F04, cobertura de saldo, visões de reconciliação e de divergência pendente | `sql/modelo.sql`, `app/transform.py` |
| Telas | carga de arquivo, contagem cega, investigação de divergência, cargas e integridade, layouts | `streamlit_app.py`, `app/telas.py` |
| Dado sintético | cenário de 2 dias com 1 movimento faltante e 1 retroativo, marcado `sintetico` | `dados_sinteticos/gerar.py` |
| Testes | 24 testes de mecânica (idempotência, estorno, poka-yoke, fotografia, reconciliação, contagem, telas) | `tests/` |

**Telas derivam do fato, não o contrário:** cada campo de formulário ou coluna de arquivo existe porque uma coluna de fato ou dimensão precisa dele.

## 1. Fluxo

```
arquivo / formulário
   → validação (layouts.yaml)          ← mesma regra para os dois canais
   → bruto_carga + bruto_linha         ← grava tudo, inclusive o que foi recusado
   → reconstrução total do modelo      ← determinística; chaves substitutas = hash da chave natural
   → visões (reconciliação, divergências pendentes)
```

## 2. Decisões tomadas nesta etapa

1. **[D] Hash de conteúdo, não de arquivo.** O mesmo conteúdo em CSV, em XLSX ou com linhas em outra ordem é a mesma carga (teste `test_csv_e_xlsx_do_mesmo_conteudo_sao_a_mesma_carga`). O hash dos bytes deixaria passar o mesmo extrato salvo em outro formato.
2. **[D] Tudo ou nada.** Uma linha inválida recusa o arquivo inteiro. Contra: uma linha ruim bloqueia 10 mil boas. A favor: carga parcial de fotografia faz a linha ausente valer zero, e carga parcial de movimentos cria um buraco silencioso. Se a carga for registrada mesmo inválida, ela entra como RECUSADA no bruto (auditoria de tentativas).
3. **[D] Fotografia substitui por inteiro.** Um novo arquivo de saldo do mesmo site × dia substitui o anterior. Estorno linha a linha não expressa "esta linha sumiu, logo é zero". O histórico de versões fica no bruto e em `cobertura_saldo.versoes`. É um desvio declarado da regra de estorno (Etapa 3), restrito ao snapshot periódico.
4. **[D] Cobertura de saldo.** Ausência de linha só significa zero onde há fotografia daquele site e dia. Sem fotografia da véspera, K04 aparece como "não verificável" (R2: nulo com motivo).
5. **Reconciliação com lançamento retroativo.** A variação esperada entre duas fotografias soma os movimentos datados no dia e lançados até a extração, mais os **retroativos** lançados entre as duas extrações. No cenário sintético, o faltante (−48) é acusado e o retroativo (−12) não.
6. **Contagem cega com congelamento em dois passos.** "Iniciar" congela o saldo (última fotografia + movimentos lançados depois). Quem conta nunca vê o número do sistema, nem a diferença depois de registrar.
7. **Recontagem final é derivada**, não digitada: a de maior número por posição. Não há campo "é final?" para o operador julgar.
8. **A investigação atribui a etapa ao ajuste.** O ajuste que vier do ERP com documento `CONTAGEM` + número recebe o motivo da investigação; sem investigação, fica `DESCONHECIDO` (alimenta K02b).
9. **Membro inferido** para SKU e endereço vindos do ERP antes do cadastro. A tela "Cargas e integridade" lista os inferidos, ou seja, o que falta cadastrar.
10. **Referência fechada onde há julgamento:** motivo, colaborador e endereço de contagem só aceitam códigos cadastrados. SKU na contagem aceita **código de barras ou código**.

## 3. Dívida técnica declarada (o protótipo NÃO faz)

| Item | Consequência | Quando resolver |
|---|---|---|
| Histórico de versão (T2) nas dimensões | Fator de conversão e atributos de SKU valem pela versão atual; o histórico da Etapa 4 não está implementado | Antes de K18 (ocupação), que depende de fator histórico |
| ~~Tolerância de contagem~~ | **Resolvido na Etapa 8:** parâmetro do SKU; padrão por classe ABC (A 0%, B 2%, C 5%) por benchmark. A lista de divergências pendentes ainda usa tolerância zero (toda diferença é investigada) | — |
| Multiempresa e login | Uma empresa (`DEMO`); o usuário é digitado na barra lateral, sem autenticação | Migração para PostgreSQL |
| Reconstrução total a cada carga | Correto e simples; em volume real fica lento (hoje ≈ 1–2 s por carga no teste) **[I]** | Quando o volume real mostrar o gargalo: reconstrução incremental por fato |
| Confiabilidade de formulário | Fica MÉDIA: um campo web não distingue leitura de código de digitação | Integração com leitor/coletor |
| Exclusão no ERP | Movimento apagado no ERP (sem estorno) não é detectado pela ausência no extrato seguinte | Se o ERP apagar em vez de estornar; detectável por cobertura de período do extrato |
| ~~Frentes 2 e 3~~ | **Resolvido na Etapa 8** (autorização para concluir a ferramenta antes do dado real) | — |

## 4. Posição contrária mais forte

**"Começar a entrada pelo formulário de contagem é inverter a prioridade: o valor está no PPCP (frente 2), não em contar estoque."**
Por que mantive: **[I]** todo cálculo de reposição e de lote (K09, K10, K14) usa saldo. Sem acuracidade medida, o ponto de pedido fica nulo por construção (Etapa 2). A frente 1 é pré-requisito, não preferência. Custo: o primeiro valor visível ao gestor de PPCP demora mais uma etapa.

## 5. Como rodar

```
pip install -r requirements-dev.txt
streamlit run streamlit_app.py      # informe o usuário na barra lateral
python -m pytest tests              # 24 testes
python semantica/validar.py         # consistência da camada semântica
```
Para ver a mecânica sem dado real: tela **Cargas e integridade → Carregar cenário sintético**.

## 6. Recalcular com dado real

| Item | Onde |
|---|---|
| Tolerância de contagem (hoje 0) | `v_divergencias_pendentes`, K01 |
| Volume real de cargas (desempenho da reconstrução) | `app/transform.py` |
| Cenário sintético inteiro (quantidades, validades, custos) | `dados_sinteticos/gerar.py` — serve só para mecânica |
