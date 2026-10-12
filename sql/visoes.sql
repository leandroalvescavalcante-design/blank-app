-- Visões analíticas (camada de visão): cada uma expõe as colunas de dimensão padronizadas
-- (data, site, sku, familia, tipo_sku, ...) + procedência (fonte, confiabilidade, sintetico, provisorio)
-- + as medidas base que as métricas de semantica/metricas.yaml usam. Recriadas a cada reconstrução.
--
-- Regra de sinal: medidas de estorno já vêm negadas no fato; somar dá a versão vigente.
-- Valor absoluto por linha usa sinal * abs(valor), senão o estorno somaria em vez de anular (R3).

CREATE OR REPLACE VIEW vm_contagem AS
SELECT CAST(c.instante_contagem AS DATE) AS data, l.site, s.sku, s.familia, s.tipo AS tipo_sku,
       coalesce(lt.lote, '') AS lote, l.endereco, col.matricula AS colaborador,
       p.fonte, p.confiabilidade, c.sintetico, coalesce(pl.provisorio, true) AS provisorio,
       coalesce(pl.classe_abc, 'C') AS classe_abc,
       c.sinal AS den,
       c.sinal * CASE WHEN abs(c.qtd_contada - c.qtd_sistema_congelada)
                          <= coalesce(psl.tolerancia_contagem_pct,
                                      CASE coalesce(pl.classe_abc, 'C') WHEN 'A' THEN 0 WHEN 'B' THEN 0.02 ELSE 0.05 END)
                             * abs(c.qtd_sistema_congelada) + 1e-9
                      THEN 1 ELSE 0 END AS num
FROM fato_contagem c
JOIN dim_local l USING (local_sk)
JOIN dim_sku s USING (sku_sk)
LEFT JOIN dim_lote lt ON lt.lote_sk = c.lote_sk AND c.lote_sk > 0
LEFT JOIN dim_colaborador col USING (colaborador_sk)
LEFT JOIN dim_procedencia p USING (procedencia_sk)
LEFT JOIN parametro_sku_local psl ON psl.sku_sk = c.sku_sk AND psl.site = l.site
LEFT JOIN fato_planejamento_sku pl ON pl.sku_sk = c.sku_sk AND pl.site = l.site
                                   AND pl.data = CAST(c.instante_contagem AS DATE)
WHERE c.e_final;

CREATE OR REPLACE VIEW vm_mov AS
SELECT f.data_movimento AS data, l.site, s.sku, s.familia, s.tipo AS tipo_sku, coalesce(lt.lote, '') AS lote,
       l.endereco, tm.codigo AS tipo_movimento, tm.sinal_esperado, m.codigo AS motivo, m.etapa_origem,
       m.categoria_perda, p.fonte, p.confiabilidade, f.sintetico,
       false AS provisorio, f.retroativo, f.qtd, f.valor, f.sinal * abs(f.valor) AS valor_abs
FROM fato_movimento_estoque f
JOIN dim_local l USING (local_sk)
JOIN dim_sku s USING (sku_sk)
JOIN dim_tipo_movimento tm USING (tipo_movimento_sk)
LEFT JOIN dim_lote lt ON lt.lote_sk = f.lote_sk AND f.lote_sk > 0
LEFT JOIN dim_motivo m USING (motivo_sk)
LEFT JOIN dim_procedencia p USING (procedencia_sk);

CREATE OR REPLACE VIEW vm_saldo AS
SELECT f.data_saldo AS data, l.site, s.sku, s.familia, s.tipo AS tipo_sku, s.unidade_base,
       coalesce(lt.lote, '') AS lote, l.endereco, l.tipo AS tipo_local, p.fonte, p.confiabilidade, f.sintetico,
       false AS provisorio,
       CASE WHEN l.tipo = 'QUARENTENA' THEN 0 ELSE f.qtd_fisica - f.qtd_bloqueada - f.qtd_reservada END AS qtd_disponivel,
       f.qtd_fisica, f.valor
FROM fato_saldo_diario f
JOIN dim_local l USING (local_sk)
JOIN dim_sku s USING (sku_sk)
LEFT JOIN dim_lote lt ON lt.lote_sk = f.lote_sk AND f.lote_sk > 0
LEFT JOIN dim_procedencia p USING (procedencia_sk);

CREATE OR REPLACE VIEW vm_reconciliacao AS
SELECT c.data_saldo AS data, c.site, s.sku, s.familia, s.tipo AS tipo_sku, l.endereco,
       'ERP' AS fonte, 'ALTA' AS confiabilidade, c.sintetico, false AS provisorio,
       CASE WHEN abs(r.dif_reconciliacao) > 1e-6 THEN 1 ELSE 0 END AS excecao, r.dif_reconciliacao
FROM v_reconciliacao r
JOIN cobertura_saldo c ON c.site = r.site AND c.data_saldo = r.data_saldo
JOIN dim_sku s USING (sku_sk)
JOIN dim_local l USING (local_sk);

CREATE OR REPLACE VIEW vm_dias_verificaveis AS
SELECT c.site, c.data_saldo AS data, c.sintetico
FROM cobertura_saldo c JOIN cobertura_saldo p ON p.site = c.site AND p.data_saldo = c.data_saldo - 1;

CREATE OR REPLACE VIEW vm_planejamento AS
SELECT f.data, f.site, s.sku, s.familia, s.tipo AS tipo_sku, s.unidade_base, 'DERIVADO' AS fonte,
       CAST(NULL AS VARCHAR) AS confiabilidade, f.sintetico, f.provisorio, f.*
EXCLUDE (data, site, sintetico, provisorio, empresa, data_sk, sku_sk)
FROM fato_planejamento_sku f JOIN dim_sku s USING (sku_sk);

CREATE OR REPLACE VIEW vm_risco AS
SELECT f.data, f.site, s.sku, s.familia, s.tipo AS tipo_sku, coalesce(lt.lote, '') AS lote, 'DERIVADO' AS fonte,
       CAST(NULL AS VARCHAR) AS confiabilidade, f.sintetico, f.provisorio, f.data_validade, f.dias_vendaveis, f.saldo,
       f.consumivel, f.risco_qtd, f.risco_valor
FROM fato_risco_validade f
JOIN dim_sku s USING (sku_sk)
LEFT JOIN dim_lote lt ON lt.lote_sk = f.lote_sk;

-- K11: carga do recurso restritivo. O disponível pertence ao slot recurso × turno × dia (não ao SKU).
CREATE OR REPLACE VIEW vm_programacao AS
WITH prog AS (
    SELECT data, turno_sk, recurso_sk, bool_or(sintetico) AS sintetico,
           sum(qtd_programada * tempo_padrao_min_un + setup_min) AS min_programados
    FROM fato_programacao_op WHERE congelada GROUP BY ALL
)
SELECT p.data, r.site, r.recurso, t.turno, 'DERIVADO' AS fonte, CAST(NULL AS VARCHAR) AS confiabilidade, p.sintetico,
       false AS provisorio, p.min_programados AS num, t.horas_disponiveis * 60 AS den
FROM prog p JOIN dim_recurso r USING (recurso_sk) JOIN dim_turno t USING (turno_sk)
WHERE r.e_restritivo = 'S';

-- K12: aderência por OP × dia contra o programa CONGELADO; mín() antes de somar.
CREATE OR REPLACE VIEW vm_aderencia AS
WITH prog AS (
    SELECT numero_op, data, recurso_sk, turno_sk, sku_sk, bool_or(sintetico) AS sintetico, sum(qtd_programada) AS prog
    FROM fato_programacao_op WHERE congelada GROUP BY ALL
),
apo AS (SELECT numero_op, data, sum(qtd_boa) AS boa FROM fato_apontamento GROUP BY ALL)
SELECT p.data, r.site, r.recurso, t.turno, s.sku, s.familia, s.tipo AS tipo_sku, s.unidade_base,
       'DERIVADO' AS fonte, CAST(NULL AS VARCHAR) AS confiabilidade, p.sintetico, false AS provisorio,
       least(coalesce(a.boa, 0), p.prog) AS num, p.prog AS den
FROM prog p
LEFT JOIN apo a USING (numero_op, data)
JOIN dim_recurso r USING (recurso_sk) JOIN dim_turno t USING (turno_sk) JOIN dim_sku s USING (sku_sk)
WHERE p.prog > 0;

CREATE OR REPLACE VIEW vm_leadtime AS
SELECT r.data, pc.site, s.sku, s.familia, s.tipo AS tipo_sku, pa.cnpj AS parceiro, p.fonte, p.confiabilidade,
       r.sintetico, false AS provisorio,
       r.qtd_recebida * (r.data - pc.data_emissao) AS num, r.qtd_recebida AS den
FROM fato_recebimento r
JOIN fato_pedido_compra_linha pc ON pc.numero_pc = r.numero_pc AND pc.item = r.item_pc
JOIN dim_sku s ON s.sku_sk = r.sku_sk
JOIN dim_parceiro pa ON pa.parceiro_sk = r.parceiro_sk
LEFT JOIN dim_procedencia p ON p.procedencia_sk = r.procedencia_sk;

-- K15: OTIF por LINHA de pedido (todas as remessas OK; corte reprova). Linhas não vencidas ficam fora.
CREATE OR REPLACE VIEW vm_ciclo_linha AS
SELECT f.data_prometida AS data, f.site, s.sku, s.familia, s.tipo AS tipo_sku, c.cliente, 'DERIVADO' AS fonte,
       CAST(NULL AS VARCHAR) AS confiabilidade, bool_or(f.sintetico) AS sintetico, false AS provisorio,
       f.numero_pedido, f.item, CASE WHEN bool_and(f.otif) THEN 1 ELSE 0 END AS num, 1 AS den,
       max(f.versao_regra_otif) AS versao_regra_otif
FROM fato_ciclo_pedido f JOIN dim_sku s USING (sku_sk) JOIN dim_cliente c USING (cliente_sk)
WHERE f.status_final != 'cancelada_cliente'
GROUP BY ALL
HAVING NOT bool_or(f.remessa = 'PENDENTE');

-- K16: fill rate (quantidade entregue / quantidade da linha); corte por motivo.
CREATE OR REPLACE VIEW vm_ciclo AS
SELECT f.data_prometida AS data, f.site, s.sku, s.familia, s.tipo AS tipo_sku, s.unidade_base, c.cliente,
       m.codigo AS motivo, f.status_final, 'DERIVADO' AS fonte, CAST(NULL AS VARCHAR) AS confiabilidade, f.sintetico,
       false AS provisorio, f.qtd_entregue AS num, f.qtd_alocada AS den
FROM fato_ciclo_pedido f JOIN dim_sku s USING (sku_sk) JOIN dim_cliente c USING (cliente_sk)
LEFT JOIN dim_motivo m USING (motivo_sk)
WHERE f.status_final != 'cancelada_cliente' AND f.remessa != 'PENDENTE';

-- K17: duração de cada etapa (ordem padrão: pedido → separação → faturamento → carregamento → entrega).
CREATE OR REPLACE VIEW vm_etapas AS
WITH base AS (
    SELECT f.*, s.sku, s.familia, s.tipo AS tipo_sku, c.cliente, v.placa AS veiculo
    FROM fato_ciclo_pedido f JOIN dim_sku s USING (sku_sk) JOIN dim_cliente c USING (cliente_sk)
    LEFT JOIN dim_veiculo v USING (veiculo_sk)
    WHERE f.status_final = 'entregue'
)
SELECT data_entrega AS data, site, sku, familia, tipo_sku, cliente, veiculo, 'DERIVADO' AS fonte,
       CAST(NULL AS VARCHAR) AS confiabilidade, sintetico, false AS provisorio, carregamento_estimado AS estimado, etapa, horas
FROM (
    SELECT *, '1 pedido→separação' AS etapa, epoch(instante_separacao - instante_pedido) / 3600 AS horas FROM base
    UNION ALL SELECT *, '2 separação→faturamento', epoch(instante_faturamento - instante_separacao) / 3600 FROM base
    UNION ALL SELECT *, '3 faturamento→carregamento', epoch(instante_carregamento - instante_faturamento) / 3600 FROM base
    UNION ALL SELECT *, '4 carregamento→entrega', epoch(instante_entrega - instante_carregamento) / 3600 FROM base
    UNION ALL SELECT *, '0 ciclo total', epoch(instante_entrega - instante_pedido) / 3600 FROM base
) WHERE horas IS NOT NULL;

-- K18: ocupação por viagem = máx(peso/cap_kg, volume/cap_m³); acima da viagem, média simples (exceção à R4).
CREATE OR REPLACE VIEW vm_viagem AS
WITH v AS (
    SELECT numero_viagem, data, site, veiculo_sk, parceiro_sk, bool_or(sintetico) AS sintetico,
           sum(peso_kg) AS peso_kg, sum(volume_m3) AS volume_m3, sum(custo_viagem) AS custo
    FROM fato_viagem GROUP BY ALL
)
SELECT v.data, v.site, ve.placa AS veiculo, coalesce(pa.cnpj, 'PROPRIA') AS parceiro, 'DERIVADO' AS fonte,
       CAST(NULL AS VARCHAR) AS confiabilidade, v.sintetico, false AS provisorio, v.numero_viagem, v.peso_kg, v.volume_m3, v.custo,
       greatest(v.peso_kg / ve.cap_kg, v.volume_m3 / ve.cap_m3) AS ocupacao
FROM v JOIN dim_veiculo ve USING (veiculo_sk) LEFT JOIN dim_parceiro pa ON pa.parceiro_sk = v.parceiro_sk;

-- K19: frete por kg; rateio em dois estágios (benchmark): custo da viagem igual por parada, e na parada por peso.
CREATE OR REPLACE VIEW vm_frete AS
WITH ent AS (
    SELECT DISTINCT e.numero_viagem, e.remessa, e.cliente_sk
    FROM fato_entrega e WHERE e.tipo_registro != 'ESTORNO'
),
kg AS (
    SELECT ent.numero_viagem, ent.cliente_sk, sum(f.qtd * s.peso_bruto_kg_un_base) AS kg
    FROM ent JOIN fato_faturamento f ON f.remessa = ent.remessa JOIN dim_sku s ON s.sku_sk = f.sku_sk
    GROUP BY ALL
),
paradas AS (SELECT numero_viagem, count(DISTINCT cliente_sk) AS n FROM ent GROUP BY ALL)
SELECT v.data, v.site, v.veiculo, v.parceiro, c.cliente, v.fonte, v.confiabilidade, v.sintetico, v.provisorio,
       v.custo / p.n AS num, kg.kg AS den
FROM vm_viagem v
JOIN paradas p USING (numero_viagem)
JOIN kg USING (numero_viagem)
JOIN dim_cliente c ON c.cliente_sk = kg.cliente_sk;
