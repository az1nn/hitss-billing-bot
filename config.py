# -*- coding: utf-8 -*-
"""
Configuration module for CNPJ extractor bot.
Contains constants, regex patterns, and configuration values.
"""

import os
import re

# Regex para achar CNPJs - incluindo vírgulas e caracteres especiais
CNPJ_REGEX = re.compile(r'(\d{2}[.,]?\d{3}[.,]?\d{3}[/]?\d{4}[-~]?[0-9~]+)')

# CNPJs da hitss que não podem ser capturados
CNPJ_IGNORE = ["11168199000188", "11168199000340", "11168199000269"]

# Pasta padrão para processamento de arquivos
DEFAULT_FOLDER = "pdfs"
os.makedirs(DEFAULT_FOLDER, exist_ok=True)

# Configurações de saída
OUTPUT_FOLDER = "output"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
ZIP_FOLDER = "zips"
ZIP_OUTPUT_DIR = os.path.join(OUTPUT_FOLDER, ZIP_FOLDER)
os.makedirs(ZIP_OUTPUT_DIR, exist_ok=True)
CSV_FILENAME = "invoice_summary.csv"

# SharePoint sync
SHAREPOINT_STATE_DB = os.path.join(OUTPUT_FOLDER, "sharepoint_state.db")
SHAREPOINT_FOLDER_PATH = "FATURAMENTO/Notas Eletronicas"
DOWNLOAD_FOLDER = os.environ.get("DOWNLOAD_FOLDER", DEFAULT_FOLDER)

# Logging (podem ser sobrescritos por variáveis de ambiente)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.environ.get("LOG_FILE", os.path.join(OUTPUT_FOLDER, "billing.log"))
