-- Modelo dimensional (frente 1). Recriado a cada reconstrução a partir do bruto (app/transform.py).
-- Nada aqui é digitado: toda linha nasce da camada bruta.

CREATE OR REPLACE TABLE dim_procedencia (procedencia_sk BIGINT, fonte VARCHAR, confiabilidade VARCHAR);

CREATE OR REPLACE TABLE dim_site (site_sk BIGINT, empresa VARCHAR, site VARCHAR, descricao VARCHAR, horario_corte VARCHAR);

CREATE OR REPLACE TABLE dim_local (
    local_sk BIGINT, empresa VARCHAR, endereco VARCHAR, site VARCHAR, zona VARCHAR, tipo VARCHAR,
    classe_temperatura VARCHAR, inferido BOOLEAN);

CREATE OR REPLACE TABLE dim_sku (
    sku_sk BIGINT, empresa VARCHAR, sku VARCHAR, descricao VARCHAR, tipo VARCHAR, familia VARCHAR,
    unidade_base VARCHAR, controla_lote VARCHAR, shelf_life_dias INTEGER, validade_minima_padrao_dias INTEGER,
    classe_temperatura VARCHAR, peso_bruto_kg_un_base DOUBLE, volume_m3_un_base DOUBLE, codigo_barras VARCHAR,
    inferido BOOLEAN);

CREATE OR REPLACE TABLE sku_unidade (sku_sk BIGINT, unidade VARCHAR, fator_para_base DOUBLE, e_unidade_palete VARCHAR);

CREATE OR REPLACE TABLE dim_lote (
    lote_sk BIGINT, empresa VARCHAR, sku_sk BIGINT, sku VARCHAR, lote VARCHAR, data_fabricacao DATE,
    data_validade DATE, origem_validade VARCHAR);

CREATE OR REPLACE TABLE dim_motivo (
    motivo_sk BIGINT, empresa VARCHAR, codigo VARCHAR, descricao VARCHAR, processo VARCHAR, etapa_origem VARCHAR,
    gera_baixa VARCHAR, categoria_perda VARCHAR, controlavel VARCHAR, origem VARCHAR);

CREATE OR REPLACE TABLE dim_colaborador (
    colaborador_sk BIGINT, empresa VARCHAR, matricula VARCHAR, funcao VARCHAR, turno VARCHAR, site VARCHAR);

CREATE OR REPLACE TABLE dim_tipo_movimento (
    tipo_movimento_sk BIGINT, codigo VARCHAR, sinal_esperado INTEGER, afeta_disponivel BOOLEAN);

CREATE OR REPLACE TABLE dim_data (
    data_sk INTEGER, data DATE, ano INTEGER, mes INTEGER, dia INTEGER, trimestre INTEGER,
    dia_semana_iso INTEGER, semana_iso INTEGER, ano_iso INTEGER);

CREATE OR REPLACE TABLE aux_investigacao (
    numero_contagem VARCHAR, endereco VARCHAR, sku VARCHAR, lote VARCHAR, motivo VARCHAR, matricula VARCHAR,
    instante TIMESTAMP);

-- F02: razão de movimentos (transacional). Estorno/correção com sinal; soma por chave = última versão.
CREATE OR REPLACE TABLE fato_movimento_estoque (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data_movimento DATE, data_sk INTEGER, instante_lancamento TIMESTAMP, retroativo BOOLEAN,
    sku_sk BIGINT, lote_sk BIGINT, local_sk BIGINT, tipo_movimento_sk BIGINT, motivo_sk BIGINT,
    documento_tipo VARCHAR, documento_numero VARCHAR, item INTEGER, sequencia INTEGER,
    qtd DOUBLE, custo_unit DOUBLE, valor DOUBLE);

-- F03: fotografia diária (snapshot periódico, esparso, semiaditivo).
CREATE OR REPLACE TABLE fato_saldo_diario (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    sintetico BOOLEAN, data_saldo DATE, data_sk INTEGER, instante_extracao TIMESTAMP,
    sku_sk BIGINT, lote_sk BIGINT, local_sk BIGINT,
    qtd_fisica DOUBLE, qtd_bloqueada DOUBLE, qtd_reservada DOUBLE, custo_unit_medio DOUBLE, valor DOUBLE);

-- Cobertura: quais site × dia têm fotografia (ausência de linha só significa zero onde há cobertura).
CREATE OR REPLACE TABLE cobertura_saldo (
    site VARCHAR, data_saldo DATE, instante_extracao TIMESTAMP, carga_id BIGINT, sintetico BOOLEAN, versoes INTEGER);

-- F04: contagem cega por posição (transacional).
CREATE OR REPLACE TABLE fato_contagem (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    numero_contagem VARCHAR, numero_recontagem INTEGER, e_final BOOLEAN, data_sk INTEGER,
    instante_contagem TIMESTAMP, instante_congelamento TIMESTAMP,
    sku_sk BIGINT, lote_sk BIGINT, local_sk BIGINT, colaborador_sk BIGINT,
    qtd_contada DOUBLE, qtd_sistema_congelada DOUBLE);
