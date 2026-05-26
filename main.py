# -*- coding: utf-8 -*-
"""
Main module for CNPJ extractor bot.
Entry point for processing PDFs and XML files.
"""

import os
import sys

from config import DEFAULT_FOLDER
from logger import get_logger
from extractors import (
    extract_text_from_pdf,
    extract_text_xml,
    extract_cnpjs,
    try_extract_value,
    detect_nfe_status,
    detect_pdf_status,
)
import output_handler
import sharepoint_db

logger = get_logger(__name__)


def process_pdfs(folder: str = DEFAULT_FOLDER) -> None:
    """
    Processa todos os PDFs e XMLs na pasta especificada.
    
    Args:
        folder: Caminho da pasta contendo os arquivos a serem processados.
    """
    processed = 0
    errors = 0
    cancelados = 0

    sharepoint_db.init_db()

    for file in os.listdir(folder):
        if not (file.lower().endswith(".pdf") or file.lower().endswith(".xml")):
            continue
        path = os.path.join(folder, file)
        
        logger.info("🔎 Processando %s...", file)
        
        try:
            # Verifica o tipo de arquivo
            xml_ja_tem_valor = False
            status = sharepoint_db.STATUS_CONCLUIDO
            if file.lower().endswith(".pdf"):
                logger.info("   📙 Processando PDF...")
                text = extract_text_from_pdf(path)
                status = detect_pdf_status(text)
            elif file.lower().endswith(".xml"):
                logger.info("   📗 Processando XML...")
                text, xml_ja_tem_valor = extract_text_xml(path)
                status = detect_nfe_status(path)
            else:
                logger.warning("   ⚠️ Tipo de arquivo não suportado: %s", file)
                continue
            
            # Verifica se conseguiu extrair texto
            if not text or not text.strip():
                logger.warning("   ⚠️ Nenhum texto extraído do arquivo")
                errors += 1
                continue
            
            if not xml_ja_tem_valor:
                try_extract_value(text)
            cnpjs = extract_cnpjs(text)
                
            if cnpjs:
                logger.info("   ➡️ CNPJs encontrados: %s", ", ".join(cnpjs))
            else:
                logger.warning("   ⚠️  Nenhum CNPJ válido encontrado")

            if status == sharepoint_db.STATUS_CANCELADO:
                logger.info("   🚫 Status da nota: cancelado")
                cancelados += 1
            else:
                logger.info("   ✔️ Status da nota: concluído")

            updated = sharepoint_db.set_status_by_file_name(file, status)
            if not updated:
                logger.debug("   ℹ️ Arquivo %s não está no SQLite; status não persistido.", file)

            processed += 1
            
        except Exception as e:
            error_type = type(e).__name__
            logger.error("   ❌ Erro inesperado (%s): %s", error_type, e)
            errors += 1
            continue
    
    logger.info(
        "✅ Processamento concluído: %s arquivos processados, %s cancelados, %s erros",
        processed, cancelados, errors,
    )


def main():
    """
    Função principal com opções de processamento.
    
    Opções:
        python3 main.py                  - Processamento padrão (extração de texto e CNPJs)
        python3 main.py --output         - Processamento + geração de ZIPs e CSV
        python3 main.py --output-only    - Apenas geração de ZIPs e CSV (sem processamento de texto)
        python3 main.py --sync           - Sincroniza arquivos do SharePoint
        python3 main.py --sync --output  - Sincroniza + processa + gera output
    """
    args = sys.argv[1:]

    do_sync = "--sync" in args
    do_output = "--output" in args
    do_output_only = "--output-only" in args

    remaining = [a for a in args if a not in ("--sync", "--output", "--output-only")]
    folder = remaining[0] if remaining else DEFAULT_FOLDER

    if not args:
        process_pdfs()
        return

    if do_sync:
        import sharepoint_sync
        logger.info("🔄 Iniciando sincronização com SharePoint...")
        ok = sharepoint_sync.sync()
        if not ok:
            logger.error("❌ Sincronização falhou. Verifique os logs acima.")
            sys.exit(1)
        logger.info("✅ Sincronização concluída.")

    if do_output_only:
        logger.info("📦 Executando apenas geração de outputs")
        output_handler.process_and_export(folder)
    elif do_output:
        logger.info("🔄 Executando processamento completo (texto + output)")
        process_pdfs(folder)
        logger.info("%s", "=" * 60)
        output_handler.process_and_export(folder)
    elif not do_sync:
        logger.error("❌ Opção inválida: %s", " ".join(args))
        logger.error("Uso: python3 main.py [--sync] [--output|--output-only] [pasta]")
        sys.exit(1)


if __name__ == "__main__":
    main()
