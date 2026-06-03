from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from typing import List, Dict, Any
import os

class PdfGenerator:
    """Gera relatório PDF consolidado das pendências fiscais."""

    @staticmethod
    def generate(data: List[Dict[str, Any]], output_path: str, title: str = "Relatório de Pendências Fiscais", report_type: str = "all"):
        doc = SimpleDocTemplate(output_path, pagesize=A4)
        styles = getSampleStyleSheet()
        
        # Estilos customizados
        title_style = ParagraphStyle(
            'TitleStyle',
            parent=styles['Heading1'],
            fontSize=18,
            spaceAfter=20,
            alignment=1  # Center
        )
        
        company_style = ParagraphStyle(
            'CompanyStyle',
            parent=styles['Heading2'],
            fontSize=14,
            spaceBefore=15,
            spaceAfter=10,
            color=colors.navy
        )

        elements = []
        
        # Título
        elements.append(Paragraph(title, title_style))
        elements.append(Spacer(1, 12))

        has_content = False
        for entry in data:
            findings = entry.get("findings", {})
            debts = findings.get("debts", [])
            omissions = findings.get("omissions", [])
            parcs = findings.get("parc", [])

            # Filtra baseado no tipo de relatório
            show_debts = (report_type in ["all", "debts"]) and debts
            show_omissions = (report_type in ["all", "omissions"]) and omissions
            show_parcs = (report_type in ["all", "parc"]) and parcs

            if not (show_debts or show_omissions or show_parcs):
                continue

            has_content = True
            cnpj = entry.get("cnpj", "Desconhecido")
            name = entry.get("company_name") or findings.get("company_name", "Empresa Desconhecida")
            
            elements.append(Paragraph(f"Empresa: {name} ({cnpj})", company_style))
            
            # 1. Débitos SIEF
            if show_debts:
                elements.append(Paragraph("Débitos (SIEF):", styles['Heading3']))
                table_data = [["Receita", "PA", "Vencimento", "Valor", "Total"]]
                for d in debts:
                    table_data.append([
                        d.get("receita", "")[:20],
                        d.get("pa_exerc", ""),
                        d.get("dt_vcto", ""),
                        d.get("vl_original", ""),
                        d.get("sdo_dev_cons", "")
                    ])
                
                t = Table(table_data, colWidths=[150, 60, 80, 80, 80])
                t.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black)
                ]))
                elements.append(t)
                elements.append(Spacer(1, 10))

            # 2. Omissões
            if show_omissions:
                elements.append(Paragraph("Omissões de Declarações:", styles['Heading3']))
                for om in omissions:
                    elements.append(Paragraph(f"• <b>{om['tipo']}</b>: {om['detalhe']}", styles['Normal']))
                elements.append(Spacer(1, 10))

            # 3. Parcelamentos
            if show_parcs:
                elements.append(Paragraph("Parcelamentos em Atraso:", styles['Heading3']))
                for p in parcs:
                    elements.append(Paragraph(f"• {p['tipo']}: {p['atraso']} parcelas em atraso", styles['Normal']))
                elements.append(Spacer(1, 10))

            elements.append(Spacer(1, 20))

        if not has_content:
            elements.append(Paragraph("Nenhuma pendência encontrada para este relatório.", styles['Italic']))

        doc.build(elements)
        return output_path
