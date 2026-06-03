import asyncio
import re
from playwright.async_api import async_playwright, Page, BrowserContext
from pydantic import HttpUrl
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import List, Dict, Any

from src.core.config import settings
from src.core.logger import log
from src.core.utils import clear_logs_directory


class VeriScraper:
    def __init__(self):
        self.base_url = str(settings.VERI_BASE_URL)
        self.email = settings.VERI_EMAIL
        self.password = settings.VERI_PASSWORD
        self.headless = settings.HEADLESS
        self.blacklisted_terms = ["email", "whatsapp", "celular", "telefone", "enviar", "mensagem", "sms", "contato", "cadastro"]
        
    async def _login(self, page: Page):
        log.info(f"Navegando para o login em {self.base_url}/login")
        await page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")
        
        log.info("Inserindo credenciais...")
        # Aguarda o formulário estar visível antes de interagir
        await page.wait_for_selector("input[type='email'], input[name='email'], input[type='text']", state="visible", timeout=15000)
        # Preenche o primeiro input de texto/email encontrado (fallback para SPAs sem type='email')
        await page.locator("input[type='email'], input[name='email'], input[type='text']").first.fill(self.email)
        await page.fill("input[type='password'], input[name='password']", self.password)
        
        # Tenta clicar no botão de submit ou login
        await page.click("button[type='submit'], button:has-text('Entrar'), button:has-text('Login')")
        
        log.info("Aguardando redirecionamento pós-login...")
        try:
            await page.wait_for_url(lambda url: "/login" not in url, timeout=15000)
            await page.wait_for_load_state("domcontentloaded")
        except Exception:
            # Captura texto da página para diagnóstico (credenciais erradas, CAPTCHA, etc.)
            body_text = await page.inner_text("body")
            raise Exception(f"Login não redirecionou. Texto da página: {body_text[:300]}")
        
        # Verifica se há mensagem de erro visível (senha incorreta, usuário inválido, etc.)
        error_locator = page.locator("text='inválid', text='incorret', text='Senha', text='erro'")
        if await error_locator.count() > 0:
            error_text = await error_locator.first.inner_text()
            raise Exception(f"Login falhou com mensagem de erro: '{error_text}'")
        
        log.success("Logado com sucesso.")

    async def _handle_report_tab(self, page: Page, report_btn) -> List[Dict[str, Any]]:
        """Clica no botão do relatório, captura download ou nova aba e extrai débitos."""
        try:
            log.info("Iniciando captura de relatório...")
            
            # Segurança extra: Verifica atributos antes de clicar
            attrs = await report_btn.evaluate("el => ({onclick: el.getAttribute('onclick'), href: el.getAttribute('href'), text: el.innerText, download: el.hasAttribute('download')})")
            log.debug(f"Verificando botão antes do clique: {attrs}")
            for term in self.blacklisted_terms:
                if term in (attrs['onclick'] or "").lower() or term in (attrs['href'] or "").lower() or term in (attrs['text'] or "").lower():
                    log.error(f"ABORTANDO CLIQUE: Botão contém termo proibido '{term}'")
                    return []

            await report_btn.scroll_into_view_if_needed()
            
            text = ""
            # Se o botão tem atributo download ou href de PDF, preferimos download
            is_pdf = ".pdf" in (attrs['href'] or "").lower() or attrs['download']
            
            if is_pdf:
                log.info("Detectado link de PDF. Tentando download direto...")
                try:
                    async with page.expect_download(timeout=15000) as download_info:
                        await report_btn.click(force=True)
                    download = await download_info.value
                    temp_path = f"logs/temp_{download.suggested_filename}"
                    await download.save_as(temp_path)
                    log.info(f"PDF baixado: {temp_path}")
                    
                    import pdfplumber
                    with pdfplumber.open(temp_path) as pdf:
                        text = "".join([p.extract_text() or "" for p in pdf.pages])
                except Exception as e:
                    log.warning(f"Falha no download direto, tentando via aba: {e}")
            
            # Se ainda não tem texto, tenta via nova aba
            if not text:
                try:
                    async with page.context.expect_page(timeout=8000) as page_info:
                        await report_btn.click(force=True)
                    new_page = await page_info.value
                    await new_page.wait_for_load_state("load")
                    
                    if ".pdf" in new_page.url.lower():
                        # Se abriu PDF em aba, inner_text falha. Vamos tentar baixar a URL
                        log.info(f"Relatório PDF em aba: {new_page.url}. Baixando via request...")
                        try:
                            response = await page.context.request.get(new_page.url)
                            if response.status == 200:
                                pdf_bytes = await response.body()
                                import io, pdfplumber
                                with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                                    text = "".join([p.extract_text() or "" for p in pdf.pages])
                            else:
                                log.error(f"Erro ao baixar PDF via request: {response.status}")
                        except Exception as req_err:
                            log.error(f"Exceção no request: {req_err}")
                    else:
                        text = await new_page.evaluate("() => document.body.innerText")
                    await new_page.close()
                except Exception as e:
                    log.error(f"Falha ao capturar via aba: {e}")

            if text:
                log.info(f"Texto extraído ({len(text)} chars). Analisando débitos e omissões...")
                from src.transformers.sief_parser import SiefParser
                findings = SiefParser.parse_text(text)
                if not findings.get("debts") and not findings.get("omissions") and not findings.get("parc"):
                    log.warning(f"SiefParser não encontrou pendências no texto. Primeiros 200 chars: {text[:200]}")
                return findings
            
            return {}
        except Exception as e:
            log.error(f"Falha fatal ao processar relatório: {e}")
            return []

    @retry(stop=stop_after_attempt(1), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def extract_pendencias(self) -> List[Dict[str, Any]]:
        # Limpa o diretório de saída antes de começar a consulta
        clear_logs_directory()
        
        all_findings = []
        page_num = 1
        processed_total = 0
        batch_limit = 50
        
        while True:
            log.info(f"--- INICIANDO SESSÃO (Batch {processed_total // batch_limit + 1}, Página {page_num}) ---")
clear_logs_directory()
            async with async_playwright() as p:
                try:
                    browser = await p.chromium.launch(headless=self.headless, channel="chrome")
                except Exception:
                    log.info("Google Chrome não encontrado, tentando Microsoft Edge...")
                    browser = await p.chromium.launch(headless=self.headless, channel="msedge")

                context = await browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                    accept_downloads=True
                )
                page = await context.new_page()
                session_processed_count = 0
                should_restart = False

                try:
                    await self._login(page)
                    
                    # Trata o modal "Agora não"
                    try:
                        agora_nao = page.get_by_role("button", name="Agora não").or_(page.locator("text='Agora não'"))
                        await agora_nao.wait_for(state="visible", timeout=5000)
                        await agora_nao.click()
                    except Exception:
                        pass

                    log.info(f"Navegando para lista geral (Resumo na pág {page_num})...")
                    await page.goto(f"{self.base_url}/ecac/listar_situacao_fiscal_geral", wait_until="domcontentloaded")
                    await page.wait_for_selector(".table, table, .row", state="visible", timeout=15000)
                    
                    # Avança até a página correta caso tenha reiniciado
                    for p_idx in range(1, page_num):
                        log.info(f"Avançando para página {p_idx + 1} para retomar...")
                        btn_proximo = page.get_by_role("link", name="Próximo").or_(page.locator("text='Próximo'"))
                        await btn_proximo.click()
                        await page.wait_for_load_state("domcontentloaded")
                        await page.wait_for_timeout(1000)

                    while True:
                        log.info(f"Processando página {page_num}...")
                        await page.wait_for_selector("table tr[role='row']", state="visible", timeout=15000)

                        # Seleciona apenas linhas que têm badge-danger (Pendência)
                        rows = await page.locator("tr[role='row']").filter(
                            has=page.locator("span.badge-danger")
                        ).all()
                        log.info(f"Encontradas {len(rows)} empresas com Pendência na página {page_num}")

                        # Antes de processar cada empresa, tenta atualizar ou visualizar
        try:
            # Botão ATUALIZAR ativo
            atualizar_btn = row.get_by_role("button", name="ATUALIZAR").first
            if await atualizar_btn.is_enabled():
                await atualizar_btn.click()
                log.info("Cliquei no botão ATUALIZAR para a empresa.")
            else:
                raise Exception("Botão ATUALIZAR desativado")
        except Exception:
            # Fallback: botão VISUALIZAR na coluna Ações
            try:
                visualizar_btn = row.get_by_role("button", name="VISUALIZAR").first
                await visualizar_btn.click()
                log.info("Cliquei no botão VISUALIZAR para a empresa.")
            except Exception as e:
                log.warning(f"Não foi possível clicar nos botões ATUALIZAR ou VISUALIZAR: {e}")
        
                            # Extrai Razão Social da primeira célula com classe sorting_1
                            company_name = "Empresa Desconhecida"
                            try:
                                company_name = (await row.locator("td.sorting_1 div").inner_text()).strip()
                            except Exception:
                                pass

                            # Extrai CNPJ — segunda célula (td sem classe sorting_1)
                            cnpj = "Desconhecido"
                            try:
                                tds = await row.locator("td").all()
                                if len(tds) >= 2:
                                    raw = (await tds[1].locator("div").inner_text()).strip()
                                    # Formata CNPJ: 12345678000100 → 12.345.678/0001-00
                                    if re.match(r"^\d{14}$", raw):
                                        cnpj = f"{raw[:2]}.{raw[2:5]}.{raw[5:8]}/{raw[8:12]}-{raw[12:]}"
                                    else:
                                        cnpj = raw
                            except Exception:
                                pass

                            log.info(f"[{processed_total + 1}] Processando: {company_name} ({cnpj})")

                            # Extrai URL do PDF direto do href do botão Visualizar — sem clicar
                            pdf_url = None
                            try:
                                pdf_url = await row.locator("a[aria-label='Visualizar']").get_attribute("href")
                            except Exception:
                                pass

                            findings = {}
                            if pdf_url and pdf_url.strip():
                                pdf_url = pdf_url.strip()
                                log.info(f"PDF encontrado: {pdf_url}")
                                try:
                                    import io, pdfplumber
                                    response = await page.context.request.get(pdf_url)
                                    if response.status == 200:
                                        pdf_bytes = await response.body()
                                        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                                            text = "".join([p.extract_text() or "" for p in pdf.pages])
                                        if text:
                                            log.info(f"Texto extraído ({len(text)} chars). Analisando pendências...")
                                            from src.transformers.sief_parser import SiefParser
                                            findings = SiefParser.parse_text(text)
                                            if not findings.get("debts") and not findings.get("omissions") and not findings.get("parc"):
                                                log.warning(f"SiefParser sem pendências. Primeiros 200 chars: {text[:200]}")
                                    else:
                                        log.error(f"Erro HTTP ao baixar PDF: {response.status}")
                                except Exception as e:
                                    log.error(f"Falha ao processar PDF: {e}")
                            else:
                                log.warning(f"Nenhuma URL de PDF encontrada para {company_name}")
                            
                            if findings:
                                findings["company_name"] = company_name
                                all_findings.append({"cnpj": cnpj, "company_name": company_name, "findings": findings})
                                cnpj_clean = re.sub(r"\D", "", cnpj)
                                with open(f"logs/findings_{cnpj_clean}.json", "w") as f:
                                    import json
                                    json.dump(findings, f)
                                
                            processed_total += 1
                            session_processed_count += 1
                            
                            if session_processed_count >= batch_limit:
                                log.warning(f"Lote de {batch_limit} atingido. Reiniciando sessão...")
                                should_restart = True
                                break
                        
                        if should_restart:
                            break

                        # Próxima Página
                        try:
                            btn_proximo = page.get_by_role("link", name="Próximo").or_(page.locator("text='Próximo'"))
                            if await btn_proximo.count() > 0 and await btn_proximo.is_visible() and not await btn_proximo.get_attribute("disabled"):
                                await btn_proximo.click(timeout=10000)
                                await page.wait_for_load_state("domcontentloaded")
                                await page.wait_for_selector(".table, table, .row", state="visible", timeout=15000)
                                page_num += 1
                            else:
                                break
                        except Exception:
                            break
                    
                    if not should_restart:
                        break

                except Exception as e:
                    log.error(f"Erro Crítico na sessão: {e}")
                    await page.screenshot(path="logs/session_error.png")
                    break
                finally:
                    await browser.close()

        if all_findings:
            try:
                from src.transformers.pdf_generator import PdfGenerator
                
                # 1. Relatório de Débitos
                PdfGenerator.generate(
                    all_findings, 
                    "logs/relatorio_debitos.pdf", 
                    title="Relatório de Débitos Fiscais", 
                    report_type="debts"
                )
                
                # 2. Relatório de Omissões
                PdfGenerator.generate(
                    all_findings, 
                    "logs/relatorio_omissoes.pdf", 
                    title="Relatório de Omissões de Declarações", 
                    report_type="omissions"
                )
                
                # 3. Relatório de Parcelamentos
                PdfGenerator.generate(
                    all_findings, 
                    "logs/relatorio_parcelamentos.pdf", 
                    title="Relatório de Pendências de Parcelamento", 
                    report_type="parc"
                )
                
                log.success("Relatórios separados gerados com sucesso na pasta logs/.")
            except Exception as e:
                log.error(f"Erro ao gerar PDFs finais: {e}")
        
        return all_findings


if __name__ == "__main__":
    scraper = VeriScraper()
    asyncio.run(scraper.extract_pendencias())
