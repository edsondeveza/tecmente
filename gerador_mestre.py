# -*- coding: utf-8 -*-
"""
gerador_mestre.py —  Gerador Mestre
========================================
Gerador de dados sintéticos para o banco de dados da TecMente.

Popula todas as tabelas do schema ``tecmente`` com dados realistas,
simulando a operação de um e-commerce de informática ao longo de um
histórico configurável (ver ANOS_HISTORICO).
**Não depende de nenhum arquivo externo** — produtos, categorias e
descrições são gerados internamente a partir de templates por categoria.

Pré-requisitos
--------------
- MySQL 8.0+ com o schema criado via ``tecmente_schema.sql``
- Dependências: ``mysql-connector-python``, ``faker``

Uso
---
    poetry run python gerador_mestre.py

Configuração
------------
Ajuste as constantes no bloco "CONFIGURAÇÕES" antes de executar:
- ``DB_CONFIG``      : credenciais do banco de dados
- ``NUM_CLIENTES``   : quantidade de clientes a gerar
- ``NUM_PEDIDOS``    : quantidade de pedidos a gerar
- ``PRODUTOS_BASE``  : catálogo de produtos embutido (SKU, nome, preço, categoria)
- ``random.seed()``  : remova ou altere para gerar dados diferentes a cada run

Autor: Edson Deveza
Versão: 1.2 (estoque temporal derivado da demanda)
"""

from __future__ import annotations

import argparse
import logging
import random
import re
from datetime import date, datetime, timedelta

import mysql.connector
from faker import Faker

from config import DB_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# =============================================================================
# CONFIGURAÇÕES
FAIXA_PRECO: dict[str, tuple[float, float]] = {
    "LOW": (0.45, 0.55),  # itens baratos/volume — margem alta (%)
    "MID": (0.38, 0.48),  # periféricos — margem média
    "HIGH": (0.30, 0.40),  # hardware intermediário — margem menor
    "ULTRA": (0.22, 0.32),  # premium — margem % baixa, valor absoluto alto
}
# Ajuste de margem (pontos percentuais) por grupo de categoria.
# Cria variação realista de lucratividade entre categorias.
AJUSTE_CATEGORIA: dict[str, float] = {
    "Cabos e Adaptadores": 0.04,
    "Energia": 0.03,
    "Eletrodomésticos": 0.02,
    "Periféricos": 0.01,
    "Armazenamento Portátil": 0.00,
    "Hardware": -0.01,
    "Redes": -0.01,
    "Impressão": 0.00,
    "Automação Comercial": -0.02,
    "Telefonia e VoIP": 0.02,
    "TVs e Displays": -0.03,
    "Câmeras e Segurança": 0.01,
    "Notebooks e Laptops": -0.02,
    "Tablets": 0.00,
}

# Fator de volume de vendas por dia da semana (ISO: 0 = segunda, 6 = domingo).
# Loja física e B2B concentram compras em dias úteis, com domingo mais fraco.
SAZONALIDADE_SEMANA: dict[int, float] = {
    0: 1.06,  # segunda
    1: 1.08,  # terça
    2: 1.08,  # quarta
    3: 1.06,  # quinta
    4: 1.04,  # sexta
    5: 0.95,  # sábado
    6: 0.73,  # domingo
}

# Peso relativo de clientes por UF — concentração regional realista:
# SP/MG (onde ficam as lojas) lideram, com capilaridade nas demais UFs.
PESOS_ESTADOS: dict[str, float] = {
    "SP": 26.0,
    "MG": 12.0,
    "RJ": 9.0,
    "PR": 6.0,
    "RS": 6.0,
    "SC": 5.0,
    "BA": 4.5,
    "GO": 3.5,
    "PE": 3.5,
    "DF": 3.0,
    "ES": 2.5,
    "CE": 2.5,
    "MT": 2.0,
    "MS": 2.0,
    "PA": 2.0,
    "AM": 1.5,
    "MA": 1.5,
    "PB": 1.5,
    "RN": 1.5,
    "PI": 1.0,
    "AL": 1.0,
    "SE": 1.0,
    "TO": 1.0,
    "RO": 0.5,
    "AC": 0.5,
    "AP": 0.5,
    "RR": 0.5,
}

# =============================================================================

fake = Faker("pt_BR")
# random.seed(42)  # remova para dados diferentes a cada execução

NUM_CLIENTES: int = 10000  # 10.000clientes
NUM_PEDIDOS: int = 100000  # 100.000 pedidos
PROPORCAO_PJ: float = 0.15  # 15% dos clientes são Pessoa Jurídica
ANOS_HISTORICO: int = 10  # janela de pedidos: ajuste aqui (ex.: 2, 5, 10)
DIAS_HISTORICO: int = 365 * ANOS_HISTORICO
DATA_INICIO = datetime.now() - timedelta(days=DIAS_HISTORICO)
# Parâmetros de reposição de estoque. O saldo em cada data é dimensionado para
# cobrir DIAS_COBERTURA_ALVO dias de venda, estimado a partir da demanda dos
# JANELA_REPOSICAO dias seguintes. O fator multiplica essa meta para simular
# decisões de compra imperfeitas: com valor abaixo de 1 a loja compra de menos
# (risco de ruptura), acima de 1 compra demais (capital parado).
DIAS_COBERTURA_ALVO: int = 60
JANELA_REPOSICAO: int = 30
FATOR_COBERTURA: tuple[float, float] = (0.5, 1.8)
# Multiplicadores de volume de vendas por mês.
# Valores > 1.0 representam alta temporada; < 1.0, baixa temporada.
# Referência: Black Friday (nov=1.80), volta às aulas (jan=1.30), Natal (dez=1.50).
SAZONALIDADE: dict[int, float] = {
    1: 1.30,  # Janeiro   – volta às aulas
    2: 1.20,  # Fevereiro – volta às aulas
    3: 0.85,  # Março
    4: 0.80,  # Abril
    5: 1.10,  # Maio      – Dia das Mães
    6: 1.00,  # Junho
    7: 0.90,  # Julho
    8: 0.85,  # Agosto
    9: 0.95,  # Setembro
    10: 1.05,  # Outubro
    11: 1.80,  # Novembro  – Black Friday
    12: 1.50,  # Dezembro  – Natal
}

# ─────────────────────────────────────────────────────────────────────────
# CATÁLOGO DE RUÍDO (taxas controladas)
# Cada taxa abaixo injeta propositalmente um problema de qualidade de dados
# para praticar normalização. Os valores-padrão reproduzem o comportamento
# atual do gerador; as taxas novas ampliam o leque de cenários. Este bloco é
# a fonte de verdade — espelha a tabela "Catálogo de ruído" no README.
# ─────────────────────────────────────────────────────────────────────────
RUIDO_EMAIL_TYPO = 0.03  # ~3% e-mails com domínio .con (erro de digitação)
RUIDO_SEM_TELEFONE = 0.08  # ~8% clientes sem telefone (NULL)
RUIDO_TELEFONE_VAZIO = 0.02  # ~2% clientes com telefone "" (vazio vs NULL)
RUIDO_EMAIL_FAMILIA = 0.04  # ~4% PF com e-mail familiar compartilhado
RUIDO_SEM_SOBRENOME = 0.02  # ~2% PF sem sobrenome cadastrado
RUIDO_SEM_NASCIMENTO = 0.12  # ~12% clientes sem data de nascimento
RUIDO_DESCONTINUADO = 0.06  # ~6% produtos inativos (ativo=0)
RUIDO_CLIENTE_DUP = 0.02  # ~2% clientes com CPF/e-mail duplicados (dedup)
RUIDO_ESPACO = 0.02  # ~2% nomes/sobrenomes/cidades com espaços irregulares
RUIDO_OBS = 0.05  # ~5% pedidos com observação de texto livre
# ~2% pedidos anteriores ao cadastro do cliente
RUIDO_PEDIDO_ANTES_CADASTRO = 0.02


# Catálogo de produtos embutido: (SKU, nome, preço_venda, categoria_hierarquica)
# Formato categoria: "Pai > Filho" — igual ao CSV gerado anteriormente.
# Adicione, remova ou edite produtos aqui conforme necessário.
PRODUTOS_BASE: list[tuple[str, str, float, str]] = [
    # ── Hardware > Placas de Vídeo ────────────────────────────────────────────
    (
        "258109",
        "Placa de Vídeo 4GB RX550 Star DDR5 AMD",
        84.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "256659",
        "Placa de Vídeo 2GB GT610 Keepdata DDR3 64Bits HDMI/DVI/VGA",
        196.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "256660",
        "Placa de Vídeo 2GB GT730 Keepdata DDR3 128Bits HDMI/DVI/VGA",
        283.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "254599",
        "Placa de Vídeo 2GB GT740 DDR5 128Bits HDMI/VGA/DVI",
        330.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "256662",
        "Placa de Vídeo 2GB GT740 Keepdata DDR5 128Bits",
        318.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "256663",
        "Placa de Vídeo 4GB GTX750 Keepdata DDR5 128Bits",
        399.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "258771",
        "Placa de Vídeo 4GB GTX750 Star DDR5 128Bits",
        378.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "256664",
        "Placa de Vídeo 4GB GTX750Ti Keepdata DDR5 128Bits",
        457.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "256665",
        "Placa de Vídeo 4GB GTX960 Keepdata DDR5 128Bits",
        573.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "52242",
        "Placa de Vídeo 8GB RX580 Biostar Radeon Gaming DDR5",
        710.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "51006",
        "Placa de Vídeo 8GB RX580 Keepdata DDR5 Dragonfly Gaming",
        830.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "67518",
        "Placa de Vídeo 8GB RX6600 Star DDR5",
        1426.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "70578",
        "Placa de Vídeo 8GB RX7600 Biostar Ultimate OC Gaming",
        1862.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "70310",
        "Placa de Vídeo 8GB RX9060XT XFX Radeon OC Black",
        2136.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "57370",
        "Placa de Vídeo 6GB RTX3050 Asus Dual OC",
        1368.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "86697",
        "Placa de Vídeo 8GB RTX2060 Biostar Super Extreme Gaming",
        1611.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "84090",
        "Placa de Vídeo 8GB RTX3060Ti Biostar Extreme Gaming",
        2153.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "67382",
        "Placa de Vídeo 8GB RTX5050 Galax 1-Click OC Black",
        1729.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "82794",
        "Placa de Vídeo 8GB RTX5050 MSI Shadow 2X OC",
        1734.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "67417",
        "Placa de Vídeo 8GB RTX5060 MSI Cyclone OC",
        2358.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "81940",
        "Placa de Vídeo 8GB RTX5060 Palit Dual OC",
        2316.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "58338",
        "Placa de Vídeo 8GB RTX5060Ti Palit Dual OC",
        2531.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "67461",
        "Placa de Vídeo 8GB RTX5060Ti Galax 1-Click OC Classic",
        2779.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "83246",
        "Placa de Vídeo 8GB RTX5060Ti Zotac Twin Edge",
        2697.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "55873",
        "Placa de Vídeo 16GB RTX5070Ti MSI Ventus 3X OC",
        6955.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "46974",
        "Placa de Vídeo 16GB RTX5080 MSI Inspire 3X OC",
        10828.99,
        "Hardware > Placas de Vídeo",
    ),
    (
        "48001",
        "Placa de Vídeo 32GB RTX5090 Zotac Gaming Solid",
        21904.99,
        "Hardware > Placas de Vídeo",
    ),
    # ── Hardware > Processadores ─────────────────────────────────────────────
    (
        "50001",
        "Processador AMD AM4 Ryzen 5 5600X 3.7GHz Box",
        1159.99,
        "Hardware > Processadores",
    ),
    (
        "50002",
        "Processador AMD AM4 Ryzen 5 5600G 3.9GHz Box",
        959.99,
        "Hardware > Processadores",
    ),
    (
        "50003",
        "Processador AMD AM5 Ryzen 7 7700X 4.5GHz Box",
        1899.99,
        "Hardware > Processadores",
    ),
    (
        "50004",
        "Processador Intel LGA1700 Core i5-12400F 2.5GHz Box",
        989.99,
        "Hardware > Processadores",
    ),
    (
        "50005",
        "Processador Intel LGA1700 Core i7-13700K 3.4GHz Box",
        2199.99,
        "Hardware > Processadores",
    ),
    (
        "50006",
        "Processador Intel LGA1851 Core i5-14600K 3.5GHz Box",
        1549.99,
        "Hardware > Processadores",
    ),
    # ── Hardware > Memória RAM ────────────────────────────────────────────────
    (
        "51001",
        "Memória DDR4 8GB Kingston 2666MHz KVR26N19S6/8",
        219.99,
        "Hardware > Memória RAM",
    ),
    (
        "51002",
        "Memória DDR4 16GB Kingston 3200MHz KVR32N22D8/16",
        389.99,
        "Hardware > Memória RAM",
    ),
    (
        "51003",
        "Memória DDR4 32GB Corsair Vengeance 3600MHz CMK32GX4M2D",
        749.99,
        "Hardware > Memória RAM",
    ),
    (
        "51004",
        "Memória DDR5 16GB Kingston Fury Beast 5200MHz KF552C40BB",
        459.99,
        "Hardware > Memória RAM",
    ),
    (
        "51005",
        "Memória DDR5 32GB Kingston Fury Beast 5600MHz KF556C40BBK2",
        899.99,
        "Hardware > Memória RAM",
    ),
    (
        "51036",
        "Memória SO-DIMM DDR4 8GB Kingston 3200MHz KVR32S22S6/8",
        259.99,
        "Hardware > Memória RAM",
    ),
    (
        "51007",
        "Memória SO-DIMM DDR4 16GB Crucial 3200MHz CT16G4SFRA32A",
        419.99,
        "Hardware > Memória RAM",
    ),
    # ── Hardware > Armazenamento ──────────────────────────────────────────────
    (
        "52001",
        "SSD 240GB Kingston A400 SATA III SA400S37/240G",
        189.99,
        "Hardware > Armazenamento",
    ),
    (
        "52002",
        "SSD 480GB Kingston A400 SATA III SA400S37/480G",
        289.99,
        "Hardware > Armazenamento",
    ),
    (
        "52003",
        "SSD 1TB Kingston NV3 M.2 NVMe PCIe SNV3S/1000G",
        399.99,
        "Hardware > Armazenamento",
    ),
    (
        "52004",
        "SSD 2TB Kingston NV3 M.2 NVMe PCIe SNV3S/2000G",
        699.99,
        "Hardware > Armazenamento",
    ),
    (
        "52005",
        "SSD 500GB Samsung 870 EVO SATA III MZ-77E500B/AM",
        399.99,
        "Hardware > Armazenamento",
    ),
    (
        "52006",
        "SSD 1TB WD Blue SN580 M.2 NVMe PCIe WDS100T3B0E",
        489.99,
        "Hardware > Armazenamento",
    ),
    (
        "52007",
        "HD 1TB Seagate Barracuda 7200RPM SATA III ST1000DM010",
        289.99,
        "Hardware > Armazenamento",
    ),
    (
        "52008",
        "HD 2TB Western Digital Blue 5400RPM WD20EZAZ",
        399.99,
        "Hardware > Armazenamento",
    ),
    (
        "52009",
        "HD 4TB Seagate IronWolf NAS 5900RPM ST4000VN008",
        749.99,
        "Hardware > Armazenamento",
    ),
    # ── Hardware > Fontes de Alimentação ─────────────────────────────────────
    (
        "53001",
        "Fonte de Alimentação 450W Corsair CV450 80 Plus Bronze",
        379.99,
        "Hardware > Fontes de Alimentação",
    ),
    (
        "53002",
        "Fonte de Alimentação 550W Corsair CV550 80 Plus Bronze",
        449.99,
        "Hardware > Fontes de Alimentação",
    ),
    (
        "53003",
        "Fonte de Alimentação 650W Corsair CV650 80 Plus Bronze",
        539.99,
        "Hardware > Fontes de Alimentação",
    ),
    (
        "53004",
        "Fonte de Alimentação 750W Corsair RM750x 80 Plus Gold",
        749.99,
        "Hardware > Fontes de Alimentação",
    ),
    (
        "53005",
        "Fonte de Alimentação 850W EVGA SuperNOVA 850 G6 Gold",
        939.99,
        "Hardware > Fontes de Alimentação",
    ),
    (
        "53006",
        "Fonte de Alimentação 200W Mtek MK200GX ITX",
        119.99,
        "Hardware > Fontes de Alimentação",
    ),
    (
        "53007",
        "Fonte de Alimentação 230W Satellite LC-8360SFX Micro ITX",
        149.99,
        "Hardware > Fontes de Alimentação",
    ),
    # ── Hardware > Refrigeração ───────────────────────────────────────────────
    (
        "54001",
        "Cooler DeepCool AK400 LGA1700/AM5 120mm",
        229.99,
        "Hardware > Refrigeração",
    ),
    (
        "54002",
        "Cooler Noctua NH-D15 LGA1700/AM5 Duplo 140mm",
        699.99,
        "Hardware > Refrigeração",
    ),
    (
        "54003",
        "Water Cooler Corsair H100i Elite 240mm ARGB",
        849.99,
        "Hardware > Refrigeração",
    ),
    (
        "54004",
        "Water Cooler NZXT Kraken 240 RL-KN240-B1",
        1059.99,
        "Hardware > Refrigeração",
    ),
    ("54005", "Water Cooler NZXT Kraken 360 RGB", 1399.99, "Hardware > Refrigeração"),
    (
        "54006",
        "Pasta Térmica Corsair TM30 High Performance 3g",
        49.99,
        "Hardware > Refrigeração",
    ),
    # ── Hardware > Gabinetes ──────────────────────────────────────────────────
    (
        "55001",
        "Gabinete Gamer DeepCool CC560 Mid-Tower ATX Vidro Temperado",
        399.99,
        "Hardware > Gabinetes",
    ),
    (
        "55002",
        "Gabinete Gamer NZXT H510 Mid-Tower ATX Branco",
        649.99,
        "Hardware > Gabinetes",
    ),
    (
        "55003",
        "Gabinete Gamer Corsair 4000D Airflow Mid-Tower ATX",
        699.99,
        "Hardware > Gabinetes",
    ),
    (
        "55004",
        "Gabinete Mini-ITX Cooler Master NR200P SFF",
        499.99,
        "Hardware > Gabinetes",
    ),
    (
        "55005",
        "Gabinete Mid-Tower FTX FTX255 500W Kit Teclado Mouse",
        229.99,
        "Hardware > Gabinetes",
    ),
    # ── Periféricos > Mouses ──────────────────────────────────────────────────
    (
        "60001",
        "Mouse USB Logitech G203 Lightsync 8000DPI Preto",
        179.99,
        "Periféricos > Mouses",
    ),
    ("60002", "Mouse USB Logitech G502 Hero 16000DPI", 349.99, "Periféricos > Mouses"),
    (
        "60003",
        "Mouse Wireless Logitech MX Master 3S 8000DPI",
        699.99,
        "Periféricos > Mouses",
    ),
    (
        "60004",
        "Mouse USB Razer DeathAdder V3 30000DPI Preto",
        499.99,
        "Periféricos > Mouses",
    ),
    (
        "60005",
        "Mouse USB Satellite MO-G35 Gamer RGB 2400DPI",
        59.99,
        "Periféricos > Mouses",
    ),
    (
        "60006",
        "Mouse USB Mtek MS35 Óptico 1200DPI Preto",
        29.99,
        "Periféricos > Mouses",
    ),
    ("60007", "Mouse USB Genius Easy 2B Óptico 800DPI", 19.99, "Periféricos > Mouses"),
    (
        "60008",
        "Kit Teclado e Mouse USB Logitech MK120 Espanhol",
        149.99,
        "Periféricos > Mouses",
    ),
    # ── Periféricos > Teclados ────────────────────────────────────────────────
    (
        "61001",
        "Teclado USB Satellite AK-910 ABNT2 Preto",
        27.99,
        "Periféricos > Teclados",
    ),
    (
        "61002",
        "Teclado USB Logitech K120 920-004422 Espanhol",
        59.99,
        "Periféricos > Teclados",
    ),
    (
        "61003",
        "Teclado Gamer USB Redragon S136 Inglês Preto",
        189.99,
        "Periféricos > Teclados",
    ),
    (
        "61004",
        "Teclado Gamer Mecânico Thermal Meka Level 20 Inglês",
        493.99,
        "Periféricos > Teclados",
    ),
    (
        "61005",
        "Teclado Bluetooth FTX FTXB09 Português Preto",
        91.99,
        "Periféricos > Teclados",
    ),
    # ── Periféricos > Monitores ───────────────────────────────────────────────
    (
        "62001",
        'Monitor 17" FTX MT17V1 Touch Capacitivo VGA/HDMI',
        549.99,
        "Periféricos > Monitores",
    ),
    (
        "62002",
        'Monitor 24" LG 24MP400-B IPS Full HD HDMI',
        849.99,
        "Periféricos > Monitores",
    ),
    (
        "62003",
        'Monitor 27" Samsung LS27B610EQNXGO IPS 2K HDMI/DP',
        1499.99,
        "Periféricos > Monitores",
    ),
    (
        "62004",
        'Monitor 27" LG 27GP850-B IPS QHD 165Hz G-Sync',
        2199.99,
        "Periféricos > Monitores",
    ),
    (
        "62005",
        'Monitor 32" Samsung Odyssey G5 VA QHD 165Hz',
        2499.99,
        "Periféricos > Monitores",
    ),
    # ── Periféricos > Webcams ─────────────────────────────────────────────────
    ("63001", "Webcam Logitech C270 HD 720p USB", 159.99, "Periféricos > Webcams"),
    ("63002", "Webcam Logitech C310 HD 720p USB", 299.99, "Periféricos > Webcams"),
    (
        "63003",
        "Webcam Logitech C920 HD Pro Full HD 1080p USB",
        499.99,
        "Periféricos > Webcams",
    ),
    ("63004", "Webcam Jabra PanaCast 20 USB 4K", 1899.99, "Periféricos > Webcams"),
    # ── Periféricos > Headsets e Fones ────────────────────────────────────────
    (
        "64001",
        "Headset USB Logitech H390 Estéreo Microfone",
        199.99,
        "Periféricos > Headsets e Fones",
    ),
    (
        "64002",
        "Headset Gamer HyperX Cloud II 7.1 USB Vermelho",
        599.99,
        "Periféricos > Headsets e Fones",
    ),
    (
        "64003",
        "Headset Gamer Razer BlackShark V2 3.5mm",
        749.99,
        "Periféricos > Headsets e Fones",
    ),
    (
        "64004",
        "Fone Bluetooth Anker Soundcore Life 2 Neo A3033",
        299.99,
        "Periféricos > Headsets e Fones",
    ),
    # ── Impressão ─────────────────────────────────────────────────────────────
    (
        "70001",
        "Impressora Epson EcoTank L3250 Jato de Tinta Wi-Fi",
        1199.99,
        "Impressão > Impressoras",
    ),
    (
        "70002",
        "Impressora HP LaserJet Pro M404dn Laser Mono Duplex",
        2499.99,
        "Impressão > Impressoras",
    ),
    (
        "70003",
        "Impressora Térmica 3Nstar RPI007E Ticket USB/Ethernet",
        899.99,
        "Impressão > Impressoras",
    ),
    (
        "70004",
        "Toner HP CF217A LaserJet M102W Preto ~1600 pgs",
        189.99,
        "Impressão > Toners e Cartuchos",
    ),
    (
        "70005",
        "Toner Samsung MLT-D101S ML-2160 Preto ~1500 pgs",
        169.99,
        "Impressão > Toners e Cartuchos",
    ),
    (
        "70006",
        "Toner HP CE285A LaserJet P1102 Preto ~1600 pgs",
        179.99,
        "Impressão > Toners e Cartuchos",
    ),
    (
        "70007",
        "Tinta Epson T544120 Preto L3110/L3150/L5190",
        66.99,
        "Impressão > Tintas",
    ),
    (
        "70008",
        "Tinta Epson T544220 Ciano L3110/L3150/L5190",
        66.99,
        "Impressão > Tintas",
    ),
    ("70009", "Tinta HP GT53 Black 1VV22AL 90ml", 55.99, "Impressão > Tintas"),
    (
        "70010",
        "Bobina Papel Térmico 80mm x 40m (50 unidades)",
        57.99,
        "Impressão > Papéis e Bobinas",
    ),
    # ── Redes ─────────────────────────────────────────────────────────────────
    (
        "71001",
        "Roteador TP-Link Archer AX73 Wi-Fi 6 AX5400",
        699.99,
        "Redes > Roteadores",
    ),
    (
        "71002",
        "Roteador TP-Link Archer AX23 Wi-Fi 6 AX1800 Dual Band",
        399.99,
        "Redes > Roteadores",
    ),
    (
        "71003",
        "Roteador TP-Link TL-WR949N 450Mbps 3 Antenas",
        99.99,
        "Redes > Roteadores",
    ),
    ("71004", "Switch 5P Mercusys MS105G Gigabit Desktop", 89.99, "Redes > Switches"),
    ("71005", "Switch 8P TP-Link TL-SG108 Gigabit Desktop", 159.99, "Redes > Switches"),
    (
        "71006",
        "Switch 24P TP-Link TL-SG1024D Gigabit Desktop",
        499.99,
        "Redes > Switches",
    ),
    (
        "71007",
        "Adaptador USB Wi-Fi TP-Link Archer T3U Nano AC1300",
        128.99,
        "Redes > Adaptadores Wi-Fi",
    ),
    (
        "71008",
        "Adaptador USB Wi-Fi TP-Link Archer T2U Mini AC600",
        59.99,
        "Redes > Adaptadores Wi-Fi",
    ),
    (
        "71009",
        "Adaptador USB para RJ-45 TP-Link UE300 USB 3.0 Gigabit",
        99.99,
        "Redes > Adaptadores de Rede",
    ),
    ("71010", "Cabo de Rede RJ-45 5m Cat6 Azul", 28.99, "Redes > Cabos de Rede"),
    ("71011", "Cabo de Rede RJ-45 10m Cat6", 59.99, "Redes > Cabos de Rede"),
    # ── Cabos e Adaptadores ───────────────────────────────────────────────────
    ("72001", "Cabo HDMI 2.0 4K 1.8m Goldplated", 24.99, "Cabos e Adaptadores"),
    ("72002", "Cabo HDMI 2.0 4K 3m Goldplated", 39.99, "Cabos e Adaptadores"),
    ("72003", "Adaptador Conversor HDMI para VGA", 34.99, "Cabos e Adaptadores"),
    (
        "72004",
        "Adaptador Conversor DisplayPort para VGA Fêmea",
        59.99,
        "Cabos e Adaptadores",
    ),
    (
        "72005",
        "Adaptador USB-C para RJ-45 TP-Link UE300C USB 3.0",
        119.99,
        "Cabos e Adaptadores",
    ),
    ("72006", "Hub USB 3.0 7 Portas Multilaser GA181", 89.99, "Cabos e Adaptadores"),
    ("72007", "Cabo USB-A para USB-C 1m Goldplated", 19.99, "Cabos e Adaptadores"),
    # ── Armazenamento Portátil ────────────────────────────────────────────────
    (
        "73001",
        "Pen Drive 32GB Sandisk Cruzer Blade USB 2.0",
        27.99,
        "Armazenamento Portátil",
    ),
    (
        "73002",
        "Pen Drive 64GB Sandisk Ultra Shift USB 3.0",
        49.99,
        "Armazenamento Portátil",
    ),
    (
        "73003",
        "Pen Drive 128GB Kingston DataTraveler USB 3.2",
        89.99,
        "Armazenamento Portátil",
    ),
    (
        "73004",
        "Cartão Micro SD 32GB Sandisk Class 10 Ultra 80MB/s",
        39.99,
        "Armazenamento Portátil",
    ),
    (
        "73005",
        "Cartão Micro SD 64GB Kingston Neo 95MB/s C10",
        59.99,
        "Armazenamento Portátil",
    ),
    (
        "73006",
        "Cartão Micro SD 128GB Samsung EVO Plus 100MB/s",
        89.99,
        "Armazenamento Portátil",
    ),
    # ── Energia ───────────────────────────────────────────────────────────────
    (
        "74001",
        "Nobreak 600VA FTX 360W Nema Universal 220V",
        241.99,
        "Energia > Nobreaks e UPS",
    ),
    (
        "74002",
        "Nobreak 700VA APC BVG700I-MSX Easy 230V",
        413.99,
        "Energia > Nobreaks e UPS",
    ),
    (
        "74003",
        "Nobreak 1200VA APC BVG1200I-MSX Easy 230V",
        665.99,
        "Energia > Nobreaks e UPS",
    ),
    (
        "74004",
        "Nobreak 2200VA APC Back BX2200MI-MS AVR 230V",
        1887.99,
        "Energia > Nobreaks e UPS",
    ),
    (
        "74005",
        "Nobreak 3000VA Smart MR-UF3000A 1800W 110V",
        965.99,
        "Energia > Nobreaks e UPS",
    ),
    # ── Automação Comercial ───────────────────────────────────────────────────
    (
        "75001",
        "Leitor Código de Barras Bematech BR800BT USB Preto",
        399.99,
        "Automação Comercial",
    ),
    (
        "75002",
        "Leitor Código de Barras CCD Honeywell 3800R USB Óptico",
        489.99,
        "Automação Comercial",
    ),
    ("75003", "Gaveta de Dinheiro FTX LAS-335 Aço RJ11", 299.99, "Automação Comercial"),
    (
        "75004",
        'Terminal POS 10" ICP802 com Impressora Térmica 58mm',
        2813.99,
        "Automação Comercial",
    ),
    # ── Câmeras e Segurança ───────────────────────────────────────────────────
    (
        "76001",
        "Câmera IP Satellite A-CAM8101 Full HD Wi-Fi Branca",
        349.99,
        "Câmeras e Segurança",
    ),
    (
        "76002",
        "Câmera de Segurança Balun Vídeo HD Passivo 5MP",
        39.99,
        "Câmeras e Segurança",
    ),
    (
        "76003",
        "Câmera IP Intelbras VIP 1230 B G3 Full HD PoE",
        849.99,
        "Câmeras e Segurança",
    ),
    # ── Notebooks e Tablets ───────────────────────────────────────────────────
    (
        "77001",
        'Notebook Asus VivoBook E1504GA I3-N305 8G/256SSD 15" W11',
        2669.99,
        "Notebooks e Laptops",
    ),
    (
        "77002",
        'Notebook Lenovo IdeaPad 3 I5-1235U 8G/512SSD 15.6" W11',
        3499.99,
        "Notebooks e Laptops",
    ),
    (
        "77003",
        "Notebook Dell Inspiron 15 I7-1255U 16G/512SSD W11",
        5499.99,
        "Notebooks e Laptops",
    ),
    ("77004", 'Tablet Samsung Galaxy Tab A8 4G/64G 10.5" Android', 1399.99, "Tablets"),
    (
        "77005",
        'Tablet Lenovo IdeaPad Pro TB373FU 8G/256G 12" com Teclado',
        3718.99,
        "Tablets",
    ),
    # ── Telefonia e VoIP ──────────────────────────────────────────────────────
    (
        "78001",
        "Telefone IP Intelbras TIP 435i Colorido Wi-Fi",
        899.99,
        "Telefonia e VoIP",
    ),
    (
        "78002",
        "Telefone S/Fio Panasonic KX-TGB110LAB Preto Bivolt",
        249.99,
        "Telefonia e VoIP",
    ),
    # ── TVs e Displays ────────────────────────────────────────────────────────
    ("79001", 'TV LED 32" Samsung UN32T4202 HD Smart Wi-Fi', 738.99, "TVs e Displays"),
    (
        "79002",
        'TV LED 43" Samsung 43DU7000 UHD Smart 4K Bluetooth',
        1332.99,
        "TVs e Displays",
    ),
    (
        "79003",
        'TV LED 50" Samsung 50DU7000 Smart BT UHD 4K USB',
        1803.99,
        "TVs e Displays",
    ),
    (
        "79004",
        'Suporte para TV FTX FTX31-KP02 32 a 70" 45kg Fixo',
        46.99,
        "TVs e Displays",
    ),
    (
        "79005",
        'Suporte para Monitor FTX FTX46-C012E 17"-32" 9kg',
        139.99,
        "TVs e Displays",
    ),
    # ── Eletrodomésticos ──────────────────────────────────────────────────────
    (
        "80001",
        "Ar Condicionado 12000 BTU Black+Decker Inverter 220V",
        2089.99,
        "Eletrodomésticos",
    ),
    (
        "80002",
        "Ar Condicionado 18000 BTU Black+Decker Inverter 220V",
        3015.99,
        "Eletrodomésticos",
    ),
    (
        "80003",
        "Ventilador FTX Brisa 3 Vel FS-40MF de Pé 60W 220V",
        252.99,
        "Eletrodomésticos",
    ),
]

# Lojas da rede: (nome, tipo, cidade, estado)
LOJAS: list[tuple[str, str, str, str]] = [
    ("CD Osasco", "Online", "Osasco", "SP"),
    ("Loja Paulista", "Física", "São Paulo", "SP"),
    ("Loja Santo André", "Física", "Santo André", "SP"),
    ("Loja Campinas", "Física", "Campinas", "SP"),
    ("Loja BH Centro", "Física", "Belo Horizonte", "MG"),
    ("Escritório Central", "Online", "São Paulo", "SP"),
]

DEPARTAMENTOS: list[str] = [
    "Vendas",
    "TI",
    "Logística",
    "Financeiro",
    "RH",
    "Marketing",
    "Suporte Técnico",
]

# Domínios usados na geração de e-mails de clientes PF.
DOMINIOS: list[str] = [
    "gmail.com",
    "hotmail.com",
    "yahoo.com.br",
    "outlook.com",
    "uol.com.br",
    "bol.com.br",
    "terra.com.br",
    "ig.com.br",
]


# =============================================================================
# HELPERS — geração de dados com ruído realista
# =============================================================================


def _email(nome: str, sobrenome: str = "", pj: bool = False) -> str:
    """Gera um endereço de e-mail com variações realistas de formato.

    Simula os padrões comuns encontrados em bases de dados reais:
    combinações de nome/sobrenome, uso de números, separadores variados.
    Cerca de 3% dos e-mails gerados contêm um erro de digitação intencional
    no domínio (ex: ``.con`` em vez de ``.com``), para exercitar rotinas de
    validação e limpeza de dados.

    Args:
        nome:      Primeiro nome do cliente.
        sobrenome: Sobrenome do cliente (opcional).
        pj:        Se ``True``, usa domínios corporativos fictícios.

    Returns:
        String com o e-mail gerado.
    """
    n = re.sub(r"[^a-z0-9]", "", nome.lower())
    s = re.sub(r"[^a-z0-9]", "", sobrenome.lower())
    dom = random.choice(["empresa.com.br", "comercio.net.br"] if pj else DOMINIOS)
    base = random.choice(
        [
            f"{n}.{s}",
            f"{n}{s}",
            f"{n}{random.randint(1, 99)}",
            f"{n[0]}{s}",
            f"{n}_{s}",
        ]
    )

    # Erro de digitação no domínio (taxa controlada)
    if random.random() < RUIDO_EMAIL_TYPO:
        dom = dom.replace(".com", ".con")

    return f"{base}@{dom}"


def _doc(pj: bool = False) -> str:
    """Gera CPF (PF) ou CNPJ (PJ) com formatação propositalmente inconsistente.

    Reproduz a realidade de bases legadas onde o mesmo campo armazena
    documentos em formatos diferentes: com pontuação, sem pontuação ou
    com separadores substituídos. Isso permite praticar normalização de dados.

    Args:
        pj: Se ``True``, gera CNPJ; caso contrário, CPF.

    Returns:
        String com o documento no formato sorteado.
    """
    raw = fake.cnpj() if pj else fake.cpf()
    r = random.random()
    if r < 0.33:
        return raw  # formato original: 000.000.000-00
    if r < 0.66:
        return re.sub(r"[.\-/]", "", raw)  # apenas números: 00000000000
    return re.sub(r"[.\-/]", "_", raw)  # separadores trocados: 000_000_000_00


def _fone() -> str | None:
    """Gera um número de telefone celular com variações de formato.

    Cerca de 8% dos registros não possuem telefone (``None``) e outros ~2%
    possuem telefone vazio (``""`` — diferente de NULL), para praticar a
    distinção entre vazio e ausente.

    Returns:
        String com o telefone formatado, ``None`` (não informado ou ``""`` vazio).
    """
    r = random.random()
    if r < RUIDO_SEM_TELEFONE:
        return None
    if r < RUIDO_SEM_TELEFONE + RUIDO_TELEFONE_VAZIO:
        return ""

    ddd = random.choice(["11", "13", "21", "31", "41", "47", "51", "61", "71"])
    num = f"9{random.randint(1000, 9999)}-{random.randint(1000, 9999)}"

    return random.choice(
        [
            f"({ddd}) {num}",  # (11) 91234-5678
            f"{ddd}{num.replace('-', '')}",  # 11912345678
            f"+55{ddd}{num.replace('-', '')}",  # +5511912345678
        ]
    )


def _ruido_espaco(s: str) -> str:
    """Insere espaços irregulares em uma string com determinada probabilidade.

    Simula bases legadas com espaços à esquerda/direita ou duplos espaços
    internos, exigindo normalização de whitespace no tratamento.

    Args:
        s: String original (nome, sobrenome, cidade etc.).

    Returns:
        A string com ruído de espaços caso sorteado, ou inalterada.
    """
    if random.random() >= RUIDO_ESPACO:
        return s
    if random.random() < 0.5:
        return f" {s}"
    if random.random() < 0.6:
        return f"{s} "
    # duplo espaço interno no primeiro espaço simples
    return s if " " not in s else re.sub(r" ", "  ", s, count=1)


def _ticket(preco: float) -> str:
    """Classifica um produto em faixas de preço para calibrar o comportamento de compra.

    A faixa determina a quantidade típica comprada por pedido:

    - LOW   (≤ R$ 50)  : cabos, adaptadores — compras em volume
    - MID   (≤ R$ 300) : periféricos, memórias — 1 a 3 unidades
    - HIGH  (≤ R$ 900) : GPUs médias, monitores — quase sempre 1 unidade
    - ULTRA (> R$ 900) : workstations, GPUs topo — sempre 1 unidade

    Args:
        preco: Preço de venda do produto em reais.

    Returns:
        Uma das strings: ``'LOW'``, ``'MID'``, ``'HIGH'`` ou ``'ULTRA'``.
    """
    if preco <= 50:
        return "LOW"
    if preco <= 300:
        return "MID"
    if preco <= 900:
        return "HIGH"
    return "ULTRA"


def _margem_bruta(preco: float, categoria_pai: str) -> float:
    """Calcula a margem bruta (%) de um produto por faixa de preço e categoria.

    Base: faixa de preço (itens baratos têm margem % maior; premium, menor).
    Ajuste: pequena variação por grupo de categoria (lucratividade por mix).

    Args:
        preco:        Preço de venda do produto em reais.
        categoria_pai: Grupo de categoria (ex.: ``'Hardware'``).

    Returns:
        Margem bruta como fração (0.22 = 22%).
    """
    lo, hi = FAIXA_PRECO[_ticket(preco)]
    margem = random.uniform(lo, hi) + AJUSTE_CATEGORIA.get(categoria_pai, 0.0)
    return round(min(max(margem, 0.10), 0.70), 4)


def _custo_unitario(preco: float, categoria_pai: str) -> float:
    """Gera o custo unitário a partir de uma margem bruta determinada por faixa/categoria.

    Args:
        preco:          Preço de venda do produto em reais.
        categoria_pai:  Grupo de categoria do produto.

    Returns:
        Custo unitário (preço × (1 − margem)).
    """
    margem = _margem_bruta(preco, categoria_pai)
    return round(preco * (1 - margem), 2)


# Sobrenomes brasileiros usados na composição de razões sociais PJ.
_SOBRENOMES_PJ: list[str] = [
    "Almeida",
    "Andrade",
    "Araújo",
    "Barbosa",
    "Borges",
    "Camargo",
    "Cardoso",
    "Carvalho",
    "Castro",
    "Correia",
    "Costa",
    "Cruz",
    "Cunha",
    "Dias",
    "Duarte",
    "Farias",
    "Fernandes",
    "Ferreira",
    "Fonseca",
    "Freitas",
    "Garcia",
    "Gomes",
    "Gonçalves",
    "Guerra",
    "Jesus",
    "Lima",
    "Lopes",
    "Machado",
    "Martins",
    "Melo",
    "Mendes",
    "Miranda",
    "Monteiro",
    "Moraes",
    "Moreira",
    "Nascimento",
    "Nunes",
    "Oliveira",
    "Pacheco",
    "Pereira",
    "Pinheiro",
    "Pinto",
    "Ramos",
    "Ribeiro",
    "Rocha",
    "Rodrigues",
    "Sales",
    "Santos",
    "Saraiva",
    "Silva",
    "Silveira",
    "Soares",
    "Souza",
    "Teixeira",
    "Vargas",
    "Vasconcelos",
    "Vieira",
]

_SUFIXOS_PJ: list[str] = [
    "Ltda.",
    "S.A.",
    "S/A",
    "ME",
    "EPP",
    "EIRELI",
    "S/S",
    "EI",
]

_SEGMENTOS_PJ: list[str] = [
    "Comércio",
    "Distribuidora",
    "Tecnologia",
    "Soluções",
    "Serviços",
    "Informática",
    "Sistemas",
    "Consultoria",
    "Importadora",
    "Atacado",
]


def _razao_social() -> str:
    """Gera uma razão social fictícia com padrão brasileiro realista.

    Combina sobrenomes, segmentos de mercado e sufixos jurídicos para
    produzir nomes como "Silva & Ferreira Tecnologia Ltda." ou
    "Distribuidora Cardoso ME", evitando os nomes genéricos gerados
    pelo ``fake.company()`` do Faker pt_BR.

    Returns:
        String com a razão social gerada.
    """
    modelo = random.randint(1, 4)

    if modelo == 1:
        # Ex: Silva & Ferreira Ltda.
        s1 = random.choice(_SOBRENOMES_PJ)
        s2 = random.choice(_SOBRENOMES_PJ)
        sufixo = random.choice(_SUFIXOS_PJ)
        return f"{s1} & {s2} {sufixo}"

    if modelo == 2:
        # Ex: Distribuidora Santos EPP
        segmento = random.choice(_SEGMENTOS_PJ)
        sobrenome = random.choice(_SOBRENOMES_PJ)
        sufixo = random.choice(_SUFIXOS_PJ)
        return f"{segmento} {sobrenome} {sufixo}"

    if modelo == 3:
        # Ex: Rocha Tecnologia e Serviços Ltda.
        sobrenome = random.choice(_SOBRENOMES_PJ)
        seg1 = random.choice(_SEGMENTOS_PJ)
        seg2 = random.choice(_SEGMENTOS_PJ)
        sufixo = random.choice(_SUFIXOS_PJ)
        return f"{sobrenome} {seg1} e {seg2} {sufixo}"

    # modelo == 4
    # Ex: Costa & Associados S.A.
    sobrenome = random.choice(_SOBRENOMES_PJ)
    sufixo = random.choice(_SUFIXOS_PJ)
    return f"{sobrenome} & Associados {sufixo}"


# =============================================================================
# TEMPLATES DE DESCRIÇÃO POR CATEGORIA
# Padrão idêntico ao gerador_realista.py: dicionários de atributos
# combinados aleatoriamente para montar a descrição do produto.
# =============================================================================

TEMPLATES: dict[str, dict] = {
    "Hardware > Placas de Vídeo": {
        "interface": ["PCIe 4.0 x16", "PCIe 3.0 x16", "PCIe 4.0 x8"],
        "memoria": ["GDDR6", "GDDR6X", "GDDR5", "GDDR5X"],
        "saida": [
            "HDMI 2.1, 3x DisplayPort",
            "HDMI 2.1, 2x DisplayPort",
            "2x HDMI, DisplayPort",
        ],
        "uso": [
            "games e criacao de conteudo",
            "workstations e games",
            "renderizacao e IA",
        ],
        "template": "{nome}. Interface {interface}, memoria {memoria}. Saidas: {saida}. Ideal para {uso}.",
    },
    "Hardware > Processadores": {
        "soquete": ["AM5", "AM4", "LGA1700", "LGA1200", "LGA1851"],
        "cache": ["cache L3 16MB", "cache L3 32MB", "cache L3 64MB", "cache L3 8MB"],
        "tdp": ["65W", "95W", "105W", "125W", "35W"],
        "uso": ["desktops de alto desempenho", "workstations", "PCs gamer"],
        "template": "{nome}. Soquete {soquete}, {cache}, TDP {tdp}. Para {uso}.",
    },
    "Hardware > Memória RAM": {
        "tipo": ["DDR4", "DDR5", "DDR3"],
        "velocidade": [
            "3200MHz",
            "3600MHz",
            "4800MHz",
            "5200MHz",
            "2666MHz",
            "2400MHz",
        ],
        "latencia": ["CL16", "CL18", "CL22", "CL36", "CL14"],
        "formato": [
            "DIMM para desktop",
            "SO-DIMM para notebook",
            "DIMM ECC para servidor",
        ],
        "template": "{nome}. {tipo} {velocidade} {latencia}, {formato}. Compativel com XMP/EXPO.",
    },
    "Hardware > Armazenamento": {
        "interface": ["NVMe PCIe 4.0", "NVMe PCIe 3.0", "SATA III 6Gb/s"],
        "leitura": ["7.400 MB/s", "3.500 MB/s", "550 MB/s", "5.000 MB/s"],
        "escrita": ["6.900 MB/s", "3.000 MB/s", "520 MB/s", "4.500 MB/s"],
        "fator": ["fator M.2 2280", 'fator 2,5"', "fator M.2 2242"],
        "template": "{nome}. Interface {interface}, leitura ate {leitura}, gravacao ate {escrita}. {fator}.",
    },
    "Hardware > Fontes de Alimentação": {
        "certificacao": [
            "80 Plus Bronze",
            "80 Plus Gold",
            "80 Plus Platinum",
            "80 Plus White",
        ],
        "modularidade": ["totalmente modular", "semi-modular", "nao-modular"],
        "protecao": [
            "com protecao OVP/UVP/OCP/SCP",
            "com protecao OVP/OCP",
            "com protecao completa",
        ],
        "template": "{nome}. Certificacao {certificacao}, cabo {modularidade}. {protecao}.",
    },
    "Hardware > Refrigeração": {
        "tipo": [
            "cooler de torre",
            "water cooler all-in-one",
            "cooler low-profile",
            "water cooler",
        ],
        "tdp": ["ate 200W TDP", "ate 150W TDP", "ate 250W TDP", "ate 300W TDP"],
        "rolamento": [
            "rolamento de esferas",
            "rolamento fluido",
            "rolamento hidraulico",
        ],
        "extra": [
            "com iluminacao ARGB",
            "com iluminacao RGB",
            "sem iluminacao",
            "com display LCD",
        ],
        "template": "{nome}. {tipo}, suporta {tdp}, {rolamento}. {extra}.",
    },
    "Hardware > Placas-Mãe": {
        "chipset": [
            "chipset B650",
            "chipset X670",
            "chipset Z790",
            "chipset B760",
            "chipset H610",
        ],
        "formato": ["ATX", "Micro-ATX", "Mini-ITX"],
        "slots_mem": ["4 slots DDR5", "4 slots DDR4", "2 slots DDR5"],
        "extra": [
            "Wi-Fi 6E e Bluetooth 5.3 integrados",
            "LAN 2.5G",
            "Wi-Fi 6 e LAN 2.5G",
        ],
        "template": "{nome}. {chipset}, formato {formato}, {slots_mem}. {extra}.",
    },
    "Hardware > Placas": {
        "barramento": ["PCI Express 3.0", "PCI Express 4.0", "USB 3.0"],
        "uso": ["expansao de conectividade", "captura de video", "som profissional"],
        "template": "{nome}. Barramento {barramento}. Para {uso}. Plug-and-play.",
    },
    "Hardware > Gabinetes": {
        "formato": ["Mid-Tower ATX", "Full-Tower ATX", "Mini-Tower mATX", "Mini-ITX"],
        "material": [
            "aco e vidro temperado",
            "aco e acrilico",
            "aluminio e vidro temperado",
        ],
        "ventilacao": [
            "com suporte a 3 fans de 120mm",
            "com suporte a 2 fans de 140mm",
            "com 3 fans inclusos",
        ],
        "extra": [
            "painel lateral transparente",
            "frente mesh para melhor airflow",
            "design compacto",
        ],
        "template": "{nome}. Formato {formato}, {material}. {ventilacao}. {extra}.",
    },
    "Periféricos > Mouses": {
        "sensor": ["sensor optico", "sensor laser", "sensor optico de alta precisao"],
        "dpi": ["400-3200 DPI", "200-6400 DPI", "100-16000 DPI", "200-25600 DPI"],
        "conexao": ["USB com fio", "wireless 2.4GHz", "Bluetooth 5.0", "USB-C com fio"],
        "uso": ["uso geral e escritorio", "games e design", "uso profissional"],
        "template": "{nome}. {sensor}, {dpi} ajustavel. Conexao {conexao}. Para {uso}.",
    },
    "Periféricos > Teclados": {
        "tipo": ["membrana", "mecanico", "mecanico semi", "scissor switch"],
        "layout": [
            "ABNT2",
            "layout ABNT2 com teclas multimidia",
            "layout US Internacional",
        ],
        "conexao": ["USB com fio", "Bluetooth 5.0", "wireless 2.4GHz", "USB-C com fio"],
        "extra": [
            "com apoio de pulso",
            "com iluminacao RGB",
            "teclas silenciosas",
            "anti-ghosting N-Key",
        ],
        "template": "{nome}. Tipo {tipo}, {layout}. Conexao {conexao}. {extra}.",
    },
    "Periféricos > Monitores": {
        "painel": ["painel IPS", "painel VA", "painel TN", "painel IPS Nano"],
        "taxa": ["144Hz", "75Hz", "165Hz", "240Hz", "60Hz"],
        "tempo": ["1ms GtG", "4ms GtG", "5ms GtG", "1ms MPRT"],
        "extra": ["FreeSync Premium", "G-Sync Compatible", "HDR400", "HDR10"],
        "template": "{nome}. {painel}, {taxa} de atualizacao, {tempo} de resposta. {extra}.",
    },
    "Periféricos > Webcams": {
        "resolucao": [
            "Full HD 1080p/30fps",
            "4K/30fps",
            "HD 720p/30fps",
            "Full HD 1080p/60fps",
        ],
        "microfone": [
            "microfone integrado com cancelamento de ruido",
            "microfone estereo integrado",
            "sem microfone",
        ],
        "fov": [
            "campo de visao 90 graus",
            "campo de visao 78 graus",
            "campo de visao 110 graus",
        ],
        "conexao": ["USB-A", "USB-C", "USB-A plug-and-play"],
        "template": "{nome}. {resolucao}, {microfone}. {fov}, conexao {conexao}.",
    },
    "Periféricos > Headsets e Fones": {
        "driver": ["drivers de 40mm", "drivers de 50mm", "drivers de 53mm"],
        "conexao": ["P2 3,5mm", "USB-A", "Bluetooth 5.0", "USB-C"],
        "respostas": ["resposta 20Hz-20kHz", "resposta 20Hz-22kHz"],
        "uso": [
            "games e comunicacao",
            "musica e entretenimento",
            "calls e videoconferencias",
        ],
        "template": "{nome}. {driver}, {conexao}. {respostas}. Ideal para {uso}.",
    },
    "Periféricos > Suportes": {
        "capacidade": ["ate 8kg", "ate 15kg", "ate 30kg", "ate 5kg"],
        "movimentos": [
            "articulado com inclinacao e rotacao",
            "fixo com inclinacao",
            "articulado 360 graus",
        ],
        "compatib": [
            'monitores 17-32"',
            'TVs 32-55"',
            'monitores 13-27"',
            'TVs 37-70"',
        ],
        "template": "{nome}. Suporta {capacidade}, {movimentos}. Compativel com {compatib}. VESA 75/100.",
    },
    "Periféricos > Projetores": {
        "tecnologia": ["DLP", "LCD", "LED"],
        "resolucao": ["Full HD 1920x1080", "HD 1280x720", "4K UHD 3840x2160"],
        "lumen": ["3.000 lumens", "4.000 lumens", "2.000 lumens", "5.000 lumens"],
        "conexao": ["HDMI, USB e VGA", "HDMI e USB", "2x HDMI e USB"],
        "template": "{nome}. Tecnologia {tecnologia}, {resolucao}, {lumen}. Entradas {conexao}.",
    },
    "Impressão > Impressoras": {
        "tecnologia": [
            "impressao a jato de tinta",
            "impressao laser monocromatica",
            "impressao laser colorida",
            "impressao termica",
        ],
        "velocidade": ["ate 20 ppm", "ate 33 ppm", "ate 10 ppm", "ate 40 ppm"],
        "conexao": ["USB e Wi-Fi", "USB, Wi-Fi e Ethernet", "USB e Ethernet", "USB"],
        "extra": [
            "com scanner e copiadora",
            "frente e verso automatico",
            "bandeja para 250 folhas",
            "com display LCD",
        ],
        "template": "{nome}. {tecnologia}, {velocidade}. Conexao {conexao}. {extra}.",
    },
    "Impressão > Toners e Cartuchos": {
        "rendimento": [
            "rendimento aprox. 1.000 paginas",
            "rendimento aprox. 2.500 paginas",
            "rendimento aprox. 5.000 paginas",
            "rendimento aprox. 10.000 paginas",
        ],
        "cobertura": ["cobertura 5%", "cobertura 5% A4"],
        "tipo": [
            "toner original",
            "toner compativel",
            "cartucho original",
            "cartucho compativel",
        ],
        "template": "{nome}. {tipo}, {rendimento} com {cobertura}. Embalagem lacrada.",
    },
    "Impressão > Tintas": {
        "volume": ["frasco 70ml", "frasco 100ml", "frasco 1 litro"],
        "tipo": ["tinta corante", "tinta pigmentada", "tinta para sublimacao"],
        "uso": [
            "reabastecimento de bulk ink",
            "recarga de cartucho",
            "impressoras EcoTank",
        ],
        "template": "{nome}. {volume}, {tipo}. Para {uso}. Alta definicao e secagem rapida.",
    },
    "Impressão > Papéis e Bobinas": {
        "largura": ["80mm", "58mm", "76mm"],
        "comprimento": ["40m", "80m", "20m"],
        "tipo": [
            "papel termico sem carbono",
            "papel termico BPA-free",
            "papel sulfite para jato de tinta",
        ],
        "template": "{nome}. {largura} de largura, {comprimento} por rolo, {tipo}. Pacote com 50 unidades.",
    },
    "Redes > Roteadores": {
        "padrao": ["Wi-Fi 6 (802.11ax)", "Wi-Fi 5 (802.11ac)", "Wi-Fi 6E (802.11axe)"],
        "velocidade": [
            "AX3000 ate 3.000 Mbps",
            "AC1200 ate 1.200 Mbps",
            "AX5400 ate 5.400 Mbps",
            "AC750 ate 750 Mbps",
        ],
        "porta": [
            "4 portas LAN Gigabit",
            "4 portas LAN 10/100",
            "4 portas LAN + 1 WAN Gigabit",
        ],
        "extra": [
            "com beamforming e MU-MIMO",
            "dual band 2,4GHz e 5GHz",
            "tri-band com IA de rede",
        ],
        "template": "{nome}. {padrao}, {velocidade}. {porta}. {extra}.",
    },
    "Redes > Switches": {
        "portas_qtd": ["5 portas", "8 portas", "16 portas", "24 portas", "48 portas"],
        "velocidade": [
            "Gigabit 10/100/1000Mbps",
            "Fast Ethernet 10/100Mbps",
            "10G Gigabit",
            "Gigabit com PoE+",
        ],
        "gerencia": ["nao gerenciavel", "gerenciavel via web", "gerenciavel via CLI"],
        "formato": ["desktop", 'rack 19" 1U', "parede"],
        "template": "{nome}. {portas_qtd} {velocidade}, {gerencia}. Formato {formato}, plug-and-play.",
    },
    "Redes > Antenas": {
        "ganho": ["5 dBi", "8 dBi", "12 dBi", "15 dBi", "9 dBi"],
        "frequencia": ["2,4GHz", "5GHz", "dual band 2,4/5GHz"],
        "tipo": ["omnidirecional", "direcional", "setorial"],
        "uso": ["redes Wi-Fi externas", "enlaces ponto a ponto", "cobertura ampla"],
        "template": "{nome}. Ganho {ganho}, frequencia {frequencia}, {tipo}. Para {uso}.",
    },
    "Redes > Adaptadores Wi-Fi": {
        "padrao": [
            "Wi-Fi 5 AC600",
            "Wi-Fi 5 AC1300",
            "Wi-Fi 6 AX1800",
            "Wi-Fi 5 AC750",
        ],
        "interface": ["USB 2.0", "USB 3.0", "USB-C"],
        "banda": ["dual band 2,4GHz e 5GHz", "banda unica 2,4GHz"],
        "extra": ["antena interna", "antena externa de alta ganho", "design nano"],
        "template": "{nome}. {padrao}, interface {interface}. {banda}. {extra}.",
    },
    "Redes > Adaptadores de Rede": {
        "velocidade": [
            "Gigabit 10/100/1000Mbps",
            "Fast Ethernet 10/100Mbps",
            "2,5G Ethernet",
        ],
        "interface": ["USB 3.0", "USB-C", "USB 2.0"],
        "extra": [
            "plug-and-play, sem driver",
            "compativel com Windows/Mac/Linux",
            "ideal para ultrabooks sem porta RJ-45",
        ],
        "template": "{nome}. {velocidade} via {interface}. {extra}.",
    },
    "Redes > Cabos de Rede": {
        "categoria_cabo": ["Cat5e", "Cat6", "Cat6A", "Cat7"],
        "blindagem": ["UTP nao blindado", "FTP blindado", "SFTP dupla blindagem"],
        "velocidade": ["ate 1 Gbps", "ate 10 Gbps", "ate 100 Mbps"],
        "uso": [
            "redes residenciais e corporativas",
            "data centers",
            "infraestrutura de rede",
        ],
        "template": "{nome}. {categoria_cabo} {blindagem}, suporta {velocidade}. Para {uso}.",
    },
    "Redes > Ubiquiti": {
        "tecnologia": ["MIMO 2x2", "MIMO 4x4", "airMAX ac"],
        "frequencia": ["5GHz", "2,4GHz", "dual band"],
        "ganho": ["13 dBi", "19 dBi", "23 dBi"],
        "uso": [
            "links ponto a ponto de longa distancia",
            "CPE PTMP",
            "backhaul wireless",
        ],
        "template": "{nome}. {tecnologia}, {frequencia}, ganho {ganho}. Para {uso}.",
    },
    "Cabos e Adaptadores": {
        "tipo": [
            "cabo de dados e carga",
            "adaptador de video",
            "cabo de video",
            "adaptador de interface",
            "extensor de sinal",
        ],
        "velocidade": [
            "USB 3.0 ate 5Gbps",
            "USB 2.0 ate 480Mbps",
            "4K a 60Hz",
            "1080p a 60Hz",
        ],
        "material": [
            "conectores banhados a ouro",
            "blindagem dupla",
            "conector reforcado",
        ],
        "template": "{nome}. {tipo}, {velocidade}. {material}. Plug-and-play.",
    },
    "Armazenamento Portátil": {
        "interface": ["USB 3.0", "USB 2.0", "USB-C 3.1"],
        "velocidade": [
            "leitura ate 130MB/s",
            "leitura ate 80MB/s",
            "leitura ate 400MB/s",
        ],
        "extra": [
            "design compacto",
            "protecao contra dados em loop",
            "com tampa protetora",
        ],
        "uso": [
            "transferencia de arquivos e backup",
            "uso em cameras e drones",
            "armazenamento e transporte de dados",
        ],
        "template": "{nome}. Interface {interface}, {velocidade}. {extra}. Para {uso}.",
    },
    "Energia > Nobreaks e UPS": {
        "topologia": ["linha interativa", "online dupla conversao", "off-line/standby"],
        "autonomia": [
            "autonomia aprox. 15min em carga total",
            "autonomia aprox. 30min em meia carga",
            "autonomia aprox. 10min em carga total",
        ],
        "protecao": [
            "protecao contra surtos, sobretensao e subtensao",
            "com regulacao automatica de tensao (AVR)",
            "protecao completa OVP/UVP/OCP",
        ],
        "template": "{nome}. Topologia {topologia}. {protecao}. {autonomia}.",
    },
    "Energia > Baterias": {
        "quimica": ["Li-Ion", "Li-Polymer", "NiMH"],
        "uso": ["notebooks e ultrabooks", "dispositivos moveis", "nobreaks"],
        "extra": [
            "sem efeito memoria",
            "ciclos de recarga prolongados",
            "protecao contra sobrecarga integrada",
        ],
        "template": "{nome}. Bateria {quimica} para {uso}. {extra}. Substitui bateria original.",
    },
    "Automação Comercial": {
        "interface": ["USB", "Serial RS-232", "USB e Ethernet", "Bluetooth"],
        "sistema": ["Windows 10/11", "Windows e Linux", "Android"],
        "uso": [
            "PDVs e frente de caixa",
            "controle de estoque",
            "automacao industrial",
        ],
        "template": "{nome}. Interface {interface}, compativel com {sistema}. Para {uso}.",
    },
    "Câmeras e Segurança": {
        "resolucao": ["Full HD 1080p", "4MP", "5MP", "4K 8MP", "HD 720p"],
        "visao": [
            "visao noturna infravermelha 30m",
            "visao noturna 20m",
            "visao noturna colorida 40m",
        ],
        "conexao": [
            "IP PoE",
            "Wi-Fi 2,4GHz",
            "HDCVI/HDTVI/AHD/CVBS",
            "IP Wi-Fi e com fio",
        ],
        "ip": [
            "classificacao IP67 (externa)",
            "classificacao IP66 (externa)",
            "para uso interno",
        ],
        "template": "{nome}. {resolucao}, {visao}. Conexao {conexao}. {ip}.",
    },
    "Tablets": {
        "sistema": ["Android 13", "Android 14", "Android 12", "iPadOS 17"],
        "conectividade": ["Wi-Fi 802.11ac", "Wi-Fi + 4G LTE", "Wi-Fi + 5G"],
        "bateria": ["bateria 6.000mAh", "bateria 8.000mAh", "bateria 5.000mAh"],
        "extra": ["camera traseira 13MP", "suporte a caneta stylus", "tela IPS"],
        "template": "{nome}. {sistema}, {conectividade}. {bateria}. {extra}.",
    },
    "Notebooks e Laptops": {
        "sistema": ["Windows 11 Home", "Windows 11 Pro", "Linux", "Chrome OS"],
        "armazenamento": ["SSD NVMe 256GB", "SSD NVMe 512GB", "SSD NVMe 1TB"],
        "bateria": [
            "bateria de 3 celulas aprox. 8h",
            "bateria de 4 celulas aprox. 10h",
        ],
        "extra": ["teclado retroiluminado", "webcam HD integrada", "leitor de digital"],
        "template": "{nome}. {sistema}, {armazenamento}. {bateria}. {extra}.",
    },
    "Computadores > Desktops": {
        "sistema": ["Windows 11 Home", "Windows 11 Pro", "sem sistema operacional"],
        "formato": ["torre compacta", "torre padrao ATX", "all-in-one"],
        "uso": ["escritorio e produtividade", "uso geral e multimidia", "workstation"],
        "extra": ["com teclado e mouse inclusos", "pronto para uso", "expansivel"],
        "template": "{nome}. {sistema}, formato {formato}. {extra}. Para {uso}.",
    },
    "Computadores > All-in-One": {
        "tela": ["tela IPS Full HD", "tela IPS 2K", "tela touchscreen Full HD"],
        "sistema": ["Windows 11 Pro", "Windows 10 Pro", "Windows 11 Home"],
        "uso": ["PDV e automacao comercial", "escritorio", "quiosques e recepcao"],
        "extra": ["design sem cabos aparentes", "suporte VESA", "com leitor de cartao"],
        "template": "{nome}. {tela}, {sistema}. {extra}. Para {uso}.",
    },
    "Telefonia e VoIP": {
        "protocolo": ["SIP 2.0", "H.323", "SIP e IAX2"],
        "conexao": ["Ethernet 10/100", "Wi-Fi e Ethernet", "USB e Ethernet"],
        "extra": ["display LCD", "viva-voz integrado", "agenda de contatos"],
        "uso": ["telefonia corporativa VoIP", "call centers", "PABX IP"],
        "template": "{nome}. Protocolo {protocolo}, {conexao}. {extra}. Para {uso}.",
    },
    "Smart Watches e Wearables": {
        "tela": ["tela AMOLED", "tela LCD", "tela TFT"],
        "autonomia": [
            "bateria aprox. 7 dias",
            "bateria aprox. 14 dias",
            "bateria aprox. 3 dias",
        ],
        "sensor": [
            "monitor cardiaco e SpO2",
            "GPS integrado e monitor cardiaco",
            "acelerometro e giroscopio",
        ],
        "compatib": ["Android e iOS", "Android 6.0+ e iOS 10+"],
        "template": "{nome}. {tela}, {autonomia}. {sensor}. Compativel com {compatib}.",
    },
    "TVs e Displays": {
        "painel": ["painel LED", "painel QLED", "painel OLED", "painel NanoCell"],
        "sistema": ["Google TV", "Android TV", "Tizen OS", "webOS"],
        "conexao": [
            "3x HDMI, 2x USB, Wi-Fi e Bluetooth",
            "2x HDMI, USB, Wi-Fi",
            "4x HDMI, 3x USB, Wi-Fi 6",
        ],
        "extra": ["Dolby Vision e Dolby Atmos", "HDR10+", "FreeSync Premium Pro"],
        "template": "{nome}. {painel}, {sistema}. Entradas: {conexao}. {extra}.",
    },
    "Eletrodomésticos": {
        "eficiencia": [
            "classe A de eficiencia energetica",
            "classificacao A++",
            "inverter de alta eficiencia",
        ],
        "voltagem": ["bivolt 110V/220V", "220V 60Hz", "110V 60Hz"],
        "extra": [
            "controle remoto incluso",
            "modo sleep e timer",
            "compressor inverter",
        ],
        "uso": ["uso residencial", "uso comercial", "pequenos espacos"],
        "template": "{nome}. {eficiencia}, {voltagem}. {extra}. Para {uso}.",
    },
    "Acessórios Diversos": {
        "tipo": ["acessorio original", "peca de reposicao", "acessorio compativel"],
        "uso": [
            "manutencao e upgrade",
            "expansao de funcionalidades",
            "reposicao de componente",
        ],
        "extra": ["instalacao simples", "compatibilidade ampla", "plug-and-play"],
        "template": "{nome}. {tipo} para {uso}. {extra}.",
    },
}

# Fallback para categorias sem template definido
TEMPLATE_GENERICO: dict = {
    "tipo": [
        "componente para informatica",
        "acessorio para informatica",
        "produto de TI",
    ],
    "extra": ["instalacao simples", "compatibilidade ampla", "plug-and-play"],
    "template": "{nome}. {tipo}. {extra}.",
}


# =============================================================================
# GERACAO DE DESCRICAO
# =============================================================================


def gerar_descricao(nome: str, categoria: str) -> str:
    """Gera uma descricao curta para um produto combinando template e nome.

    Seleciona atributos aleatorios dos dicionarios da categoria e monta a frase descritiva.

    Args:
        nome:      Nome normalizado do produto.
        categoria: Nome da categoria (ex: 'Hardware > Placas de Video').

    Returns:
        String com a descricao gerada (maximo ~200 caracteres).
    """
    dados = TEMPLATES.get(categoria, TEMPLATE_GENERICO)
    template = dados["template"]

    # Monta dicionario de substituicoes com valores aleatorios por chave
    substituicoes: dict[str, str] = {"nome": nome}
    for chave, valores in dados.items():
        if chave == "template":
            continue
        if isinstance(valores, list):
            substituicoes[chave] = random.choice(valores)

    # Aplica o template; em caso de chave faltante usa descricao generica
    try:
        descricao = template.format(**substituicoes)
    except KeyError:
        descricao = f"{nome}. Componente para informatica. Compatibilidade ampla."

    # Trunca se ultrapassar 200 caracteres, cortando na ultima virgula
    if len(descricao) > 200:
        descricao = descricao[:197].rsplit(",", 1)[0] + "."

    return descricao


# =============================================================================

# =============================================================================
# FUNÇÕES DE POPULAÇÃO
# =============================================================================


def limpar(cur) -> None:
    """Trunca todas as tabelas do schema na ordem correta de dependência.

    Desativa temporariamente a verificação de chaves estrangeiras para
    permitir o truncamento independente da ordem. Útil para re-executar
    o gerador sem precisar recriar o banco manualmente.

    Args:
        cur: Cursor MySQL ativo.
    """
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    tabelas = [
        "pedido_item",
        "pedido",
        "estoque",
        "funcionario",
        "cliente",
        "produto",
        "categoria",
        "fornecedor",
        "departamento",
        "loja",
    ]
    for tabela in tabelas:
        try:
            cur.execute(f"TRUNCATE TABLE {tabela}")
            # Garante que o próximo ID gerado seja 1
            cur.execute(f"ALTER TABLE {tabela} AUTO_INCREMENT = 1")
        except mysql.connector.Error:
            pass  # ignora se a tabela ainda não existir
    cur.execute("SET FOREIGN_KEY_CHECKS=1")


def popular_base(cur) -> tuple[list[int], list[int]]:
    """Popula as tabelas dimensionais: lojas, departamentos e fornecedores.

    Insere os dados mestres estáticos definidos nas constantes ``LOJAS`` e
    ``DEPARTAMENTOS``, e gera 40 fornecedores fictícios com Faker.

    Args:
        cur: Cursor MySQL ativo.

    Returns:
        Tupla ``(loja_ids, forn_ids)`` com as PKs geradas, usadas pelas
        funções seguintes para criar relacionamentos.
    """
    cur.executemany(
        "INSERT INTO loja (nome, tipo, cidade, estado) VALUES (%s, %s, %s, %s)",
        LOJAS,
    )
    cur.executemany(
        "INSERT INTO departamento (nome) VALUES (%s)",
        [(d,) for d in DEPARTAMENTOS],
    )

    # Fornecedores fixos — distribuidoras e representantes reais do setor de TI no Brasil.
    # CNPJ gerado com ruído intencional (formatação inconsistente) para exercitar limpeza de dados.
    fornecedores = [
        ("Ingram Micro Brasil Ltda.", _doc(pj=True), "Barueri", "SP"),
        ("TD SYNNEX Brasil Comércio e Distrib.", _doc(pj=True), "São Paulo", "SP"),
        ("Intcomex do Brasil Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("Aldo Componentes Eletrônicos Ltda.", _doc(pj=True), "Caxias do Sul", "RS"),
        ("Multilaser Industrial S.A.", _doc(pj=True), "Extrema", "MG"),
        ("Positivo Tecnologia S.A.", _doc(pj=True), "Curitiba", "PR"),
        ("Logitech do Brasil Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("Kingston Technology Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Corsair Memory Brasil Distrib.", _doc(pj=True), "São Paulo", "SP"),
        ("Samsung Eletrônica da Amazônia Ltda.", _doc(pj=True), "Manaus", "AM"),
        ("LG Electronics do Brasil Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("Seagate Technology Brasil Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("Western Digital do Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("TP-Link do Brasil Comércio Eletrônico", _doc(pj=True), "São Paulo", "SP"),
        ("Intelbras S.A.", _doc(pj=True), "São José", "SC"),
        ("Epson do Brasil Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("HP do Brasil Sistemas de Computação", _doc(pj=True), "Barueri", "SP"),
        ("Lenovo Tecnologia (Brasil) Ltda.", _doc(pj=True), "Indaiatuba", "SP"),
        ("Dell Computadores do Brasil Ltda.", _doc(pj=True), "Eldorado do Sul", "RS"),
        ("Asus do Brasil Computadores Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("MSI Computer do Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Gigabyte Technology Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("APC by Schneider Electric Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Vertiv Brasil Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("Cooler Master Brasil Distrib.", _doc(pj=True), "São Paulo", "SP"),
        ("NZXT Brasil Representações", _doc(pj=True), "São Paulo", "SP"),
        ("Razer do Brasil Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("HyperX / Kingston Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Crucial / Micron Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Zotac Technology Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Palit Microsystems Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Galax / KFA2 Brasil Distrib.", _doc(pj=True), "São Paulo", "SP"),
        ("XFX Brasil Comércio", _doc(pj=True), "São Paulo", "SP"),
        ("Satellite / FTX Distribuidora", _doc(pj=True), "São Paulo", "SP"),
        ("Mtek Informática Distrib. Ltda.", _doc(pj=True), "São Paulo", "SP"),
        ("Keepdata Comércio de Informática", _doc(pj=True), "São Paulo", "SP"),
        ("Ubiquiti Networks Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Sandisk / Western Digital Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("Biostar Technology Brasil", _doc(pj=True), "São Paulo", "SP"),
        ("3Nstar Automação Comercial Brasil", _doc(pj=True), "São Paulo", "SP"),
    ]
    cur.executemany(
        "INSERT INTO fornecedor (nome, cnpj, cidade, estado) VALUES (%s, %s, %s, %s)",
        fornecedores,
    )

    cur.execute("SELECT id_loja FROM loja")
    loja_ids = [r[0] for r in cur.fetchall()]

    cur.execute("SELECT id_fornecedor FROM fornecedor")
    forn_ids = [r[0] for r in cur.fetchall()]

    return loja_ids, forn_ids


def popular_produtos(
    cur, forn_ids: list[int]
) -> tuple[list[tuple[int, float]], set[int]]:
    """Insere categorias e produtos no banco a partir do catálogo embutido ``PRODUTOS_BASE``.

    Não depende de nenhum arquivo externo. Para cada produto:
    - Extrai a hierarquia de categoria do campo ``"Pai > Filho"``
    - Gera o custo unitário a partir da margem bruta por faixa/categoria
    - Gera a descrição usando o template da categoria via :func:`gerar_descricao`

    Identifica os "produtos populares" usando distribuição de Pareto:
    20% dos produtos mais baratos (alta rotatividade) mais uma amostra
    dos mais caros (itens aspiracionais com demanda consistente).

    Args:
        cur:      Cursor MySQL ativo.
        forn_ids: Lista de IDs de fornecedores para associação aleatória.

    Returns:
        Tupla ``(prods, populares)`` onde:

        - ``prods``     : lista de ``(id_produto, preco_venda, preco_custo)``
        - ``populares`` : conjunto de IDs de produtos com alta demanda
    """
    # Extrai categorias únicas do catálogo e insere no banco
    cats: dict[str, tuple[str, str]] = {}
    for _, _, _, cat_raw in PRODUTOS_BASE:
        if " > " in cat_raw:
            pai, filho = cat_raw.split(" > ", 1)
        else:
            pai, filho = cat_raw, cat_raw
        cats[cat_raw] = (pai.strip(), filho.strip())

    unicas = sorted(set(cats.values()), key=lambda x: x[1])
    for pai, filho in unicas:
        cur.execute(
            "INSERT IGNORE INTO categoria (nome, nome_pai) VALUES (%s, %s)",
            (filho, pai),
        )

    cur.execute("SELECT id_categoria, nome FROM categoria")
    cat_map = {nome: id_ for id_, nome in cur.fetchall()}

    # Monta lista de produtos com descrição gerada por template
    produtos_db = []
    for sku, nome, preco, cat_raw in PRODUTOS_BASE:
        pai, filho = cats.get(cat_raw, ("Geral", "Geral"))
        custo = _custo_unitario(preco, pai)
        id_cat = cat_map.get(filho, 1)
        descricao = gerar_descricao(nome, cat_raw)
        produtos_db.append(
            (sku, nome, descricao, custo, preco, id_cat, random.choice(forn_ids))
        )

    log.info("%d produtos carregados do catálogo interno.", len(produtos_db))

    produtos_db = [
        (*p, (1 if random.random() >= RUIDO_DESCONTINUADO else 0)) for p in produtos_db
    ]

    # Inserção em lotes de 500
    for i in range(0, len(produtos_db), 500):
        cur.executemany(
            "INSERT IGNORE INTO produto "
            "(sku, nome, descricao, preco_custo, preco_venda, id_categoria, "
            "id_fornecedor, ativo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            produtos_db[i : i + 500],
        )

    cur.execute("SELECT id_produto, preco_venda, preco_custo FROM produto")
    prods = [(id_, float(p), float(c)) for id_, p, c in cur.fetchall()]

    # Distribuição de Pareto: 20% mais baratos + amostra dos mais caros
    ordenados = sorted(prods, key=lambda x: x[1])
    populares: set[int] = {p[0] for p in ordenados[: int(len(ordenados) * 0.20)]}
    populares |= {
        p[0] for p in random.sample(ordenados[-100:], min(50, len(ordenados)))
    }

    return prods, populares


def _datas_snapshot(inicio: date, fim: date) -> list[date]:
    """Lista as datas de snapshot de estoque: 1º dia de cada mês + o próprio fim.

     A primeira data é sempre o 1º dia do mês seguinte a ``inicio`` (não há
    saldo conhecido antes disso) e a última é ``fim``, o que garante que o
     snapshot corrente exista mesmo quando ``fim`` cai no meio do mês.

     Args:
         inicio: Início da janela histórica (não gera snapshot nele).
         fim:    Data do snapshot corrente.

     Returns:
         Lista de datas crescentes.
    """
    datas: list[date] = []
    ano, mes = inicio.year, inicio.month + 1
    if mes > 12:
        ano, mes = ano + 1, 1
    while True:
        data = date(ano, mes, 1)
        if data >= fim:
            break
        datas.append(data)
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    if not datas or datas[-1] != fim:
        datas.append(fim)
    return datas


def _demanda_janela(
    vendas_mes: dict[tuple[int, int, int, int], int],
    id_loja: int,
    id_prod: int,
    inicio: date,
    dias: int,
) -> int:
    """Soma as unidades vendidas na janela ``[inicio, inicio + dias)``.

    Args:
        vendas_mes: Contador ``{(id_loja, id_prod, ano, mes): unidades}``.
        id_loja:    ID da loja.
        id_prod:    ID do produto.
        inicio:     Primeiro dia da janela (inclusive).
        dias:       Tamanho da janela em dias.

    Returns:
        Total de unidades vendidas na janela.
    """
    total = 0
    fim = inicio + timedelta(days=dias)
    cursor = inicio
    while cursor < fim:
        chave = (id_loja, id_prod, cursor.year, cursor.month)
        total += vendas_mes.get(chave, 0)
        # Avança para o próximo mês, mas para no dia 1 do mês seguinte ao fim
        # para não contar vendas que caem fora da janela.
        if cursor.month == 12:
            proximo = date(cursor.year + 1, 1, 1)
        else:
            proximo = date(cursor.year, cursor.month + 1, 1)
        if proximo >= fim:
            break
        cursor = proximo
    return total


def _nivel_estoque(demanda_janela: int, fator: float) -> int:
    """Converte a demanda de uma janela em um saldo de estoque.

    Args:
        demanda_janela: Unidades vendidas em ``JANELA_REPOSICAO`` dias.
        fator:          Multiplicador da meta de cobertura.

    Returns:
        Saldo de unidades, nunca negativo.
    """
    alvo = demanda_janela * DIAS_COBERTURA_ALVO / JANELA_REPOSICAO
    return max(0, int(round(alvo * fator)))


def popular_estoque(
    cur,
    prods: list[tuple[int, float]],
    loja_ids: list[int],
    vendas_mes: dict[tuple[int, int, int, int], int],
    inicio: date,
    fim: date,
) -> int:
    """Gera o histórico de snapshots de estoque (produto × loja × data).

    Cada snapshot é dimensionado para cobrir ``DIAS_COBERTURA_ALVO`` dias de
    venda, usando como estimativa a demanda dos ``JANELA_REPOSICAO`` dias
    seguintes. Para o snapshot corrente não existe demanda futura observada,
    então a estimativa usa a demanda dos dias **anteriores** (persistência) —
    é o que um planejador teria à mão.

    O saldo nasce da demanda real dos pedidos, e não de um número arbitrário:
    é isso que torna a cobertura de estoque mensurável. Antes o estoque era
    um snapshot estático que nunca diminuía, então qualquer alerta de ruptura
    era ruído.

    Args:
        cur:        Cursor MySQL ativo.
        prods:      Lista de ``(id_produto, preco_venda, preco_custo)``.
        loja_ids:   Lista de IDs de lojas.
        vendas_mes: Contador ``{(id_loja, id_prod, ano, mes): unidades}``.
        inicio:     Início da janela histórica.
        fim:        Data do snapshot corrente.

    Returns:
        Quantidade de snapshots gravados.
    """
    datas = _datas_snapshot(inicio, fim)
    log.info(
        "Gerando estoque temporal: %d datas × %d produtos × %d lojas...",
        len(datas),
        len(prods),
        len(loja_ids),
    )

    # Um fator por par produto × loja: a decisão de reposição do par é estável
    # ao longo do tempo, mas varia entre pares.
    fatores = {
        (id_prod, id_loja): random.uniform(*FATOR_COBERTURA)
        for id_prod, _, _ in prods
        for id_loja in loja_ids
    }

    def demanda_para(id_loja: int, id_prod: int, data: date, eh_final: bool) -> int:
        """Demanda estimada para dimensionar o snapshot em ``data``."""
        if eh_final:
            # Sem futuro observado: usa a janela anterior como proxy.
            inicio_janela = data - timedelta(days=JANELA_REPOSICAO)
        else:
            inicio_janela = data
        return _demanda_janela(
            vendas_mes, id_loja, id_prod, inicio_janela, JANELA_REPOSICAO
        )

    dados: list[tuple] = []
    for data in datas:
        eh_final = data == datas[-1]
        for id_prod, _, _ in prods:
            for id_loja in loja_ids:
                demanda = demanda_para(id_loja, id_prod, data, eh_final)
                qtd = _nivel_estoque(demanda, fatores[(id_prod, id_loja)])
                dados.append((id_prod, id_loja, data, qtd))

    for i in range(0, len(dados), 2000):
        cur.executemany(
            "INSERT INTO estoque (id_produto, id_loja, data, quantidade) "
            "VALUES (%s, %s, %s, %s)",
            dados[i : i + 2000],
        )

    log.info("%d snapshots de estoque gravados.", len(dados))
    return len(dados)


def popular_funcionarios(cur, loja_ids: list[int]) -> dict[int, list[int]]:
    """Gera funcionários e os distribui pelas lojas e departamentos.

    Lojas físicas recebem 10 funcionários do departamento de Vendas;
    lojas online e escritórios recebem 20 funcionários distribuídos
    entre os demais departamentos.

    Args:
        cur:      Cursor MySQL ativo.
        loja_ids: Lista de IDs de lojas (parâmetro reservado para
                  extensões futuras — a query busca lojas diretamente).

    Returns:
        Dicionário ``{id_loja: [id_funcionario, ...]}``, usado para
        associar atendentes aos pedidos gerados em lojas físicas.
    """
    cur.execute("SELECT id_departamento, nome FROM departamento")
    dep_map = {nome: id_ for id_, nome in cur.fetchall()}

    cur.execute("SELECT id_loja, tipo FROM loja")
    lojas = cur.fetchall()

    funcs = []
    for id_loja, tipo in lojas:
        n_funcs = 10 if tipo == "Física" else 20
        for _ in range(n_funcs):
            if tipo == "Física":
                dep = "Vendas"
                cargo = random.choice(["Vendedor", "Supervisor de Vendas"])
            else:
                dep = random.choice([d for d in DEPARTAMENTOS if d != "Vendas"])
                cargo = random.choice(
                    ["Analista", "Gerente", "Assistente", "Coordenador"]
                )

            salario = round(random.uniform(2000, 12000), 2)
            data_admissao = fake.date_between(start_date="-6y")
            # Nascimento: funcionário tinha entre 18 e 45 anos na admissão,
            # garantindo faixa etária atual realista (hoje entre ~18 e ~51 anos).
            # Subtração em dias (não .replace()) evita 29/fev inexistente.
            idade_na_admissao = random.randint(18, 45)
            data_nascimento = data_admissao - timedelta(days=365 * idade_na_admissao)
            funcs.append(
                (
                    fake.first_name(),
                    fake.last_name(),
                    _doc(),
                    cargo,
                    data_admissao,
                    salario,
                    dep_map[dep],
                    id_loja,
                    data_nascimento,
                )
            )

    cur.executemany(
        "INSERT INTO funcionario "
        "(nome, sobrenome, cpf, cargo, data_admissao, salario, id_departamento, id_loja, "
        "data_nascimento) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        funcs,
    )

    # Monta índice de funcionários por loja para uso na geração de pedidos
    cur.execute("SELECT id_funcionario, id_loja FROM funcionario")
    vend: dict[int, list[int]] = {}
    for id_func, id_loja in cur.fetchall():
        vend.setdefault(id_loja, []).append(id_func)

    return vend


def popular_clientes(cur) -> tuple[list[int], list[int], dict[int, date]]:
    """Gera clientes PF e PJ com dados sintéticos e ruído realista.

    Aplica as seguintes regras de ruído para simular qualidade de dados real:

    - ~4% dos clientes PF compartilham e-mail (membros de uma mesma família)
    - ~2% não possuem sobrenome cadastrado
    - ~12% não possuem data de nascimento
    - ~8% não possuem telefone
    - CPF/CNPJ com formatação inconsistente (ver :func:`_doc`)
    - Razões sociais PJ geradas via :func:`_razao_social` (padrão brasileiro realista)

    Args:
        cur: Cursor MySQL ativo.

    Returns:
        Tupla ``(pf_ids, pj_ids, recentes)`` com os IDs dos clientes gerados
        por tipo e, para os clientes recentes (pool de anomalia temporal),
        o mapeamento ``id_cliente → data_cadastro``.
        Usados na segmentação e no ruído de datas dos pedidos.
    """
    clientes = []

    # Pool de e-mails compartilhados para simular compras em família
    emails_familia = [_email(fake.first_name(), fake.last_name()) for _ in range(80)]

    cpf_gerados: set[str] = set()

    for i in range(NUM_CLIENTES):
        pj = random.random() < PROPORCAO_PJ
        tipo = "PJ" if pj else "PF"
        # Concentração geográfica regional (SP/MG têm peso maior, demais UFs
        # com capilaridade) — estados sorteados pela ponderação configurada.
        estados = list(PESOS_ESTADOS)
        pesos = list(PESOS_ESTADOS.values())
        estado = random.choices(estados, weights=pesos, k=1)[0]
        cidade, estado = (fake.city(), estado)

        # Cadastro alinhado aos pedidos: a maioria se registra ANTES da janela
        # de pedidos (DATA_INICIO), então as compras seguem o cadastro. Uma
        # fração recente forma o pool de anomalia temporal (ver popular_pedidos
        # / RUIDO_PEDIDO_ANTES_CADASTRO).
        if random.random() < 0.03:
            cadastro = fake.date_between(start_date="-90d", end_date="today")
        else:
            cadastro = DATA_INICIO - timedelta(
                days=random.randint(0, DIAS_HISTORICO // 10)
            )

        nasc = (
            None
            if random.random() < RUIDO_SEM_NASCIMENTO
            else fake.date_between(start_date="-70y", end_date="-18y")
        )

        if pj:
            nome = _razao_social()
            sob = None
            email = _email(re.sub(r"[^a-z]", "", nome.lower())[:10], pj=True)
        else:
            nome = fake.first_name()
            sob = fake.last_name() if random.random() > RUIDO_SEM_SOBRENOME else None
            email = (
                random.choice(emails_familia)
                if random.random() < RUIDO_EMAIL_FAMILIA
                else _email(nome, sob or "")
            )

        # Espaços irregulares (whitespace para normalizar no tratamento)
        nome = _ruido_espaco(nome)
        sob = _ruido_espaco(sob) if sob else None
        cidade = _ruido_espaco(cidade)

        # Dedup: ~2% reutilizam um CPF/e-mail já gerado (alvo de deduplicação)
        doc = _doc(pj)
        if random.random() < RUIDO_CLIENTE_DUP and cpf_gerados:
            doc = random.choice(list(cpf_gerados))
        else:
            cpf_gerados.add(doc)

        clientes.append(
            (nome, sob, tipo, email, _fone(), doc, nasc, cadastro, cidade, estado)
        )

    for i in range(0, len(clientes), 500):
        cur.executemany(
            "INSERT INTO cliente "
            "(nome, sobrenome, tipo, email, telefone, cpf_cnpj, "
            "data_nascimento, data_cadastro, cidade, estado) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            clientes[i : i + 500],
        )
    # Busca os IDs REAIS do banco após o INSERT (com tipo e cadastro)
    cur.execute("SELECT id_cliente, tipo, data_cadastro FROM cliente")
    todas = cur.fetchall()
    pf_ids = [r[0] for r in todas if r[1] == "PF"]
    pj_ids = [r[0] for r in todas if r[1] == "PJ"]
    # Pool de anomalia temporal: clientes registrados nos últimos 90 dias.
    # Recebem pedidos anteriores ao cadastro via RUIDO_PEDIDO_ANTES_CADASTRO.
    # Guarda também a data de cadastro para datar o pedido pouco antes do registro.
    recente_limiar = (datetime.now() - timedelta(days=90)).date()
    recentes = {r[0]: r[2] for r in todas if r[2] >= recente_limiar}

    return pf_ids, pj_ids, recentes


def _indice_por_ticket(
    prods: list[tuple[int, float, float]],
) -> dict[str, list[tuple[int, float, float]]]:
    """Agrupa produtos por faixa de preço para seleção eficiente."""
    por_ticket: dict[str, list[tuple[int, float, float]]] = {
        "LOW": [],
        "MID": [],
        "HIGH": [],
        "ULTRA": [],
    }
    for pid, preco, custo in prods:
        por_ticket[_ticket(preco)].append((pid, preco, custo))
    return por_ticket


def _escolher_cliente(
    super_ativos: set[int],
    inativos: set[int],
    normais: list[int],
    pj_ids: list[int],
    recentes: dict[int, date],
    cadastro: dict[int, date] | None = None,
) -> tuple[int, bool, bool] | None:
    """Seleciona o cliente do pedido conforme o perfil comportamental.

    Retorna ``(id_cliente, eh_pj, eh_anomalia)`` ou None para rejeitar
    a iteração (nenhum cliente elegível).

    Exemplo de anomalia: pedido poucos dias antes do cadastro do cliente
    (registro recente), conforme ``RUIDO_PEDIDO_ANTES_CADASTRO``.
    """
    eh_anomalia = False
    if random.random() < RUIDO_PEDIDO_ANTES_CADASTRO and recentes:
        id_cli = random.choice(list(recentes))
        eh_anomalia = True
    else:
        r = random.random()
        if r < 0.40 and super_ativos:
            id_cli = random.choice(list(super_ativos))
        elif r < 0.43 and inativos:
            id_cli = random.choice(list(inativos))
        elif normais:
            id_cli = random.choice(normais)
        else:
            return None
    return id_cli, id_cli in pj_ids, eh_anomalia


def _compor_itens(
    por_ticket: dict[str, list[tuple[int, float, float]]],
    prods: list[tuple[int, float, float]],
    populares: set[int],
    pj: bool,
    escolhidos: set[int],
) -> tuple[list[tuple], float]:
    """Monta os itens de um pedido com preferência por produtos populares.

    Cada produto entra no máximo uma vez por pedido; clientes PJ levam
    no mínimo 5 produtos distintos com quantidades maiores.

    Returns:
        ``(itens, total)`` — itens como ``(id_produto, qtd, preco, custo)``
        e o valor bruto somando ``qtd * preco``. ``itens`` vazio significa
        pedido descartado.
    """
    n_itens = random.randint(5, 10) if pj else random.randint(1, 4)
    tickets = random.choices(
        ["LOW", "MID", "HIGH", "ULTRA"],
        weights=[20, 45, 30, 5] if pj else [40, 35, 20, 5],
        k=n_itens,
    )

    itens: list[tuple] = []
    total = 0.0

    for tk in tickets:
        pool = por_ticket.get(tk, [])
        if not pool:
            continue

        candidatos = [(p, pr, c) for p, pr, c in pool if p not in escolhidos]

        if random.random() < 0.60 and populares:
            pop_tk = [(p, pr, c) for p, pr, c in candidatos if p in populares]
            if pop_tk:
                candidatos = pop_tk

        if not candidatos:
            candidatos = [(p, pr, c) for p, pr, c in prods if p not in escolhidos]
        if not candidatos:
            continue

        id_prod, preco_tab, custo = random.choice(candidatos)
        escolhidos.add(id_prod)

        qtd_por_ticket = {
            "LOW": random.randint(5, 30) if pj else random.randint(1, 5),
            "MID": random.randint(2, 10) if pj else random.randint(1, 3),
            "HIGH": random.randint(1, 4) if pj else 1,
            "ULTRA": 1,
        }
        qtd = qtd_por_ticket[tk]

        preco_unit = preco_tab
        total += qtd * preco_unit
        itens.append((id_prod, qtd, preco_unit, custo))

    return itens, total


def carregar_dependencias_pedidos(
    cur,
) -> tuple[
    list[tuple[int, float, float]],
    set[int],
    dict[int, list[int]],
    list[int],
    list[int],
    dict[int, date],
]:
    """Lê do banco os dados necessários para gerar pedidos.

    Útil no modo ``--pedidos``, quando a base (produtos, funcionários e
    clientes) já existe e só a geração de pedidos será refeita.

    Returns:
        Tupla ``(prods, populares, vend_por_loja, pf_ids, pj_ids,
        recentes)`` no mesmo formato de :func:`popular_produtos` e
        :func:`popular_clientes`.
    """
    cur.execute("SELECT id_produto, preco_venda, preco_custo FROM produto")
    prods = [(id_, float(p), float(c)) for id_, p, c in cur.fetchall()]

    ordenados = sorted(prods, key=lambda x: x[1])
    populares: set[int] = {p[0] for p in ordenados[: int(len(ordenados) * 0.20)]}
    populares |= {
        p[0] for p in random.sample(ordenados[-100:], min(50, len(ordenados)))
    }

    cur.execute("SELECT id_funcionario, id_loja FROM funcionario")
    vend_por_loja: dict[int, list[int]] = {}
    for id_func, id_loja in cur.fetchall():
        vend_por_loja.setdefault(id_loja, []).append(id_func)

    cur.execute("SELECT id_cliente, tipo, data_cadastro FROM cliente")
    todas = cur.fetchall()
    pf_ids = [r[0] for r in todas if r[1] == "PF"]
    pj_ids = [r[0] for r in todas if r[1] == "PJ"]
    recente_limiar = (datetime.now() - timedelta(days=90)).date()
    recentes = {r[0]: r[2] for r in todas if r[2] >= recente_limiar}

    return prods, populares, vend_por_loja, pf_ids, pj_ids, recentes


def popular_pedidos(
    cur,
    prods: list[tuple[int, float]],
    populares: set[int],
    vend_por_loja: dict[int, list[int]],
    pf_ids: list[int],
    pj_ids: list[int],
    recentes: dict[int, date],
) -> dict[tuple[int, int, int, int], int]:
    """Gera pedidos e itens simulando comportamento realista de compra.

    Segmenta os clientes em três grupos comportamentais:

    - **Super-ativos** (8%): responsáveis por ~40% dos pedidos
    - **Inativos** (22%): raramente aparecem (~3% dos pedidos)
    - **Normais** (70%): distribuição padrão

    Aplica sazonalidade via ``SAZONALIDADE``, com amostragem por
    rejeição: meses com boost menor geram menos pedidos naturalmente.

    Pedidos PJ contêm no mínimo 5 produtos distintos (uma linha por
    produto); o desconto é calculado no nível do pedido conforme o tipo
    de loja (3% Física, 5% Online).
    Novembro tem taxa de cancelamento ligeiramente maior (Black Friday).

    Args:
        cur:           Cursor MySQL ativo.
        prods:         Lista de ``(id_produto, preco_venda, preco_custo)``.
        populares:     Conjunto de IDs de produtos com alta demanda.
        vend_por_loja: Dicionário ``{id_loja: [id_funcionario, ...]}``.
        pf_ids:        IDs de clientes Pessoa Física.
        pj_ids:        IDs de clientes Pessoa Jurídica.
        recentes:      Clientes recentes (mapeamento id → data de cadastro),
                       usados apenas na anomalia temporal.

    Returns:
        Contador ``{(id_loja, id_produto, ano, mês): unidades}`` com as
        unidades efetivamente vendidas (cancelamentos não consomem estoque).
        É a entrada do histórico de estoque, gerado depois desta etapa.
    """
    cur.execute("SELECT id_loja, tipo FROM loja")
    lojas = cur.fetchall()

    todos = pf_ids + pj_ids
    # Clientes recentes ficam fora do fluxo normal de vendas: são usados apenas
    # na anomalia temporal (RUIDO_PEDIDO_ANTES_CADASTRO), mantendo a taxa ~2% controlada.
    pool = [c for c in todos if c not in recentes]
    super_ativos = set(random.sample(pool, int(NUM_CLIENTES * 0.08)))
    inativos = set(
        random.sample(
            [c for c in pool if c not in super_ativos],
            int(NUM_CLIENTES * 0.22),
        )
    )
    normais = [c for c in pool if c not in super_ativos and c not in inativos]

    por_ticket = _indice_por_ticket(prods)

    gerados = 0
    ped_buf: list[tuple] = []
    item_buf: list[list[tuple]] = []
    # Consumo de estoque derivado dos pedidos reais (cancelados não consomem).
    vendas_mes: dict[tuple[int, int, int, int], int] = {}
    textos_obs = [
        "Entrega em horário comercial",
        "Cliente preferencial",
        "Sem contato telefônico",
    ]

    while gerados < NUM_PEDIDOS:
        # Anomalia temporal controlada: ~2% dos pedidos vão para clientes
        # registrados recentemente, fazendo o pedido preceder o cadastro.
        escolha = _escolher_cliente(super_ativos, inativos, normais, pj_ids, recentes)
        if escolha is None:
            continue
        id_cli, pj, eh_anomalia = escolha

        # Aplica sazonalidade por amostragem por rejeição (mensal × dia da semana)
        if eh_anomalia:
            # Pedido poucos dias antes do cadastro do cliente (anomalia sutil).
            cadastro_cli = recentes.get(id_cli)
            if cadastro_cli is None:
                continue
            data = datetime.combine(
                cadastro_cli - timedelta(days=random.randint(1, 60)),
                datetime.min.time(),
            )
        else:
            dias = random.randint(0, DIAS_HISTORICO - 1)
            data = DATA_INICIO + timedelta(days=dias)
        boost = SAZONALIDADE.get(data.month, 1.0)
        boost *= SAZONALIDADE_SEMANA.get(data.weekday(), 1.0)
        if random.random() > boost / 1.80:
            continue  # rejeita pedido fora da curva sazonal

        # Seleciona loja e canal de venda
        id_loja, tipo_loja = random.choice(lojas)
        canal = (
            "Loja Física"
            if tipo_loja == "Física"
            else random.choice(["Site", "Marketplace", "WhatsApp", "Televendas"])
        )
        # Só pedidos de loja física têm atendente; online → id_funcionario NULL.
        id_func = (
            random.choice(vend_por_loja.get(id_loja, [None]))
            if canal == "Loja Física"
            else None
        )

        # Percentual de desconto baseado no tipo de loja
        # Física: 3%, Online: 5%
        percentual_desconto = 0.03 if tipo_loja == "Física" else 0.05

        # Compõe itens do pedido com preferência por produtos populares.
        escolhidos: set[int] = set()
        itens, total = _compor_itens(por_ticket, prods, populares, pj, escolhidos)

        if not itens:
            continue

        # Taxa de cancelamento maior em novembro (pico Black Friday)
        pesos_status = (
            [0.68, 0.15, 0.10, 0.07] if data.month == 11 else [0.76, 0.14, 0.07, 0.03]
        )
        status = random.choices(
            ["Concluído", "Enviado", "Processando", "Cancelado"],
            weights=pesos_status,
        )[0]

        # Desconto baseado no tipo de loja: Física = 3%, Online = 5%
        valor_bruto = round(total, 2)
        valor_desconto = round(valor_bruto * percentual_desconto, 2)
        valor_final = round(valor_bruto - valor_desconto, 2)

        obs = random.choice(textos_obs) if random.random() < RUIDO_OBS else None

        if status != "Cancelado":
            ano_mes = (id_loja, data.year, data.month)
            for id_prod_item, qtd_item, _, _ in itens:
                chave = (ano_mes[0], id_prod_item, ano_mes[1], ano_mes[2])
                vendas_mes[chave] = vendas_mes.get(chave, 0) + qtd_item

        ped_buf.append(
            (
                id_cli,
                id_loja,
                id_func,
                data,
                status,
                canal,
                valor_final,
                valor_desconto,
                obs,
            )
        )
        item_buf.append(itens)
        gerados += 1

        # Flush a cada 200 pedidos para manter transações curtas
        if len(ped_buf) >= 200:
            _flush(cur, ped_buf, item_buf)
            ped_buf.clear()
            item_buf.clear()

        if gerados % 5000 == 0:
            log.info("%d/%d pedidos gerados...", gerados, NUM_PEDIDOS)

    # Flush do buffer residual
    if ped_buf:
        _flush(cur, ped_buf, item_buf)

    log.info("%d pedidos gerados.", gerados)
    return vendas_mes


def _flush(cur, peds: list[tuple], items: list[list[tuple]]) -> None:
    """Persiste um lote de pedidos e seus respectivos itens no banco.

    Insere os pedidos um a um para capturar os ``lastrowid`` gerados,
    depois insere todos os itens em um único ``executemany`` para eficiência.

    Args:
        cur:   Cursor MySQL ativo.
        peds:  Lista de tuplas com os dados de cada pedido.
        items: Lista de listas de tuplas com os itens de cada pedido.
               O índice deve corresponder ao índice em ``peds``.
    """
    pedido_ids: list[int] = []

    for ped in peds:
        cur.execute(
            "INSERT INTO pedido "
            "(id_cliente, id_loja, id_funcionario, data_pedido, "
            "status, canal, valor_total, desconto, obs) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            ped,
        )
        pedido_ids.append(cur.lastrowid)

    # Achata itens mantendo o vínculo correto com o id_pedido de cada um
    rows_itens = [
        (id_ped, id_prod, qtd, preco, custo)
        for id_ped, itens in zip(pedido_ids, items)
        for id_prod, qtd, preco, custo in itens
    ]

    if rows_itens:
        cur.executemany(
            "INSERT INTO pedido_item "
            "(id_pedido, id_produto, quantidade, preco_unitario, "
            "custo_unitario) "
            "VALUES (%s, %s, %s, %s, %s)",
            rows_itens,
        )


# =============================================================================
# PONTO DE ENTRADA
# =============================================================================


def main() -> None:
    """Orquestra a execução completa do gerador em ordem de dependência.

    Cada etapa é comitada individualmente para facilitar o diagnóstico em
    caso de falha: se a geração de pedidos falhar, os dados base já estarão
    persistidos e podem ser inspecionados diretamente no banco.

    Modos parciais (úteis em iteração de desenvolvimento):
    - ``--clientes``: popula base + produtos/estoque/funcionários + clientes.
    - ``--pedidos``:  gera apenas pedidos, reaproveitando o que já existe.
    """
    parser = argparse.ArgumentParser(description="Gerador Mestre — TecMente")
    grupo = parser.add_mutually_exclusive_group()
    grupo.add_argument(
        "--clientes",
        action="store_true",
        help="Popula apenas as dimensões e clientes (sem pedidos).",
    )
    grupo.add_argument(
        "--pedidos",
        action="store_true",
        help="Gera apenas pedidos, usando base/clientes já existentes no banco.",
    )
    args = parser.parse_args()

    log.info("=" * 55)
    log.info("TecMente — Gerador Mestre v1.1")
    log.info("=" * 55)

    conn = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cur = conn.cursor(buffered=True)

        if not args.pedidos:
            log.info("Limpando tabelas...")
            limpar(cur)
            conn.commit()

            log.info("Populando base (lojas, departamentos, fornecedores)...")
            loja_ids, forn_ids = popular_base(cur)
            conn.commit()

            log.info("Populando produtos e categorias...")
            prods, populares = popular_produtos(cur, forn_ids)
            conn.commit()

            log.info("Populando funcionários...")
            vend = popular_funcionarios(cur, loja_ids)
            conn.commit()

            log.info("Populando clientes...")
            pf_ids, pj_ids, recentes = popular_clientes(cur)
            conn.commit()
        else:
            log.info("Modo --pedidos: lendo dependências existentes...")
            prods, populares, vend, pf_ids, pj_ids, recentes = (
                carregar_dependencias_pedidos(cur)
            )

        if args.clientes:
            log.info("=" * 55)
            log.info("Base e clientes populados (sem pedidos) com sucesso!")
            log.info("Clientes  : %d (PF + PJ)", NUM_CLIENTES)
            log.info("=" * 55)
            log.info("O estoque é gerado no passo --pedidos (depende das vendas).")
        else:
            log.info("Gerando %d pedidos...", NUM_PEDIDOS)
            vendas_mes = popular_pedidos(
                cur, prods, populares, vend, pf_ids, pj_ids, recentes
            )
            conn.commit()

            # Estoque depende das vendas: só faz sentido depois dos pedidos.
            log.info("Populando estoque temporal...")
            cur.execute("SELECT id_loja FROM loja")
            loja_ids = [linha[0] for linha in cur.fetchall()]
            popular_estoque(
                cur,
                prods,
                loja_ids,
                vendas_mes,
                DATA_INICIO.date(),
                datetime.now().date(),
            )
            conn.commit()

            log.info("=" * 55)
            log.info("Banco populado com sucesso!")
            log.info("=" * 55)
            log.info("Produtos  : %d", len(prods))
            log.info("Clientes  : %d (PF + PJ)", NUM_CLIENTES)
            log.info("Pedidos   : %d", NUM_PEDIDOS)
            log.info("Populares : %d produtos", len(populares))
            log.info(
                "Views disponíveis: vw_faturamento_mensal | vw_ranking_produtos | "
                "vw_clientes | vw_vendas_itens"
            )
            log.info(
                "                    vw_rfm | vw_vendas_canal | vw_categorias "
                "| vw_pedidos | vw_pedidos_itens"
            )

    except mysql.connector.Error as e:
        log.error("Erro MySQL: %s", e)
        if conn and conn.is_connected():
            conn.rollback()

    finally:
        if conn and conn.is_connected():
            cur.close()
            conn.close()
            log.info("Conexão fechada.")


if __name__ == "__main__":
    main()
