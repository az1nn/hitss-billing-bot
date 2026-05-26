# -*- coding: utf-8 -*-
"""
Output handler module for invoice processing.
Handles ZIP creation, data structuring, and CSV export for NFSe invoices.
"""

import os
import re
import csv
import zipfile
from dataclasses import dataclass, asdict, fields
from pathlib import Path
from typing import List, Optional, Dict
import xml.etree.ElementTree as ET
from datetime import datetime

from config import OUTPUT_FOLDER, ZIP_FOLDER, CSV_FILENAME
from logger import get_logger
from validators import only_digits

logger = get_logger(__name__)

# Namespace para NFSe ABRASF 2.04
NFSE_NS = {'nfse': 'http://www.abrasf.org.br/nfse.xsd'}

@dataclass
class InvoiceData:
    """Structured data extracted from NFSe invoice."""
    source_file: str  # Original file path
    zip_path: str  # Generated ZIP file path
    invoice_number: str  # Número da Nota
    total_value: float  # ValorServicos or ValorLiquidoNfse
    uf_prestador: str  # UF do prestador
    uf_tomador: str  # UF do tomador
    cnpj_prestador: str  # CNPJ do prestador (14 digits)
    cnpj_tomador: str  # CNPJ do tomador (14 digits)
    data_emissao: Optional[str] = None
    razao_social_prestador: Optional[str] = None
    razao_social_tomador: Optional[str] = None
    codigo_verificacao: Optional[str] = None


def extract_invoice_data_from_xml(xml_path: str) -> Optional[InvoiceData]:
    """
    Extract structured data from NFSe XML file.
    
    Args:
        xml_path: Path to the XML file
        
    Returns:
        InvoiceData object with extracted information or None if extraction fails
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        
        # Helper function to find text with namespace
        def find_text(xpath: str, default: str = "") -> str:
            try:
                # Try with namespace first
                element = root.find(xpath, NFSE_NS)
                if element is not None:
                    return element.text or default
                
                # Try without namespace (fallback)
                element = root.find(xpath.replace('nfse:', ''))
                if element is not None:
                    return element.text or default
                    
                # Try with local-name (more robust)
                xpath_local = xpath.replace('nfse:', '*[local-name()="').replace('/', '/*[local-name()="') + '"]'
                for char in ['/', '.']:
                    xpath_local = xpath_local.replace(char + '*[local-name()="', char)
                xpath_local = xpath_local.replace('*[local-name()=""]', '*')
                
                element = root.find(xpath_local)
                return element.text if element is not None else default
                
            except Exception:
                return default
        
        # Extract basic invoice data
        invoice_number = find_text('.//nfse:InfNfse/nfse:Numero') or find_text('.//Numero')
        if not invoice_number:
            logger.warning("⚠️  Could not find invoice number in %s", xml_path)
            return None
            
        # Extract monetary values (try multiple paths)
        valor_servicos = find_text('.//nfse:Servico/nfse:Valores/nfse:ValorServicos') or find_text('.//ValorServicos')
        valor_liquido = find_text('.//nfse:ValoresNfse/nfse:ValorLiquidoNfse') or find_text('.//ValorLiquidoNfse')
        
        total_value = 0.0
        try:
            if valor_servicos:
                total_value = float(valor_servicos)
            elif valor_liquido:
                total_value = float(valor_liquido)
        except ValueError:
            logger.warning("⚠️  Could not parse monetary value in %s", xml_path)
            
        # Extract UF data
        uf_prestador = find_text('.//nfse:PrestadorServico/nfse:Endereco/nfse:Uf') or find_text('.//PrestadorServico//Uf')
        uf_tomador = find_text('.//nfse:TomadorServico/nfse:Endereco/nfse:Uf') or find_text('.//TomadorServico//Uf')
        
        # Extract CNPJ data
        cnpj_prestador_raw = find_text('.//nfse:Prestador/nfse:CpfCnpj/nfse:Cnpj') or find_text('.//Prestador//Cnpj')
        cnpj_tomador_raw = find_text('.//nfse:TomadorServico/nfse:IdentificacaoTomador/nfse:CpfCnpj/nfse:Cnpj') or find_text('.//TomadorServico//Cnpj')
        
        # Clean CNPJs (remove formatting)
        cnpj_prestador = only_digits(cnpj_prestador_raw) if cnpj_prestador_raw else ""
        cnpj_tomador = only_digits(cnpj_tomador_raw) if cnpj_tomador_raw else ""
        
        # Extract optional fields
        data_emissao = find_text('.//nfse:InfNfse/nfse:DataEmissao') or find_text('.//DataEmissao')
        razao_social_prestador = find_text('.//nfse:PrestadorServico/nfse:RazaoSocial') or find_text('.//PrestadorServico//RazaoSocial')
        razao_social_tomador = find_text('.//nfse:TomadorServico/nfse:RazaoSocial') or find_text('.//TomadorServico//RazaoSocial')
        codigo_verificacao = find_text('.//nfse:InfNfse/nfse:CodigoVerificacao') or find_text('.//CodigoVerificacao')
        
        return InvoiceData(
            source_file=xml_path,
            zip_path="",  # Will be set when ZIP is created
            invoice_number=invoice_number,
            total_value=total_value,
            uf_prestador=uf_prestador,
            uf_tomador=uf_tomador,
            cnpj_prestador=cnpj_prestador,
            cnpj_tomador=cnpj_tomador,
            data_emissao=data_emissao,
            razao_social_prestador=razao_social_prestador,
            razao_social_tomador=razao_social_tomador,
            codigo_verificacao=codigo_verificacao
        )
        
    except Exception as e:
        logger.error("❌ Error extracting data from %s: %s", xml_path, e)
        return None


def _copy_invoice_data(data: InvoiceData) -> InvoiceData:
    """Return a copy of InvoiceData so cache is not mutated."""
    return InvoiceData(
        source_file=data.source_file,
        zip_path=data.zip_path,
        invoice_number=data.invoice_number,
        total_value=data.total_value,
        uf_prestador=data.uf_prestador,
        uf_tomador=data.uf_tomador,
        cnpj_prestador=data.cnpj_prestador,
        cnpj_tomador=data.cnpj_tomador,
        data_emissao=data.data_emissao,
        razao_social_prestador=data.razao_social_prestador,
        razao_social_tomador=data.razao_social_tomador,
        codigo_verificacao=data.codigo_verificacao,
    )


def create_individual_zip(source_path: str, output_dir: str) -> str:
    """
    Create individual ZIP for a single file (PDF or XML).
    
    Args:
        source_path: Path to the source file
        output_dir: Directory where ZIP will be created
        
    Returns:
        Path to the created ZIP file
    """
    try:
        # Get source file info
        source_file = Path(source_path)
        zip_name = f"{source_file.stem}.zip"
        zip_path = Path(output_dir) / zip_name
        
        # Create ZIP file
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.write(source_path, source_file.name)
            
        logger.info("📦 Created ZIP: %s", zip_path)
        return str(zip_path)
        
    except Exception as e:
        logger.error("❌ Error creating ZIP for %s: %s", source_path, e)
        return ""


def export_to_csv(invoices: List[InvoiceData], output_path: str) -> None:
    """
    Export list of InvoiceData to CSV.
    
    Args:
        invoices: List of InvoiceData objects
        output_path: Path where CSV will be saved
    """
    if not invoices:
        logger.warning("⚠️  No invoices to export")
        return
        
    try:
        # Define CSV headers (in Portuguese for clarity)
        fieldnames = [
            'caminho_zip',
            'numero_nota', 
            'valor_total',
            'uf_prestador',
            'uf_tomador',
            'cnpj_prestador',
            'cnpj_tomador',
            'arquivo_origem',
            'data_emissao',
            'razao_social_prestador',
            'razao_social_tomador',
            'codigo_verificacao'
        ]
        
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for invoice in invoices:
                # Map InvoiceData fields to CSV fields
                row = {
                    'caminho_zip': invoice.zip_path,
                    'numero_nota': invoice.invoice_number,
                    'valor_total': invoice.total_value,
                    'uf_prestador': invoice.uf_prestador,
                    'uf_tomador': invoice.uf_tomador,
                    'cnpj_prestador': invoice.cnpj_prestador,
                    'cnpj_tomador': invoice.cnpj_tomador,
                    'arquivo_origem': invoice.source_file,
                    'data_emissao': invoice.data_emissao or '',
                    'razao_social_prestador': invoice.razao_social_prestador or '',
                    'razao_social_tomador': invoice.razao_social_tomador or '',
                    'codigo_verificacao': invoice.codigo_verificacao or ''
                }
                writer.writerow(row)
                
        logger.info("📊 CSV exported: %s (%s invoices)", output_path, len(invoices))
        
    except Exception as e:
        logger.error("❌ Error exporting CSV: %s", e)


def process_and_export(folder: str) -> List[InvoiceData]:
    """
    Main function: process all files, create ZIPs, export CSV.
    
    Args:
        folder: Folder containing PDF and XML files to process
        
    Returns:
        List of processed InvoiceData objects
    """
    logger.info("🔄 Starting output processing for folder: %s", folder)
    
    if not os.path.exists(folder):
        logger.error("❌ Folder not found: %s", folder)
        return []
    
    # Setup output directories
    zip_output_dir = os.path.join(OUTPUT_FOLDER, ZIP_FOLDER)
    csv_output_path = os.path.join(OUTPUT_FOLDER, CSV_FILENAME)
    
    # XMLs that are used as companion of a PDF (same stem or same invoice number): no separate CSV row
    pdf_stems_lower = {
        Path(f).stem.lower() for f in os.listdir(folder)
        if f.lower().endswith('.pdf')
    }
    xml_used_as_companion = set()
    for f in os.listdir(folder):
        if f.lower().endswith('.xml') and Path(f).stem.lower() in pdf_stems_lower:
            xml_used_as_companion.add(os.path.normpath(os.path.join(folder, f)))
    
    # Cache XML -> InvoiceData so we can pair by invoice number and avoid parsing twice
    xml_invoice_data_cache: Dict[str, Optional[InvoiceData]] = {}
    for f in os.listdir(folder):
        if f.lower().endswith('.xml'):
            path = os.path.normpath(os.path.join(folder, f))
            xml_invoice_data_cache[path] = extract_invoice_data_from_xml(path)
    
    invoices = []
    processed_files = 0
    
    # Process all XML and PDF files
    for filename in os.listdir(folder):
        if not (filename.lower().endswith('.xml') or filename.lower().endswith('.pdf')):
            continue
            
        file_path = os.path.join(folder, filename)
        file_path_norm = os.path.normpath(file_path)
        processed_files += 1
        
        logger.info("📄 Processing: %s", filename)
        
        # Create individual ZIP
        zip_path = create_individual_zip(file_path, zip_output_dir)
        
        if filename.lower().endswith('.xml'):
            # XML: add row only if not used as companion of a PDF
            if file_path_norm in xml_used_as_companion:
                logger.warning("📎 XML used as companion for PDF (no separate row)")
                continue
            invoice_data = xml_invoice_data_cache.get(file_path_norm) or extract_invoice_data_from_xml(file_path)
            if invoice_data:
                invoice_data = _copy_invoice_data(invoice_data)
                invoice_data.zip_path = zip_path
                invoices.append(invoice_data)
                logger.info("✅ Extracted data: Invoice #%s, Value: R$ %s", invoice_data.invoice_number, f"{invoice_data.total_value:,.2f}")
        else:
            # PDF: enrich with XML data if same-stem XML exists (case-insensitive) or same invoice number in name
            stem = Path(file_path).stem
            companion_xml_path = None
            companion_data = None
            # 1) Try same stem (case-insensitive)
            for f in os.listdir(folder):
                if f.lower().endswith('.xml') and Path(f).stem.lower() == stem.lower():
                    candidate = os.path.normpath(os.path.join(folder, f))
                    companion_data = xml_invoice_data_cache.get(candidate)
                    if companion_data:
                        companion_xml_path = candidate
                        break
            # 2) Try match by invoice number in PDF name (e.g. "NF 402 HONEYWELL" vs XML with Numero 402)
            if not companion_data:
                numbers_in_stem = re.findall(r'\d+', stem)
                for path, data in xml_invoice_data_cache.items():
                    if data and data.invoice_number and data.invoice_number.strip() in numbers_in_stem:
                        companion_xml_path = path
                        companion_data = data
                        xml_used_as_companion.add(path)
                        break
            if companion_xml_path and companion_data:
                invoice_data = _copy_invoice_data(companion_data)
                invoice_data.source_file = file_path
                invoice_data.zip_path = zip_path
                invoices.append(invoice_data)
                logger.info("✅ PDF enriched with XML data: Invoice #%s, Value: R$ %s", invoice_data.invoice_number, f"{invoice_data.total_value:,.2f}")
            else:
                pdf_data = InvoiceData(
                    source_file=file_path,
                    zip_path=zip_path,
                    invoice_number="N/A (PDF)",
                    total_value=0.0,
                    uf_prestador="",
                    uf_tomador="",
                    cnpj_prestador="",
                    cnpj_tomador=""
                )
                invoices.append(pdf_data)
                logger.info("📄 PDF archived (no data extraction)")
    
    # Export CSV if we have data
    if invoices:
        export_to_csv(invoices, csv_output_path)
    
    # Summary
    xml_count = len([i for i in invoices if i.invoice_number != "N/A (PDF)"])
    pdf_count = len([i for i in invoices if i.invoice_number == "N/A (PDF)"])
    
    logger.info("📋 Processing Summary:")
    logger.info("   📁 Files processed: %s", processed_files)
    logger.info("   📦 ZIPs created: %s", len(invoices))
    logger.info("   🧾 XMLs with data: %s", xml_count)
    logger.info("   📄 PDFs archived: %s", pdf_count)
    logger.info("   📊 CSV exported: %s", csv_output_path)
    logger.info("   📂 ZIP folder: %s", zip_output_dir)
    
    return invoices


if __name__ == "__main__":
    # For standalone testing
    from config import DEFAULT_FOLDER
    process_and_export(DEFAULT_FOLDER)