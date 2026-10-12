-- Camada bruta: append-only. Nunca UPDATE nem DELETE (invariante de três camadas).
-- Dimensões e fatos são reconstruídos a partir daqui (app/transform.py).

CREATE SEQUENCE IF NOT EXISTS seq_carga START 1;

CREATE TABLE IF NOT EXISTS bruto_carga (
    carga_id        BIGINT PRIMARY KEY,
    empresa         VARCHAR NOT NULL,
    layout          VARCHAR NOT NULL,
    fonte           VARCHAR NOT NULL,      -- UPLOAD | FORMULARIO | ERP
    nome_arquivo    VARCHAR,
    hash_conteudo   VARCHAR NOT NULL,      -- md5 dos hashes de linha ordenados: independe de formato e ordem
    usuario         VARCHAR NOT NULL,
    instante        TIMESTAMP NOT NULL,
    sintetico       BOOLEAN NOT NULL,
    status          VARCHAR NOT NULL,      -- ACEITA | RECUSADA | DUPLICADA
    n_linhas        INTEGER NOT NULL,
    n_novas         INTEGER NOT NULL,
    n_correcoes     INTEGER NOT NULL,
    n_repetidas     INTEGER NOT NULL,
    n_erros         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bruto_linha (
    carga_id        BIGINT NOT NULL,
    num_linha       INTEGER NOT NULL,
    payload_origem  VARCHAR NOT NULL,      -- linha como veio (JSON de textos)
    payload         VARCHAR,               -- linha tipada e normalizada (JSON); nulo se inválida
    chave_negocio   VARCHAR,
    hash_linha      VARCHAR,
    status          VARCHAR NOT NULL,      -- NOVA | CORRECAO | REPETIDA | ERRO
    erros           VARCHAR,
    PRIMARY KEY (carga_id, num_linha)
);
