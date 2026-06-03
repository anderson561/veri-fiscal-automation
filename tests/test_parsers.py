import pytest
from src.transformers.sief_parser import SiefParser

# Mock de texto extraído do PDF (Baseado nas imagens)
MOCK_PDF_TEXT = """
Diagnóstico Fiscal na Receita Federal
Pendência - Débito (SIEF)
CNPJ: 62.652.792/0001-36
Receita             PA/Exerc. Dt. Vcto    Vl. Original Sdo. Devedor    Multa    Juros Sdo. Dev. Cons. Situação
0561-07 - IRRF      12/2025   20/01/2026        114,76       114,76    18,55     2,29        135,60   DEVEDOR
1082-01 - CP-SEGUR. 11/2025   19/12/2025        895,07       895,07   179,01    28,28      1.102,36   DEVEDOR
1082-01 - CP-SEGUR. 12/2025   20/01/2026      1.772,21     1.772,21   286,56    35,44      2.094,21   DEVEDOR
SIMPLES NAC.        11/2025   22/12/2025     19.173,92    19.173,92 3.834,78   605,89     23.614,59   DEVEDOR
"""

def test_sief_parser_extracts_all_debts():
    """Valida se o regex extrai corretamente as 4 linhas de débitos com complexidade de números brasileiros"""
    result = SiefParser.parse_text(MOCK_PDF_TEXT)
    
    assert len(result) == 4
    
    # Valida linha simples sem milhar
    assert result[0] == {
        "receita": "0561-07 - IRRF",
        "pa_exerc": "12/2025",
        "dt_vcto": "20/01/2026",
        "vl_original": "114,76",
        "sdo_devedor": "114,76",
        "multa": "18,55",
        "juros": "2,29",
        "sdo_dev_cons": "135,60",
        "situacao": "DEVEDOR"
    }
    
    # Valida linha com milhar brasileiro (.) e decimal (,)
    assert result[3] == {
        "receita": "SIMPLES NAC.",
        "pa_exerc": "11/2025",
        "dt_vcto": "22/12/2025",
        "vl_original": "19.173,92",
        "sdo_devedor": "19.173,92",
        "multa": "3.834,78",
        "juros": "605,89",
        "sdo_dev_cons": "23.614,59",
        "situacao": "DEVEDOR"
    }

@pytest.mark.parametrize("invalid_row", [
    "0561-07 - IRRF 12/2025 20/01/2026 114.76 DEVEDOR", # Faltam colunas
    "SIMPLES NAC. 11/25 22/12/2025 10,00 10,00 1,00 1,00 12,00 DEVEDOR", # Ano com 2 dígitos
])
def test_sief_parser_rejects_invalid_rows(invalid_row):
    """Garante que a regex não dê falso positivo em linhas corrompidas."""
    result = SiefParser.parse_text(invalid_row)
    assert len(result) == 0
