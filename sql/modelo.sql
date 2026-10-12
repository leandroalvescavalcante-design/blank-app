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

-- ============================================================ frentes 2 e 3

CREATE OR REPLACE TABLE dim_calendario_operacional (site VARCHAR, data DATE, dia_util BOOLEAN);

CREATE OR REPLACE TABLE dim_cliente (
    cliente_sk BIGINT, empresa VARCHAR, cliente VARCHAR, nome VARCHAR, municipio VARCHAR, uf VARCHAR,
    latitude DOUBLE, longitude DOUBLE, janela_inicio VARCHAR, janela_fim VARCHAR, prioridade INTEGER,
    validade_minima_dias INTEGER);

CREATE OR REPLACE TABLE dim_parceiro (
    parceiro_sk BIGINT, empresa VARCHAR, cnpj VARCHAR, razao_social VARCHAR, e_fornecedor VARCHAR, e_transportadora VARCHAR);

CREATE OR REPLACE TABLE parceiro_sku (
    parceiro_sk BIGINT, sku_sk BIGINT, lote_minimo DOUBLE, multiplo_compra DOUBLE, lead_time_contratado_dias INTEGER);

CREATE OR REPLACE TABLE dim_veiculo (
    veiculo_sk BIGINT, empresa VARCHAR, placa VARCHAR, tipo VARCHAR, cap_kg DOUBLE, cap_m3 DOUBLE,
    classe_temperatura VARCHAR, propria VARCHAR, parceiro_sk BIGINT);

CREATE OR REPLACE TABLE dim_recurso (
    recurso_sk BIGINT, empresa VARCHAR, recurso VARCHAR, descricao VARCHAR, site VARCHAR, tipo VARCHAR, e_restritivo VARCHAR);

CREATE OR REPLACE TABLE dim_turno (
    turno_sk BIGINT, empresa VARCHAR, turno VARCHAR, site VARCHAR, inicio VARCHAR, fim VARCHAR, horas_disponiveis DOUBLE);

CREATE OR REPLACE TABLE matriz_setup (recurso_sk BIGINT, familia_origem VARCHAR, familia_destino VARCHAR, minutos DOUBLE);

CREATE OR REPLACE TABLE acordo_validade (cliente_sk BIGINT, sku_sk BIGINT, validade_minima_dias INTEGER);

CREATE OR REPLACE TABLE parametro_sku_local (
    sku_sk BIGINT, site VARCHAR, nivel_servico DOUBLE, dias_parados INTEGER, transito_dias INTEGER, custo_pedido DOUBLE,
    taxa_manter_ano DOUBLE, lead_time_reposicao_dias INTEGER, tolerancia_contagem_pct DOUBLE);

CREATE OR REPLACE TABLE parametro_empresa (
    empresa VARCHAR, otif_tolerancia_pct DOUBLE, limiar_ocupacao DOUBLE, limiar_k02b DOUBLE, n_min_observacoes INTEGER,
    janela_demanda_dias INTEGER, janela_lead_time_dias INTEGER, janela_clientes_dias INTEGER, apto_n_contagens INTEGER,
    apto_janela_dias INTEGER, apto_limiar DOUBLE, horizonte_projecao_dias INTEGER, versao INTEGER);

-- F01 recebimento (transacional)
CREATE OR REPLACE TABLE fato_recebimento (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data DATE, data_sk INTEGER, instante_conferencia TIMESTAMP, sku_sk BIGINT, lote_sk BIGINT, local_sk BIGINT,
    parceiro_sk BIGINT, colaborador_sk BIGINT, motivo_sk BIGINT, numero_recebimento VARCHAR, item INTEGER,
    numero_pc VARCHAR, item_pc INTEGER, chave_nf_entrada VARCHAR,
    qtd_esperada DOUBLE, qtd_recebida DOUBLE, qtd_recusada DOUBLE);

-- F05 pedido de compra (snapshot acumulado, reconstruído do bruto)
CREATE OR REPLACE TABLE fato_pedido_compra_linha (
    empresa VARCHAR, procedencia_sk BIGINT, sintetico BOOLEAN, numero_pc VARCHAR, item INTEGER,
    sku_sk BIGINT, site VARCHAR, parceiro_sk BIGINT, motivo_sk BIGINT,
    data_emissao DATE, data_prevista_original DATE, data_prevista_atual DATE, data_primeiro_receb DATE,
    data_ultimo_receb DATE, data_encerramento DATE,
    qtd_pedida DOUBLE, qtd_recebida_acum DOUBLE, qtd_cancelada DOUBLE, status VARCHAR);

-- F06a programação (snapshot por versão)
CREATE OR REPLACE TABLE fato_programacao_op (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data DATE, data_sk INTEGER, turno_sk BIGINT, recurso_sk BIGINT, sku_sk BIGINT,
    numero_op VARCHAR, versao INTEGER, sequencia INTEGER, congelada BOOLEAN,
    qtd_programada DOUBLE, tempo_padrao_min_un DOUBLE, setup_min DOUBLE);

-- F06b apontamento (transacional)
CREATE OR REPLACE TABLE fato_apontamento (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data DATE, data_sk INTEGER, instante_apontamento TIMESTAMP, turno_sk BIGINT, recurso_sk BIGINT, sku_sk BIGINT,
    lote_sk BIGINT, colaborador_sk BIGINT, motivo_sk BIGINT, numero_op VARCHAR, numero_apontamento INTEGER,
    qtd_boa DOUBLE, qtd_refugo DOUBLE);

-- F07 eventos do cliente sobre pedido de venda (transacional)
CREATE OR REPLACE TABLE fato_evento_pedido_venda (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data_evento DATE, data_desejada DATE, data_sk INTEGER, instante_evento TIMESTAMP, cliente_sk BIGINT, sku_sk BIGINT,
    site VARCHAR, motivo_sk BIGINT, numero_pedido VARCHAR, item INTEGER, numero_evento INTEGER, tipo_evento VARCHAR,
    delta_qtd DOUBLE);

-- F08 separação e conferência (transacional)
CREATE OR REPLACE TABLE fato_separacao (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data DATE, data_sk INTEGER, instante_separacao TIMESTAMP, instante_conferencia TIMESTAMP,
    sku_sk BIGINT, lote_sk BIGINT, local_sk BIGINT, cliente_sk BIGINT, colaborador_separador_sk BIGINT,
    colaborador_conferente_sk BIGINT, motivo_sk BIGINT, numero_tarefa VARCHAR, remessa VARCHAR, numero_pedido VARCHAR,
    item INTEGER, qtd_solicitada DOUBLE, qtd_separada DOUBLE, qtd_conferida DOUBLE);

-- F09 faturamento (transacional)
CREATE OR REPLACE TABLE fato_faturamento (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data DATE, data_sk INTEGER, instante_emissao TIMESTAMP, cliente_sk BIGINT, sku_sk BIGINT, site VARCHAR,
    chave_nf VARCHAR, item_nf INTEGER, numero_pedido VARCHAR, item_pedido INTEGER, remessa VARCHAR,
    qtd DOUBLE, valor_mercadoria DOUBLE);

-- F10a viagem (transacional; peso/volume derivados das remessas, com fator vigente)
CREATE OR REPLACE TABLE fato_viagem (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data DATE, data_sk INTEGER, instante_saida TIMESTAMP, instante_retorno TIMESTAMP, veiculo_sk BIGINT,
    colaborador_sk BIGINT, parceiro_sk BIGINT, site VARCHAR, numero_viagem VARCHAR,
    peso_kg DOUBLE, volume_m3 DOUBLE, custo_viagem DOUBLE, qtd_remessas INTEGER, qtd_paradas INTEGER);

-- F10b tentativa de entrega (transacional)
CREATE OR REPLACE TABLE fato_entrega (
    empresa VARCHAR, procedencia_sk BIGINT, carga_id BIGINT, bruto_num_linha INTEGER, chave_negocio VARCHAR,
    hash_linha VARCHAR, tipo_registro VARCHAR, sinal INTEGER, sintetico BOOLEAN,
    data DATE, data_sk INTEGER, instante_chegada TIMESTAMP, instante_conclusao TIMESTAMP, cliente_sk BIGINT,
    motivo_sk BIGINT, numero_viagem VARCHAR, remessa VARCHAR, numero_tentativa INTEGER, status VARCHAR,
    e_ultima_tentativa BOOLEAN);

-- F11 ciclo do pedido (snapshot acumulado, derivado): linha de pedido × remessa
CREATE OR REPLACE TABLE fato_ciclo_pedido (
    empresa VARCHAR, procedencia_sk BIGINT, sintetico BOOLEAN, numero_pedido VARCHAR, item INTEGER, remessa VARCHAR,
    cliente_sk BIGINT, sku_sk BIGINT, site VARCHAR, veiculo_sk BIGINT, motivo_sk BIGINT,
    data_pedido DATE, data_prometida DATE, data_separacao DATE, data_faturamento DATE, data_carregamento DATE,
    data_entrega DATE, instante_pedido TIMESTAMP, instante_separacao TIMESTAMP, instante_faturamento TIMESTAMP,
    instante_carregamento TIMESTAMP, instante_entrega TIMESTAMP, carregamento_estimado BOOLEAN,
    qtd_pedida_linha DOUBLE, qtd_alocada DOUBLE, qtd_entregue DOUBLE, status_final VARCHAR,
    no_prazo BOOLEAN, completo BOOLEAN, otif BOOLEAN, versao_regra_otif INTEGER);

-- F12 planejamento (snapshot periódico, derivado): estado de planejamento por SKU × site × dia
CREATE OR REPLACE TABLE fato_planejamento_sku (
    empresa VARCHAR, sintetico BOOLEAN, data DATE, data_sk INTEGER, sku_sk BIGINT, site VARCHAR,
    classe_abc VARCHAR, apto_reposicao BOOLEAN, acuracidade_janela DOUBLE, n_contagens_janela INTEGER,
    d DOUBLE, sigma_d DOUBLE, n_obs_demanda INTEGER, adi DOUBLE, cv2 DOUBLE, padrao_demanda VARCHAR,
    L DOUBLE, sigma_L DOUBLE, n_obs_lead_time INTEGER, fonte_lead_time VARCHAR,
    nivel_servico DOUBLE, z DOUBLE, metodo_ss VARCHAR, ss DOUBLE, rop DOUBLE, motivo_nulo VARCHAR,
    q_eoq DOUBLE, q_palete DOUBLE, cob_max DOUBLE, teto_lote DOUBLE, lote_minimo DOUBLE, q_lote DOUBLE,
    alerta_lote_inviavel BOOLEAN, saldo_disponivel DOUBLE, custo_unit DOUBLE, cobertura_dias DOUBLE, dias_ate_ruptura INTEGER,
    gatilho_compra BOOLEAN, provisorio BOOLEAN);

-- F12b risco de vencimento por lote (derivado de F03 + F12, FEFO)
CREATE OR REPLACE TABLE fato_risco_validade (
    empresa VARCHAR, sintetico BOOLEAN, data DATE, data_sk INTEGER, sku_sk BIGINT, lote_sk BIGINT, site VARCHAR,
    data_validade DATE, validade_minima_dias INTEGER, dias_vendaveis INTEGER, saldo DOUBLE, consumivel DOUBLE,
    risco_qtd DOUBLE, risco_valor DOUBLE, provisorio BOOLEAN);
