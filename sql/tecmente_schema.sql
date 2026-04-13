-- ============================================================
--  TecMente  — Schema do Banco de Dados v1
--  MySQL 8.0+ | utf8mb4
--  Execute antes do gerador_mestre.py
-- ============================================================

CREATE DATABASE IF NOT EXISTS tecmente
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE tecmente;

-- ─────────────────────────────────────────────
-- DIMENSÕES
-- ─────────────────────────────────────────────

CREATE TABLE categoria (
    id_categoria  INT AUTO_INCREMENT PRIMARY KEY,
    nome          VARCHAR(100) NOT NULL,
    nome_pai      VARCHAR(100),                  -- ex: "Hardware" para "Placas de Vídeo"
    UNIQUE KEY uq_nome (nome)
);

CREATE TABLE fornecedor (
    id_fornecedor  INT AUTO_INCREMENT PRIMARY KEY,
    nome           VARCHAR(150) NOT NULL,
    cnpj           VARCHAR(20),
    cidade         VARCHAR(80),
    estado         CHAR(2),
    INDEX idx_estado (estado)
);

CREATE TABLE loja (
    id_loja  INT AUTO_INCREMENT PRIMARY KEY,
    nome     VARCHAR(100) NOT NULL,
    tipo     ENUM('Física', 'Online') NOT NULL,
    cidade   VARCHAR(80),
    estado   CHAR(2)
);

CREATE TABLE departamento (
    id_departamento  INT AUTO_INCREMENT PRIMARY KEY,
    nome             VARCHAR(80) NOT NULL UNIQUE
);

-- ─────────────────────────────────────────────
-- PRODUTOS
-- ─────────────────────────────────────────────

CREATE TABLE produto (
    id_produto     INT AUTO_INCREMENT PRIMARY KEY,
    sku            VARCHAR(30) UNIQUE,
    nome           VARCHAR(255) NOT NULL,
    descricao      TEXT,
    preco_custo    DECIMAL(10,2),
    preco_venda    DECIMAL(10,2) NOT NULL,
    id_categoria   INT,
    id_fornecedor  INT,
    ativo          TINYINT(1) DEFAULT 1,
    FOREIGN KEY (id_categoria)  REFERENCES categoria(id_categoria),
    FOREIGN KEY (id_fornecedor) REFERENCES fornecedor(id_fornecedor),
    INDEX idx_categoria (id_categoria),
    INDEX idx_preco     (preco_venda),
    INDEX idx_ativo     (ativo)
);

CREATE TABLE estoque (
    id_estoque         INT AUTO_INCREMENT PRIMARY KEY,
    id_produto         INT NOT NULL,
    id_loja            INT NOT NULL,
    quantidade         INT NOT NULL DEFAULT 0,
    ultima_atualizacao DATE,
    FOREIGN KEY (id_produto) REFERENCES produto(id_produto),
    FOREIGN KEY (id_loja)    REFERENCES loja(id_loja),
    UNIQUE KEY uq_prod_loja (id_produto, id_loja)
);

-- ─────────────────────────────────────────────
-- PESSOAS
-- ─────────────────────────────────────────────

CREATE TABLE funcionario (
    id_funcionario  INT AUTO_INCREMENT PRIMARY KEY,
    nome            VARCHAR(80)  NOT NULL,
    sobrenome       VARCHAR(80),
    cpf             VARCHAR(20),
    cargo           VARCHAR(80),
    data_admissao   DATE,
    data_nascimento DATE,
    salario         DECIMAL(10,2),
    id_departamento INT,
    id_loja         INT,
    FOREIGN KEY (id_departamento) REFERENCES departamento(id_departamento),
    FOREIGN KEY (id_loja)         REFERENCES loja(id_loja)
);

CREATE TABLE cliente (
    id_cliente      INT AUTO_INCREMENT PRIMARY KEY,
    nome            VARCHAR(100) NOT NULL,
    sobrenome       VARCHAR(100),
    tipo            ENUM('PF', 'PJ') NOT NULL DEFAULT 'PF',
    email           VARCHAR(150),              -- sem UNIQUE: duplicatas intencionais
    telefone        VARCHAR(30),
    cpf_cnpj        VARCHAR(25),               -- formatação propositalmente inconsistente
    data_nascimento DATE,
    data_cadastro   DATE NOT NULL,
    cidade          VARCHAR(80),
    estado          CHAR(2),
    INDEX idx_email  (email),
    INDEX idx_tipo   (tipo),
    INDEX idx_estado (estado)
);

-- ─────────────────────────────────────────────
-- VENDAS
-- ─────────────────────────────────────────────

CREATE TABLE pedido (
    id_pedido      INT AUTO_INCREMENT PRIMARY KEY,
    id_cliente     INT NOT NULL,
    id_loja        INT NOT NULL,
    id_funcionario INT,                        -- NULL em pedidos online sem atendente
    data_pedido    DATETIME NOT NULL,
    status         ENUM('Concluído','Enviado','Processando','Cancelado') NOT NULL,
    canal          ENUM('Loja Física','Site','Marketplace','WhatsApp','Televendas') NOT NULL,
    valor_total    DECIMAL(12,2) NOT NULL,
    desconto       DECIMAL(10,2) DEFAULT 0,
    obs            VARCHAR(255),
    FOREIGN KEY (id_cliente)     REFERENCES cliente(id_cliente),
    FOREIGN KEY (id_loja)        REFERENCES loja(id_loja),
    FOREIGN KEY (id_funcionario) REFERENCES funcionario(id_funcionario),
    INDEX idx_data   (data_pedido),
    INDEX idx_status (status),
    INDEX idx_canal  (canal)
);

CREATE TABLE pedido_item (
    id_item          INT AUTO_INCREMENT PRIMARY KEY,
    id_pedido        INT NOT NULL,
    id_produto       INT NOT NULL,
    quantidade       INT NOT NULL,
    preco_unitario   DECIMAL(10,2) NOT NULL,
    custo_unitario   DECIMAL(10,2),
    desconto_item    DECIMAL(10,2) DEFAULT 0,
    FOREIGN KEY (id_pedido)  REFERENCES pedido(id_pedido),
    FOREIGN KEY (id_produto) REFERENCES produto(id_produto),
    INDEX idx_pedido  (id_pedido),
    INDEX idx_produto (id_produto)
);

-- ─────────────────────────────────────────────
-- VIEWS ANALÍTICAS
-- ─────────────────────────────────────────────

-- Faturamento por mês
CREATE OR REPLACE VIEW vw_faturamento_mensal AS
SELECT
    DATE_FORMAT(data_pedido, '%Y-%m')            AS ano_mes,
    YEAR(data_pedido)                            AS ano,
    MONTH(data_pedido)                           AS mes,
    COUNT(DISTINCT id_pedido)                    AS total_pedidos,
    COUNT(DISTINCT id_cliente)                   AS clientes_unicos,
    SUM(valor_total)                             AS receita_bruta,
    SUM(desconto)                                AS total_descontos,
    SUM(CASE WHEN status != 'Cancelado'
             THEN valor_total ELSE 0 END)        AS receita_liquida,
    SUM(CASE WHEN status =  'Cancelado'
             THEN valor_total ELSE 0 END)        AS valor_cancelado,
    ROUND(SUM(CASE WHEN status =  'Cancelado'
             THEN valor_total ELSE 0 END)
        / NULLIF(SUM(valor_total),0) * 100, 2)  AS pct_cancelamento
FROM pedido
GROUP BY ano_mes, ano, mes;

-- Ranking de produtos
CREATE OR REPLACE VIEW vw_ranking_produtos AS
SELECT
    p.id_produto,
    p.sku,
    p.nome,
    c.nome                                       AS categoria,
    c.nome_pai                                   AS categoria_pai,
    p.preco_venda,
    SUM(pi.quantidade)                           AS unidades_vendidas,
    SUM(pi.quantidade * pi.preco_unitario)       AS receita,
    SUM(pi.quantidade * (pi.preco_unitario
        - COALESCE(pi.custo_unitario, 0)))       AS lucro_bruto,
    COUNT(DISTINCT pi.id_pedido)                 AS num_pedidos
FROM pedido_item pi
JOIN pedido   pe ON pi.id_pedido  = pe.id_pedido  AND pe.status != 'Cancelado'
JOIN produto  p  ON pi.id_produto = p.id_produto
JOIN categoria c ON p.id_categoria = c.id_categoria
GROUP BY p.id_produto, p.sku, p.nome, c.nome, c.nome_pai, p.preco_venda
ORDER BY receita DESC;

-- RFM de clientes (Recência, Frequência, Valor)
CREATE OR REPLACE VIEW vw_rfm AS
SELECT
    c.id_cliente,
    c.nome,
    c.tipo,
    c.cidade,
    c.estado,
    DATEDIFF(CURDATE(), MAX(pe.data_pedido))     AS recencia_dias,
    COUNT(DISTINCT pe.id_pedido)                 AS frequencia,
    SUM(pe.valor_total)                          AS valor_total,
    ROUND(AVG(pe.valor_total), 2)                AS ticket_medio,
    MIN(pe.data_pedido)                          AS primeira_compra,
    MAX(pe.data_pedido)                          AS ultima_compra
FROM cliente c
JOIN pedido pe ON c.id_cliente = pe.id_cliente AND pe.status != 'Cancelado'
GROUP BY c.id_cliente, c.nome, c.tipo, c.cidade, c.estado;

-- Performance por canal e loja
CREATE OR REPLACE VIEW vw_vendas_canal AS
SELECT
    l.nome                                       AS loja,
    l.tipo                                       AS tipo_loja,
    pe.canal,
    DATE_FORMAT(pe.data_pedido, '%Y-%m')         AS ano_mes,
    COUNT(*)                                     AS total_pedidos,
    SUM(pe.valor_total)                          AS receita,
    ROUND(AVG(pe.valor_total), 2)                AS ticket_medio
FROM pedido pe
JOIN loja l ON pe.id_loja = l.id_loja
WHERE pe.status != 'Cancelado'
GROUP BY l.nome, l.tipo, pe.canal, ano_mes;

-- Performance por categoria
CREATE OR REPLACE VIEW vw_categorias AS
SELECT
    c.nome_pai                                   AS grupo,
    c.nome                                       AS categoria,
    COUNT(DISTINCT p.id_produto)                 AS total_produtos,
    SUM(pi.quantidade)                           AS unidades_vendidas,
    SUM(pi.quantidade * pi.preco_unitario)       AS receita,
    ROUND(AVG(p.preco_venda), 2)                 AS preco_medio
FROM pedido_item pi
JOIN pedido   pe ON pi.id_pedido  = pe.id_pedido  AND pe.status != 'Cancelado'
JOIN produto  p  ON pi.id_produto = p.id_produto
JOIN categoria c ON p.id_categoria = c.id_categoria
GROUP BY c.nome_pai, c.nome
ORDER BY receita DESC;

SELECT 'Schema TecMente criado com sucesso!' AS status;
