import re
import pdfplumber
from typing import List, Dict, Any
from src.core.logger import log

class SiefParser:
    """Extrai débitos e pendências (SIEF) de relatórios em PDF."""
    
    DEBT_ROW_PATTERN = re.compile(
        r"^(?P<receita>.*?)\s+"
        r"(?P<pa_exerc>\d{2}/\d{4})\s+"
        r"(?P<dt_vcto>\d{2}/\d{2}/\d{4})\s+"
        r"(?P<vl_original>[\d.,]+)\s+"
        r"(?P<sdo_devedor>[\d.,]+)\s+"
        r"(?P<multa>[\d.,]+)\s+"
        r"(?P<juros>[\d.,]+)\s+"
        r"(?P<sdo_dev_cons>[\d.,]+)\s+"
        r"(?P<situacao>DEVEDOR)$",
        re.MULTILINE
    )

    # Omissão de DITR
    DITR_PATTERN = re.compile(r"Omissão de DITR.*?CIB:\s*(?P<cib>[\d.-]+)\s*-\s*(?P<exercicio>[\d\s]+)", re.DOTALL)
    
    # Omissão de DIRF
    DIRF_PATTERN = re.compile(r"Omissão de DIRF.*?(Ano de Retenção)\s*(?P<ano>\d{4})", re.DOTALL)

    # Omissão DCTFWEB / ECF / ECD / DEFIS
    OMISSION_GENERIC_PATTERN = re.compile(r"Omissão de (?P<tipo>DCTFWEB|ECF|ECD|DEFIS).*?Período:\s*(?P<periodo>[\d/.\s-]+)", re.DOTALL)

    # Parcelamentos
    PARC_PATTERN = re.compile(r"Pendência - Parcelamento \(PARCSN/PARCMEI\).*?Parcelas em atraso\s*(?P<parcelas>\d+)", re.DOTALL)

    @classmethod
    def parse_pdf(cls, file_path: str) -> List[Dict[str, Any]]:
        """Abre o PDF e extrai todos os débitos da seção SIEF."""
        debts = []
        log.info(f"Analisando PDF: {file_path}")
        
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""
                
                # Para evitar pegar coisas fora do SIEF, 
                # pode-se isolar text.split("Pendência - Débito (SIEF)") se necessário.
                
                for match in cls.DEBT_ROW_PATTERN.finditer(text):
                    debt = match.groupdict()
                    # Clean/strip
                    debt["receita"] = debt["receita"].strip()
                    debts.append(debt)
                    
        log.info(f"Extraídos {len(debts)} débitos do arquivo SIEF.")
        return debts

    @classmethod
    def parse_text(cls, text: str) -> Dict[str, Any]:
        """Extrai débitos e omissões do texto."""
        results = {
            "debts": [],
            "omissions": [],
            "parc": []
        }

        # Débitos SIEF
        for match in cls.DEBT_ROW_PATTERN.finditer(text):
            debt = match.groupdict()
            debt["receita"] = debt["receita"].strip()
            results["debts"].append(debt)

        # Omissão DITR
        for match in cls.DITR_PATTERN.finditer(text):
            results["omissions"].append({
                "tipo": "DITR",
                "detalhe": f"CIB: {match.group('cib').strip()} - {match.group('exercicio').strip()}"
            })

        # Omissão DIRF
        for match in cls.DIRF_PATTERN.finditer(text):
            results["omissions"].append({
                "tipo": "DIRF",
                "detalhe": f"Ano: {match.group('ano')}"
            })

        # Omissões Genéricas (DCTFWEB, ECF, ECD)
        for match in cls.OMISSION_GENERIC_PATTERN.finditer(text):
            results["omissions"].append({
                "tipo": match.group("tipo"),
                "detalhe": f"Período: {match.group('periodo').strip()}"
            })

        # Parcelamentos
        for match in cls.PARC_PATTERN.finditer(text):
            results["parc"].append({
                "tipo": "PARCSN/PARCMEI",
                "atraso": match.group("parcelas")
            })

        return results
