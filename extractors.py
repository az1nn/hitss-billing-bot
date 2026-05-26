# -*- coding: utf-8 -*-
"""
Extractors module for CNPJ extractor bot.
Contains functions for extracting text and data from PDFs, XMLs, and OCR.
"""

import re
import xml.etree.ElementTree as ET
from PyPDF2 import PdfReader
from pdf2image import convert_from_path
import pytesseract

from config import CNPJ_REGEX, CNPJ_IGNORE
from logger import get_logger
from validators import only_digits, validate_cnpj

logger = get_logger(__name__)

# Mínimo de caracteres para considerar texto nativo do PDF utilizável (senão tenta OCR)
PDF_NATIVE_TEXT_MIN_CHARS = 80
# Mínimo de dígitos no texto nativo (notas costumam ter muitos números)
PDF_NATIVE_MIN_DIGITS = 40

_BR_MONEY_RE = re.compile(
    r"(?:R\$\s*)?(\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2})"
)

_INVOICE_TOTAL_LABEL_RE = re.compile(
    r"valor\s+da\s+nota|valor\s+total|total\s+da\s+nota|total\s+geral|"
    r"valor\s+l[ií]quido|total\s+a\s+pagar|vl\.?\s*total|"
    r"total\s+(?:da\s+)?nf|valor\s+(?:da\s+)?nf|"
    r"valor\s+do\s+documento|valor\s+cobrado",
    re.IGNORECASE,
)

# Só dispara extração Campinas/ISSQN quando o rótulo completo aparece (evita "ISSQN" solto).
_BASE_CALCULO_ISSQN_LABEL_RE = re.compile(
    r"base\s+de\s+c[áa]lculo\s+do\s+issqn",
    re.IGNORECASE,
)

# Valores em R$ com 2 decimais; ``(?!\d)`` evita prefixo de alíquota ``2,000000``.
_STRICT_BR_MONEY_RE = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}(?!\d)")


def extract_text_pdf(path: str) -> str:
    """Extrai texto de PDF texto pesquisável."""
    text_parts = []
    try:
        reader = PdfReader(path)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    except Exception as e:
        logger.error("Erro lendo PDF %s: %s", path, e)
    return "\n".join(text_parts)


def _native_pdf_text_looks_useful(text: str) -> bool:
    """Evita usar só camadas de texto espúrias quando a nota está na imagem."""
    if len(text) < PDF_NATIVE_TEXT_MIN_CHARS:
        return False
    lower = text.lower()
    if any(
        k in lower
        for k in (
            "cnpj",
            "nota fiscal",
            "nf-e",
            "nfe",
            "nfse",
            "valor total",
            "valor da nota",
            "tomador",
            "prestador",
            "r$",
            "duplicata",
            "fatura",
        )
    ):
        return True
    if re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", text):
        return True
    if sum(1 for c in text if c.isdigit()) >= PDF_NATIVE_MIN_DIGITS:
        return True
    return False


def extract_text_from_pdf(path: str) -> str:
    """Tenta texto nativo do PDF; se for curto ou não parecer nota, usa OCR."""
    native = extract_text_pdf(path).strip()
    if _native_pdf_text_looks_useful(native):
        logger.info("   📄 Texto nativo do PDF")
        return native
    logger.info("   📄 Texto nativo insuficiente ou sem indícios de nota; usando OCR...")
    ocr = extract_text_ocr(path).strip()
    return ocr if ocr else native


def extract_text_ocr(path: str) -> str:
    """Extrai texto de PDF via OCR (Optical Character Recognition)."""
    text_parts = []
    try:
        images = convert_from_path(path)
        for img in images:
            try:
                text = pytesseract.image_to_string(img, lang="por+eng")
                if text:
                    text_parts.append(text)
            except pytesseract.TesseractError as e:
                logger.warning("   ⚠️ Erro Tesseract ao processar página: %s", e)
                continue
    except FileNotFoundError:
        logger.error("   ❌ Arquivo não encontrado: %s", path)
    except PermissionError:
        logger.error("   ❌ Sem permissão para ler: %s", path)
    except Exception as e:
        error_type = type(e).__name__
        logger.error("   ❌ Erro no OCR (%s): %s", error_type, e)
    return "\n".join(text_parts)


def _xml_decimal_to_float(s: str) -> float:
    """Converte texto de valor no XML (ex.: 592.02 ou 592,02) para float."""
    t = s.strip().replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return float("-inf")


# Códigos de tpEvento que correspondem a cancelamento de NFe
# (110111 = Cancelamento; 110112 = Cancelamento por substituição)
_NFE_CANCEL_EVENT_CODES = {"110111", "110112"}

# Padrões que indicam que a NOTA em si está cancelada em PDFs.
# Evita falso-positivo com textos genéricos como rodapé de SAC
# ("Cancelamentos, Reclamações...") ao exigir contexto explícito da nota,
# rótulo de status/situação, ou marca d'água isolada.
_PDF_CANCEL_RE = re.compile(
    r"""
    (?:
        # 1) "nota [fiscal] [eletrônica] [de serviços] cancelad[oa]" e variantes
        \b(?:nota(?:\s+fiscal)?(?:\s+eletr[oô]nica)?(?:\s+de\s+servi[çc]os)?
            |nf|nf-?e|nfse|nfs-?e|documento|fatura|duplicata)
        \s+(?:fiscal\s+)?cancelad[oa]s?\b
        |
        # 2) "cancelad[oa] em DD..." / "cancelada por|pela|pelo|essa|esta|este..."
        \bcancelad[oa]s?\s+(?:em\s+\d|por\s+|pela\s+|pelo\s+|essa\s+|esta\s+|este\s+)
        |
        # 3) Rótulo de status/situação/estado seguido de cancelad...
        \b(?:status|situa[çc][ãa]o|estado)\s*[:\-]?\s*cancelad[oa]s?\b
        |
        # 4) Marca d'água: linha contendo APENAS "CANCELADA"/"CANCELADO" (com
        # opcionais "NOTA"/"NF"/"NFE"/"DOCUMENTO" antes)
        (?:^|\n)\s*(?:NOTA\s+(?:FISCAL\s+)?|NF\s+|NFE\s+|NF-?E\s+|DOCUMENTO\s+)?
        CANCELAD[OA]S?\s*(?:\n|$)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_pdf_status(text: str) -> str:
    """
    Detecta status da nota a partir do texto extraído de um PDF (nativo ou OCR).

    Considera cancelada quando o texto traz um sinal claro de status da
    nota: frase com contexto ("Nota Fiscal Cancelada", "Documento
    Cancelado"), rótulo ("Status: CANCELADO", "Situação: cancelada"),
    expressão temporal ("cancelada em 04/07/2017") ou marca d'água
    isolada ("CANCELADA" sozinha em uma linha). Palavras avulsas como
    "Cancelamentos" em rodapé de SAC não disparam o sinal.

    Args:
        text: texto extraído do PDF.

    Returns:
        "cancelado" se houver indício consistente de cancelamento da nota;
        "concluido" caso contrário (inclui texto vazio).
    """
    if not text:
        return "concluido"
    return "cancelado" if _PDF_CANCEL_RE.search(text) else "concluido"


def detect_nfe_status(xml_path: str) -> str:
    """
    Detecta o status da nota a partir do conteúdo do XML.

    Eventos de NFe (root ``procEventoNFe``) com ``descEvento`` contendo
    "Cancelamento" ou ``tpEvento`` em {110111, 110112} são tratados como
    notas canceladas. Demais XMLs (NFe regulares, outros eventos) são
    considerados concluídos.

    Args:
        xml_path: caminho para o arquivo XML.

    Returns:
        "cancelado" para eventos de cancelamento de NFe; "concluido"
        em qualquer outro caso (inclusive falha de parsing, para não
        bloquear o fluxo).
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except (FileNotFoundError, PermissionError, ET.ParseError, UnicodeDecodeError) as e:
        logger.warning("   ⚠️ Não foi possível detectar status do XML %s: %s", xml_path, e)
        return "concluido"

    root_local = root.tag.split('}', 1)[-1]
    if root_local != "procEventoNFe":
        return "concluido"

    for elem in root.iter():
        tag_local = elem.tag.split('}', 1)[-1]
        text = (elem.text or "").strip()
        if not text:
            continue
        if tag_local == "descEvento" and "cancel" in text.lower():
            return "cancelado"
        if tag_local == "tpEvento" and text in _NFE_CANCEL_EVENT_CODES:
            return "cancelado"

    return "concluido"


def extract_text_xml(path: str) -> tuple[str, bool]:
    """
    Extrai texto de arquivo XML (NFe).

    Retorna (texto_plano, True) se já registrou o total da nota a partir do XML
    (maior vNF / ValorServicos quando há vários nós).
    """
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        text_parts = []
        vnf_brutos: list[str] = []
        valor_servicos_brutos: list[str] = []

        # Extrai texto de todos os elementos
        for elem in root.iter():
            if elem.text and elem.text.strip():
                text_parts.append(elem.text.strip())
            if elem.tail and elem.tail.strip():
                text_parts.append(elem.tail.strip())

            # Extrai CNPJ e valores relevantes
            if elem.tag.endswith('CNPJ') and elem.text:
                cnpj_clean = only_digits(elem.text)
                if cnpj_clean not in CNPJ_IGNORE:
                    text_parts.append(f"CNPJ: {elem.text}")
            if (elem.tag.endswith('vNF') or
                elem.tag.endswith('ValorServicos') or
                elem.tag.endswith('vTotTrib') or
                'total' in elem.tag.lower()) and elem.text:
                text_parts.append(f"Valor: {elem.text}")
                if elem.tag.endswith('vNF'):
                    vnf_brutos.append(elem.text.strip())
                elif elem.tag.endswith('ValorServicos'):
                    valor_servicos_brutos.append(elem.text.strip())

        valor_xml_impresso = False
        if vnf_brutos:
            melhor = max(vnf_brutos, key=_xml_decimal_to_float)
            logger.info("   💰 Valor encontrado NFe: %s", melhor)
            valor_xml_impresso = True
        elif valor_servicos_brutos:
            melhor = max(valor_servicos_brutos, key=_xml_decimal_to_float)
            logger.info("   💰 Valor encontrado NFe: %s", melhor)
            valor_xml_impresso = True

        return " ".join(text_parts), valor_xml_impresso
    except FileNotFoundError:
        logger.error("   ❌ Arquivo XML não encontrado: %s", path)
        return "", False
    except PermissionError:
        logger.error("   ❌ Sem permissão para ler XML: %s", path)
        return "", False
    except ET.ParseError as e:
        logger.error("   ❌ XML corrompido ou malformado: %s", e)
        return "", False
    except UnicodeDecodeError as e:
        logger.error("   ❌ Erro de codificação no XML: %s", e)
        return "", False
    except Exception as e:
        error_type = type(e).__name__
        logger.error("   ❌ Erro lendo XML (%s): %s", error_type, e)
        return "", False


def extract_cnpjs(text: str) -> list:
    """Extrai CNPJs válidos de um texto."""
    cnpjs = []
    for m in CNPJ_REGEX.finditer(text):
        raw = m.group(1)
        # Remove tudo que não for dígito, incluindo vírgulas, pontos, barras, hífens e caracteres especiais como ~
        digits = only_digits(raw.replace('~', ''))
        # Se o CNPJ tem menos de 14 dígitos após limpeza, pode ser que o ~ substitua um dígito
        if len(digits) < 14 and '~' in raw:
            # Tenta substituir ~ por cada dígito de 0-9 e valida
            for digit in '0123456789':
                test_cnpj = only_digits(raw.replace('~', digit))
                if len(test_cnpj) == 14 and test_cnpj not in CNPJ_IGNORE and validate_cnpj(test_cnpj):
                    cnpjs.append(test_cnpj)
                    break
        elif len(digits) == 14:
            if digits in CNPJ_IGNORE:
                continue
            if validate_cnpj(digits):
                cnpjs.append(digits)
    return list(set(cnpjs))  # remove duplicados


def _parse_br_money_token(line: str):
    """Retorna (float, string_bruta) do primeiro valor monetário BR na linha, ou None."""
    m = _BR_MONEY_RE.search(line)
    if not m:
        return None
    raw = m.group(1)
    try:
        return float(raw.replace(".", "").replace(",", ".")), raw
    except ValueError:
        return None


def extract_invoice_values(text: str) -> list:
    """Extrai valores numéricos (com casas decimais) do texto (rótulos comuns + RJ legado)."""
    values: list[float] = []
    lines = text.splitlines()

    # Rótulos comuns + mesma linha ou até 4 linhas abaixo (layout quebrado / OCR)
    for i, linha in enumerate(lines):
        if not _INVOICE_TOTAL_LABEL_RE.search(linha):
            continue
        for chunk in [linha] + lines[i + 1: i + 5]:
            parsed = _parse_br_money_token(chunk)
            if parsed:
                val, raw_value = parsed
                values.append(val)
                logger.info("   💰 Valor encontrado: %s", raw_value)
                break
        if values:
            break

    # Legado RJ: "VALOR DA NOTA" com janela maior no texto completo
    if not values:
        pattern = re.compile(
            r"VALOR\s+DA\s+NOTA[^\d]{0,120}([\d\.]+,\d{2}|\d+,\d{2})",
            re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(text):
            raw_value = match.group(1)
            logger.info("   💰 Valor encontrado RJ: %s", raw_value)
            clean_value = raw_value.replace(".", "").replace(",", ".")
            try:
                values.append(float(clean_value))
            except ValueError:
                continue
            break

    return values


def extract_total_service_values(text: str):
    """Extrai valores numéricos (com casas decimais) do texto 'Vl. Total dos Serviços'."""
    linhas = text.splitlines()
    valor_encontrado = None

    for i, linha in enumerate(linhas):
        if "Total dos Serviços" in linha:
            if i + 1 < len(linhas):
                proxima_linha = linhas[i + 1]
                if proxima_linha == "":
                    proxima_linha = linhas[i + 2]
                    
                # Procura primeiro número no formato brasileiro (com R$ opcional)
                match = re.search(r"R?\$?\s?(\d{1,3}(?:\.\d{3})*,\d{2})", proxima_linha)
                if match:
                    valor_encontrado = match.group(1)  # só o número
                    break
    if valor_encontrado is not None:
        logger.info("   💰 Valor encontrado em DF: %s", valor_encontrado)
        return valor_encontrado


def _strict_br_money_tokens(linha: str) -> list[str]:
    """Todos os valores ``X.xxx,xx`` na linha (2 decimais, não prefixo de ``2,000000``)."""
    return _STRICT_BR_MONEY_RE.findall(linha)


def _br_money_str_to_float(s: str) -> float:
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return float("nan")


def _campinas_pick_base_from_tokens(toks: list[str]) -> str | None:
    """
    Identifica a coluna **Base de cálculo do ISSQN** em linhas de dados da NFSe Campinas.

    Na tabela *Cálculo do ISSQN* a ordem é: total NFSe, deduções, desc., **base**, alíq., valor ISSQN.
    No bloco *Valor total* (rodapé) a primeira coluna numérica é a base.
    """
    if len(toks) < 4:
        return None
    t0 = _br_money_str_to_float(toks[0])
    t3 = _br_money_str_to_float(toks[3])
    t4 = _br_money_str_to_float(toks[4]) if len(toks) > 4 else float("nan")
    # Linha da tabela de cálculo: valor do ISSQN (última coluna) é bem menor que a base.
    if len(toks) >= 5 and t3 > 0 and t4 < t3 * 0.45:
        return toks[3]
    # Linha do resumo "Valor total": base na 1ª coluna; colunas 3–4 costumam ser descontos zerados.
    if len(toks) >= 5 and abs(t3) < 1e-6 and t0 > 0:
        return toks[0]
    if len(toks) >= 4 and t3 > 0:
        return toks[3]
    return None


def extract_nfse_campinas_total(text: str) -> str | None:
    """
    Valor da coluna **Base de cálculo do ISSQN** na NFSe Campinas.

    Usa o layout oficial (tabela *Cálculo do ISSQN* ou bloco *Valor total*), não o primeiro
    número da linha (que pode ser total, alíquota ou **valor do ISSQN**).
    """
    linhas = text.splitlines()

    def _emit(base: str) -> str:
        logger.info("   💰 valor da nota (base cálculo ISSQN): %s", base)
        return base

    for i, linha in enumerate(linhas):
        if not _BASE_CALCULO_ISSQN_LABEL_RE.search(linha):
            continue
        chunk_nfse = " ".join(linhas[max(0, i - 2) : i + 1]).lower()

        # Tabela "Cálculo do ISSQN": cabeçalho com Valor total da NFSe + Base (mesma ou linha anterior).
        if "valor total da nfse" in chunk_nfse:
            for j in range(1, min(14, len(linhas) - i)):
                row = linhas[i + j].strip()
                if not row:
                    continue
                toks = _strict_br_money_tokens(row)
                if len(toks) >= 4 and _br_money_str_to_float(toks[3]) > 0:
                    return _emit(toks[3])
            continue

        # Bloco "Valor total" / rodapé: primeira coluna numérica = base.
        if "valor líquido" in chunk_nfse and "nfse" in chunk_nfse:
            for j in range(1, min(14, len(linhas) - i)):
                row = linhas[i + j].strip()
                toks = _strict_br_money_tokens(row)
                if toks and _br_money_str_to_float(toks[0]) > 0:
                    return _emit(toks[0])
            continue

        # Contexto Campinas: tenta deduzir coluna pela forma dos valores (base vs valor ISSQN).
        win = "\n".join(linhas[max(0, i - 3) : min(len(linhas), i + 14)]).lower()
        if "cálculo do issqn" not in win and "calculo do issqn" not in win:
            continue
        for j in range(0, min(14, len(linhas) - i)):
            row = linhas[i + j].strip()
            if not row or re.fullmatch(r"0+(?:,0{2})?", row):
                continue
            toks = _strict_br_money_tokens(row)
            pick = _campinas_pick_base_from_tokens(toks)
            if pick and _br_money_str_to_float(pick) > 0:
                return _emit(pick)

    return None


def try_extract_value(text: str):
    """
    Tenta extrair valor da nota usando múltiplos extratores.
    Retorna o primeiro valor encontrado.
    """
    extractors = [
        extract_nfse_campinas_total,
        extract_total_service_values,
        extract_invoice_values
    ]
    for extractor in extractors:
        result = extractor(text)

        # Para extract_invoice_values, retorna lista, então verifica se tem valor
        if isinstance(result, list) and result:
            return result[0]
        elif result:
            return result
    return None
