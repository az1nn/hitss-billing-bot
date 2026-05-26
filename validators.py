# -*- coding: utf-8 -*-
"""
Validators module for CNPJ extractor bot.
Contains validation functions for CNPJ and other data.
"""

import re


def only_digits(s: str) -> str:
    """Remove tudo que não for dígito."""
    return re.sub(r'\D', '', s)


def validate_cnpj(cnpj: str) -> bool:
    """
    Valida CNPJ usando algoritmo de verificação de dígitos.
    
    Args:
        cnpj: String contendo apenas os 14 dígitos do CNPJ.
        
    Returns:
        True se o CNPJ é válido, False caso contrário.
    """
    if len(cnpj) != 14:
        return False
    if cnpj == cnpj[0] * 14:
        return False

    def calc_digit(digs, multipliers):
        s = sum(int(d) * m for d, m in zip(digs, multipliers))
        r = s % 11
        return '0' if r < 2 else str(11 - r)

    base12 = cnpj[:12]
    m1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = calc_digit(base12, m1)
    m2 = [6] + m1
    d2 = calc_digit(base12 + d1, m2)
    return cnpj[-2:] == d1 + d2
