import os
from src.transformers.pdf_generator import PdfGenerator

def test_generate_separate_reports():
    # Mock data
    data = [
        {
            "cnpj": "11.111.111/0001-11",
            "company_name": "Empresa com Débitos",
            "findings": {
                "debts": [{"receita": "IRRF", "pa_exerc": "12/2025", "dt_vcto": "20/01/2026", "vl_original": "100,00", "sdo_dev_cons": "120,00"}],
                "omissions": [],
                "parc": []
            }
        },
        {
            "cnpj": "22.222.222/0001-22",
            "company_name": "Empresa com Omissões",
            "findings": {
                "debts": [],
                "omissions": [{"tipo": "DCTFWEB", "detalhe": "Período: 01/2025"}],
                "parc": []
            }
        },
        {
            "cnpj": "33.333.333/0001-33",
            "company_name": "Empresa com Parcelamento",
            "findings": {
                "debts": [],
                "omissions": [],
                "parc": [{"tipo": "PARCSN", "atraso": "3"}]
            }
        },
        {
            "cnpj": "44.444.444/0001-44",
            "company_name": "Empresa com Tudo",
            "findings": {
                "debts": [{"receita": "CSLL", "pa_exerc": "12/2025", "dt_vcto": "20/01/2026", "vl_original": "500,00", "sdo_dev_cons": "550,00"}],
                "omissions": [{"tipo": "ECF", "detalhe": "Exercício: 2024"}],
                "parc": [{"tipo": "PARCMEI", "atraso": "1"}]
            }
        }
    ]

    os.makedirs("logs", exist_ok=True)

    # Test Debt Report
    PdfGenerator.generate(data, "logs/test_debitos.pdf", title="Teste Débitos", report_type="debts")
    assert os.path.exists("logs/test_debitos.pdf")

    # Test Omission Report
    PdfGenerator.generate(data, "logs/test_omissoes.pdf", title="Teste Omissões", report_type="omissions")
    assert os.path.exists("logs/test_omissoes.pdf")

    # Test Installment Report
    PdfGenerator.generate(data, "logs/test_parcelamentos.pdf", title="Teste Parcelamentos", report_type="parc")
    assert os.path.exists("logs/test_parcelamentos.pdf")

    print("Relatórios de teste gerados com sucesso.")

if __name__ == "__main__":
    test_generate_separate_reports()
