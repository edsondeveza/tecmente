# -*- coding: utf-8 -*-
"""
config.py — Configuração centralizada do pipeline TecMente.

Carrega as credenciais do banco de dados a partir de variáveis de
ambiente (ou arquivo .env), evitando que senhas fiquem hardcoded
em múltiplos scripts.

Uso
---
    from config import DB_CONFIG

    conn = mysql.connector.connect(**DB_CONFIG)

Autor: Edson Deveza
Versão: 1.0
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    _env_path = Path(__file__).parent / ".env"
    if _env_path.exists():
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv não instalado — usa variáveis de ambiente do SO

DB_CONFIG: dict[str, str | int] = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "user":     os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "tecmente"),
}

ENCODING: str = "utf-8-sig"
