import asyncio
import os
import re
from playwright.async_api import async_playwright, Page, BrowserContext
from pydantic import HttpUrl
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from typing import List, Dict, Any, Optional, Tuple

from src.core.config import settings
from src.core.logger import log
from src.core.utils import clear_logs_directory

SESSION_STATE_PATH = "session/veri_state.json"


class VeriScraper:
    def __init__(self):
        self.base_url = str(settings.VERI_BASE_URL)
        self.email = settings.VERI_EMAIL
        self.password = settings.VERI_PASSWORD
        self.headless = settings.HEADLESS
        self.window_width = settings.WINDOW_WIDTH
        self.window_height = settings.WINDOW_HEIGHT
        self.session_path = SESSION_STATE_PATH
        self.blacklisted_terms = ["email", "whatsapp", "celular", "telefone", "enviar", "mensagem", "sms", "contato", "cadastro"]

    def _ensure_session_dir(self):
        session_dir = os.path.dirname(self.session_path)
        if session_dir:
            os.makedirs(session_dir, exist_ok=True)

    async def _login(self, page: Page):
        log.info(f"Navegando para o login em {self.base_url}/login")
        await page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")

        log.info("Inserindo credenciais...")
        # Aguarda o formulário estar visível antes de interagir
        await page.wait_for_selector("input[type='email'], input[name='email'], input[type='text']", state="visible", timeout=15000)
        # Preenche o primeiro input de texto/email encontrado (fallback para SPAs sem type='email')
        await page.locator("input[type='email'], input[name='email'], input[type='text']").first.fill(self.email)
        await page.fill("input[type='password'], input[name='password']", self.password)

        # Se houver hCaptcha, não clicamos automaticamente: o operador precisa marcar
        # "Sou humano" e clicar em Entrar manualmente na janela visível do navegador.
        has_captcha = await page.locator("iframe[src*='hcaptcha'], .h-captcha, #h-captcha").count() > 0
        if has_captcha:
            log.warning("hCaptcha detectado. Marque 'Sou humano' e clique em Entrar manualmente na janela do navegador.")
            log.warning("Aguardando até 5 minutos pela ação manual...")
            redirect_timeout = 300000
        else:
            await page.click("button[type='submit'], button:has-text('Entrar'), button:has-text('Login')")
            redirect_timeout = 15000

        log.info("Aguardando redirecionamento pós-login...")
        try:
            await page.wait_for_url(lambda url: "/login" not in url, timeout=redirect_timeout)
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

        # Persiste a sessão autenticada para reaproveitar nos próximos reinícios de lote,
        # evitando repetir o hCaptcha a cada 50 empresas.
        self._ensure_session_dir()
        await page.context.storage_state(path=self.session_path)
        log.info(f"Sessão salva em {self.session_path} para reaproveitamento.")

    async def _new_context(self, browser):
        """Cria o contexto do navegador, carregando a sessão salva quando disponível."""
        # no_viewport=True: usa o tamanho real da janela (definido em _launch_browser),
        # deixando o Chrome exibir barra de rolagem nativa quando o conteúdo não couber.
        kwargs = {"no_viewport": True, "accept_downloads": True}
        if os.path.exists(self.session_path):
            kwargs["storage_state"] = self.session_path
        return await browser.new_context(**kwargs)

    async def _ensure_authenticated(self, page: Page):
        """Reaproveita a sessão salva se ainda for válida; caso contrário, faz login
        (que pode exigir resolução manual do hCaptcha)."""
        if os.path.exists(self.session_path):
            await page.goto(f"{self.base_url}/ecac/listar_situacao_fiscal_geral", wait_until="domcontentloaded")
            if "/login" not in page.url:
                log.success("Sessão salva reaproveitada — login não foi necessário.")
                return
            log.info("Sessão salva expirou ou é inválida. Login necessário.")

        if self.headless:
            raise Exception(
                "Sessão inválida/expirada e HEADLESS=True: não é possível resolver o hCaptcha sem uma "
                "janela visível. Rode com HEADLESS=False para permitir o login manual."
            )

        await self._login(page)

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

    async def _launch_browser(self, p):
        """Sobe o Chrome e recorre ao Edge caso o Chrome não esteja instalado."""
        # Define o tamanho e a posição da janela para caber na tela.
        # Só tem efeito junto com no_viewport=True no contexto (ver _new_context).
        launch_args = [
            f"--window-size={self.window_width},{self.window_height}",
            "--window-position=0,0",
        ]
        try:
            return await p.chromium.launch(headless=self.headless, channel="chrome", args=launch_args)
        except Exception:
            log.info("Google Chrome não encontrado, tentando Microsoft Edge...")
            return await p.chromium.launch(headless=self.headless, channel="msedge", args=launch_args)

    async def _dismiss_upsell_modal(self, page: Page):
        """Fecha o modal 'Agora não' que às vezes aparece após o login."""
        try:
            agora_nao = page.get_by_role("button", name="Agora não").or_(page.locator("text='Agora não'"))
            await agora_nao.wait_for(state="visible", timeout=5000)
            await agora_nao.click()
        except Exception:
            pass

    async def _goto_list_page(self, page: Page, page_num: int):
        """Navega até a listagem geral e avança até a página onde a sessão parou."""
        log.info(f"Navegando para lista geral (Resumo na pág {page_num})...")
        await page.goto(f"{self.base_url}/ecac/listar_situacao_fiscal_geral", wait_until="domcontentloaded")
        await page.wait_for_selector(".table, table, .row", state="visible", timeout=15000)

        for p_idx in range(1, page_num):
            log.info(f"Avançando para página {p_idx + 1} para retomar...")
            btn_proximo = page.get_by_role("link", name="Próximo").or_(page.locator("text='Próximo'"))
            await btn_proximo.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(1000)

    async def _get_pending_rows(self, page: Page, page_num: int):
        """Retorna as linhas da tabela cujo status possui o badge de pendência."""
        log.info(f"Processando página {page_num}...")
        await page.wait_for_selector("table tr[role='row']", state="visible", timeout=15000)

        rows = await page.locator("tr[role='row']").filter(
            has=page.locator("span.badge-danger")
        ).all()
        log.info(f"Encontradas {len(rows)} empresas com Pendência na página {page_num}")
        return rows

    async def _open_company_details(self, row):
        """Clica em ATUALIZAR (se ativo) ou em VISUALIZAR para abrir/atualizar os dados da empresa."""
        try:
            atualizar_btn = row.get_by_role("button", name="ATUALIZAR").first
            if await atualizar_btn.is_enabled():
                await atualizar_btn.click()
                log.info("Cliquei no botão ATUALIZAR para a empresa.")
            else:
                raise Exception("Botão ATUALIZAR desativado")
        except Exception:
            try:
                visualizar_btn = row.get_by_role("button", name="VISUALIZAR").first
                await visualizar_btn.click()
                log.info("Cliquei no botão VISUALIZAR para a empresa.")
            except Exception as e:
                log.warning(f"Não foi possível clicar nos botões ATUALIZAR ou VISUALIZAR: {e}")

    async def _extract_company_name(self, row) -> str:
        try:
            return (await row.locator("td.sorting_1 div").inner_text()).strip()
        except Exception:
            return "Empresa Desconhecida"

    async def _extract_cnpj(self, row) -> str:
        try:
            tds = await row.locator("td").all()
            if len(tds) >= 2:
                raw = (await tds[1].locator("div").inner_text()).strip()
                # Formata CNPJ: 12345678000100 → 12.345.678/0001-00
                if re.match(r"^\d{14}$", raw):
                    return f"{raw[:2]}.{raw[2:5]}.{raw[5:8]}/{raw[8:12]}-{raw[12:]}"
                return raw
        except Exception:
            pass
        return "Desconhecido"

    async def _extract_pdf_url(self, row) -> Optional[str]:
        try:
            return await row.locator("a[aria-label='Visualizar']").get_attribute("href")
        except Exception:
            return None

    async def _fetch_findings_from_pdf(self, page: Page, pdf_url: str) -> Dict[str, Any]:
        """Baixa o PDF de situação fiscal via request e extrai débitos/omissões/parcelamentos."""
        import io, pdfplumber
        from src.transformers.sief_parser import SiefParser

        try:
            response = await page.context.request.get(pdf_url)
            if response.status != 200:
                log.error(f"Erro HTTP ao baixar PDF: {response.status}")
                return {}

            pdf_bytes = await response.body()
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = "".join([p.extract_text() or "" for p in pdf.pages])

            if not text:
                return {}

            log.info(f"Texto extraído ({len(text)} chars). Analisando pendências...")
            findings = SiefParser.parse_text(text)
            if not findings.get("debts") and not findings.get("omissions") and not findings.get("parc"):
                log.warning(f"SiefParser sem pendências. Primeiros 200 chars: {text[:200]}")
            return findings
        except Exception as e:
            log.error(f"Falha ao processar PDF: {e}")
            return {}

    def _persist_findings(self, cnpj: str, findings: Dict[str, Any]):
        import json
        cnpj_clean = re.sub(r"\D", "", cnpj)
        with open(f"logs/findings_{cnpj_clean}.json", "w") as f:
            json.dump(findings, f)

    async def _process_row(self, page: Page, row, sequence_number: int) -> Optional[Dict[str, Any]]:
        """Processa uma linha de empresa pendente: abre detalhes, extrai identificação e pendências do PDF."""
        await self._open_company_details(row)

        company_name = await self._extract_company_name(row)
        cnpj = await self._extract_cnpj(row)
        log.info(f"[{sequence_number}] Processando: {company_name} ({cnpj})")

        pdf_url = await self._extract_pdf_url(row)
        if not pdf_url or not pdf_url.strip():
            log.warning(f"Nenhuma URL de PDF encontrada para {company_name}")
            return None

        pdf_url = pdf_url.strip()
        log.info(f"PDF encontrado: {pdf_url}")
        findings = await self._fetch_findings_from_pdf(page, pdf_url)
        if not findings:
            return None

        findings["company_name"] = company_name
        self._persist_findings(cnpj, findings)
        return {"cnpj": cnpj, "company_name": company_name, "findings": findings}

    async def _process_page_rows(
        self, page: Page, page_num: int, processed_total: int, all_findings: List[Dict[str, Any]], batch_limit: int
    ) -> Tuple[int, bool]:
        """Processa todas as empresas pendentes da página atual. Retorna (processed_total, should_restart)."""
        rows = await self._get_pending_rows(page, page_num)
        session_processed_count = 0

        for row in rows:
            entry = await self._process_row(page, row, processed_total + 1)
            if entry:
                all_findings.append(entry)

            processed_total += 1
            session_processed_count += 1

            if session_processed_count >= batch_limit:
                log.warning(f"Lote de {batch_limit} atingido. Reiniciando sessão...")
                return processed_total, True

        return processed_total, False

    async def _advance_to_next_page(self, page: Page) -> bool:
        """Clica em 'Próximo'. Retorna True se avançou, False se não há mais páginas."""
        try:
            btn_proximo = page.get_by_role("link", name="Próximo").or_(page.locator("text='Próximo'"))
            if await btn_proximo.count() > 0 and await btn_proximo.is_visible() and not await btn_proximo.get_attribute("disabled"):
                await btn_proximo.click(timeout=10000)
                await page.wait_for_load_state("domcontentloaded")
                await page.wait_for_selector(".table, table, .row", state="visible", timeout=15000)
                return True
            return False
        except Exception:
            return False

    async def _run_session(
        self, page: Page, page_num: int, processed_total: int, all_findings: List[Dict[str, Any]], batch_limit: int
    ) -> Tuple[int, int, bool]:
        """Percorre as páginas da listagem a partir de page_num até esgotá-las ou atingir o batch_limit.
        Retorna (page_num, processed_total, should_restart)."""
        await self._dismiss_upsell_modal(page)
        await self._goto_list_page(page, page_num)

        while True:
            processed_total, should_restart = await self._process_page_rows(page, page_num, processed_total, all_findings, batch_limit)
            if should_restart:
                return page_num, processed_total, True

            if await self._advance_to_next_page(page):
                page_num += 1
            else:
                return page_num, processed_total, False

    def _generate_reports(self, all_findings: List[Dict[str, Any]]):
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

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def extract_pendencias(self) -> List[Dict[str, Any]]:
        # Limpa o diretório de saída antes de começar a consulta
        clear_logs_directory()

        all_findings = []
        page_num = 1
        processed_total = 0
        batch_limit = 50

        while True:
            log.info(f"--- INICIANDO SESSÃO (Batch {processed_total // batch_limit + 1}, Página {page_num}) ---")
            async with async_playwright() as p:
                browser = await self._launch_browser(p)
                context = await self._new_context(browser)
                page = await context.new_page()

                try:
                    await self._ensure_authenticated(page)
                    page_num, processed_total, should_restart = await self._run_session(
                        page, page_num, processed_total, all_findings, batch_limit
                    )
                    if not should_restart:
                        break
                except Exception as e:
                    log.error(f"Erro Crítico na sessão: {e}")
                    await page.screenshot(path="logs/session_error.png")
                    break
                finally:
                    await browser.close()

        if all_findings:
            self._generate_reports(all_findings)

        return all_findings


if __name__ == "__main__":
    scraper = VeriScraper()
    asyncio.run(scraper.extract_pendencias())
