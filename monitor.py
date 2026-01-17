"""
Multi-Site Monitor - Versão Otimizada para GitHub Actions
Monitora múltiplos sites e envia notificações por email quando detecta mudanças
"""

import os
import sys
import json
import logging
import hashlib
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import List, Dict, Optional

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

from bs4 import BeautifulSoup

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr


class MultiSiteMonitor:
    """Monitor para múltiplos sites"""
    
    # URLs dos sites - ADICIONE SEUS SITES AQUI
    SITES = [
        "https://www.urbs.curitiba.pr.gov.br/transporte/boletim-de-transportes",
        "https://www.eueanatureza.com.br/ensaios_modelos",
        "https://www.rektmag.net/" 
    ]

    def __init__(self, email_recipients, gmail_user, gmail_password):
        self.email_recipients = email_recipients
        self.gmail_user = gmail_user
        self.gmail_password = gmail_password

        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        
        # Arquivos únicos para todos os sites
        self.hash_file = self.data_dir / "hash.json"
        self.content_file = self.data_dir / "content.txt"
        
        self.driver = None
        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    # ------------------------------------------------------------------
    # SELENIUM - CONFIGURAÇÃO OTIMIZADA
    # ------------------------------------------------------------------
    def create_selenium_driver(self):
        logging.info("🚀 Criando driver Selenium...")

        options = Options()
        
        # Configurações essenciais para CI
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-breakpad")
        options.add_argument("--disable-component-extensions-with-background-pages")
        options.add_argument("--disable-features=TranslateUI,BlinkGenPropertyTrees")
        options.add_argument("--disable-ipc-flooding-protection")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
        options.add_argument("--force-color-profile=srgb")
        options.add_argument("--hide-scrollbars")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--mute-audio")
        options.add_argument("--window-size=1280,720")
        
        # Estratégia de carregamento
        options.page_load_strategy = "none"
        
        # Desabilitar recursos pesados
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
            "profile.managed_default_content_settings.stylesheets": 2,
            "profile.managed_default_content_settings.cookies": 2,
            "profile.managed_default_content_settings.javascript": 1,
            "profile.managed_default_content_settings.plugins": 2,
            "profile.managed_default_content_settings.popups": 2,
            "profile.managed_default_content_settings.geolocation": 2,
            "profile.managed_default_content_settings.media_stream": 2,
        }
        options.add_experimental_option("prefs", prefs)
        
        # User agent
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)

        # Timeouts
        self.driver.set_page_load_timeout(30)
        self.driver.set_script_timeout(30)

        logging.info("✅ Driver Selenium criado")

    def get_site_name(self, url: str) -> str:
        """Extrai um nome simples da URL"""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        # Remove www. e pega o nome principal
        name = domain.replace("www.", "").split(".")[0]
        return name.upper()

    def get_site_content(self, url: str) -> str:
        """Obtém o conteúdo de um site específico"""
        site_name = self.get_site_name(url)
        logging.info(f"🌐 Acessando {site_name}: {url}")

        if not self.driver:
            self.create_selenium_driver()

        self.driver.get(url)
        
        # Esperar pelo body
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            logging.info(f"✅ {site_name} - Body detectado")
        except TimeoutException:
            logging.warning(f"⚠️ {site_name} - Timeout esperando body")
        
        # Tempo para JavaScript
        time.sleep(8)
        
        # Parar carregamento
        try:
            self.driver.execute_script("window.stop();")
        except:
            pass
        
        html = self.driver.page_source
        
        if len(html) < 5000:
            raise ValueError(f"{site_name}: HTML muito pequeno ({len(html)} bytes)")
        
        logging.info(f"✅ {site_name} - Página carregada ({len(html)} chars)")
        return self.extract_content(html)

    # ------------------------------------------------------------------
    # EXTRAÇÃO DE CONTEÚDO
    # ------------------------------------------------------------------
    def extract_content(self, html: str) -> str:
        """Extrai títulos (h1, h2, h3) do HTML"""
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # Remover tags desnecessárias
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Extrair títulos
        titles = []
        for h in soup.find_all(["h1", "h2", "h3"]):
            text = h.get_text(" ", strip=True)
            if len(text) >= 10:
                titles.append(text)
        
        return "\n".join(sorted(set(titles)))

    # ------------------------------------------------------------------
    # HASH E DETECÇÃO DE MUDANÇAS - ARQUIVOS ÚNICOS
    # ------------------------------------------------------------------
    def calculate_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def load_all_hashes(self) -> Dict[str, Dict]:
        """Carrega todos os hashes do arquivo hash.json"""
        if not self.hash_file.exists():
            return {}
        
        try:
            with open(self.hash_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Erro ao carregar hashes: {e}")
            return {}

    def save_all_hashes(self, hashes: Dict[str, Dict]):
        """Salva todos os hashes no arquivo hash.json"""
        with open(self.hash_file, "w", encoding="utf-8") as f:
            json.dump(hashes, f, indent=2, ensure_ascii=False)

    def load_all_contents(self) -> Dict[str, str]:
        """Carrega todos os conteúdos do arquivo content.txt"""
        if not self.content_file.exists():
            return {}
        
        try:
            contents = {}
            with open(self.content_file, "r", encoding="utf-8") as f:
                current_url = None
                current_content = []
                
                for line in f:
                    if line.startswith("=== URL: "):
                        # Salvar conteúdo anterior
                        if current_url:
                            contents[current_url] = "\n".join(current_content).strip()
                        
                        # Nova URL
                        current_url = line.replace("=== URL: ", "").strip()
                        current_content = []
                    elif line.startswith("=== END ==="):
                        if current_url:
                            contents[current_url] = "\n".join(current_content).strip()
                            current_url = None
                            current_content = []
                    else:
                        current_content.append(line.rstrip())
                
                # Último conteúdo
                if current_url:
                    contents[current_url] = "\n".join(current_content).strip()
            
            return contents
        except Exception as e:
            logging.warning(f"Erro ao carregar conteúdos: {e}")
            return {}

    def save_all_contents(self, contents: Dict[str, str]):
        """Salva todos os conteúdos no arquivo content.txt"""
        with open(self.content_file, "w", encoding="utf-8") as f:
            for url, content in contents.items():
                f.write(f"=== URL: {url}\n")
                f.write(content)
                f.write("\n=== END ===\n\n")

    def detect_change(self, url: str, content: str) -> bool:
        """Detecta se houve mudança no conteúdo de um site"""
        site_name = self.get_site_name(url)
        
        if not content or len(content) < 50:
            logging.warning(f"⚠️ {site_name} - Conteúdo inválido ({len(content)} chars)")
            return False

        # Carregar dados existentes
        all_hashes = self.load_all_hashes()
        all_contents = self.load_all_contents()

        # Calcular novo hash
        new_hash = self.calculate_hash(content)
        old_hash = all_hashes.get(url, {}).get("hash", "")

        # Atualizar conteúdo
        all_contents[url] = content
        self.save_all_contents(all_contents)

        # Atualizar hash
        all_hashes[url] = {
            "hash": new_hash,
            "timestamp": datetime.now(LOCAL_TZ).isoformat(),
        }
        self.save_all_hashes(all_hashes)

        if not old_hash:
            logging.info(f"🆕 {site_name} - Hash inicial salvo")
            return False

        if new_hash == old_hash:
            logging.info(f"✅ {site_name} - Nenhuma mudança detectada")
            return False

        logging.info(f"🔔 {site_name} - MUDANÇA DETECTADA")
        return True

    # ------------------------------------------------------------------
    # EMAIL
    # ------------------------------------------------------------------
    def send_email_notification(self, changed_urls: List[str]):
        """Envia email com notificação de mudanças"""
        logging.info(f"📧 Enviando email para {len(changed_urls)} site(s) alterado(s)")

        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr(
            (str(Header("Multi-Site Monitor", "utf-8")), self.gmail_user)
        )
        msg["To"] = ", ".join(self.email_recipients)
        
        # Título do email
        if len(changed_urls) == 1:
            site_name = self.get_site_name(changed_urls[0])
            subject = f"🚨 Mudança Detectada - {site_name}"
        else:
            subject = f"🚨 {len(changed_urls)} Sites Atualizados"
        
        msg["Subject"] = Header(subject, "utf-8")

        # Corpo do email
        sites_html = ""
        for url in changed_urls:
            site_name = self.get_site_name(url)
            sites_html += f"""
            <div style="margin:15px 0; padding:15px; background:#f9f9f9; border-left:4px solid #1e88e5">
                <h3 style="margin:0 0 10px 0; color:#1e88e5">{site_name}</h3>
                <p style="margin:5px 0">
                    <a href="{url}" style="color:#1e88e5">{url}</a>
                </p>
            </div>
            """

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background:#f5f5f5;">
          <div style="max-width:600px;margin:auto;background:#ffffff;padding:20px;border-radius:8px">
            <h2 style="color:#1e88e5;">🚨 Mudanças Detectadas</h2>
            <p>Os seguintes sites foram atualizados:</p>
            
            {sites_html}
            
            <ul style="margin-top:20px">
              <li><b>Data/Hora:</b> {datetime.now(LOCAL_TZ).strftime('%d/%m/%Y %H:%M:%S')}</li>
              <li><b>Sites monitorados:</b> {len(self.SITES)}</li>
              <li><b>Sites alterados:</b> {len(changed_urls)}</li>
            </ul>
            
            <hr style="margin:20px 0">
            <small style="color:#666">Multi-Site Monitor • Envio automático</small>
          </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(self.gmail_user, self.gmail_password)
            server.sendmail(
                self.gmail_user,
                self.email_recipients,
                msg.as_string(),
            )

        logging.info("✅ Email enviado com sucesso")

    # ------------------------------------------------------------------
    # RUN
    # ------------------------------------------------------------------
    def run(self):
        logging.info("=" * 60)
        logging.info(f"🚀 MULTI-SITE MONITOR - Monitorando {len(self.SITES)} site(s)")
        logging.info("=" * 60)

        changed_urls = []
        errors = []

        try:
            for url in self.SITES:
                site_name = self.get_site_name(url)
                try:
                    logging.info(f"\n🔍 Verificando: {site_name}")
                    
                    content = self.get_site_content(url)
                    
                    if self.detect_change(url, content):
                        changed_urls.append(url)
                    
                    # Pausa entre sites
                    time.sleep(2)
                    
                except Exception as e:
                    error_msg = f"{site_name}: {str(e)}"
                    logging.error(f"❌ Erro em {error_msg}")
                    errors.append(error_msg)

            # Enviar email se houver mudanças
            if changed_urls:
                self.send_email_notification(changed_urls)
                logging.info(f"\n✅ Monitor concluído - {len(changed_urls)} mudança(s) detectada(s)")
            else:
                logging.info("\n✅ Monitor concluído - Nenhuma mudança detectada")

            # Reportar erros
            if errors:
                logging.warning(f"\n⚠️ {len(errors)} erro(s) encontrado(s):")
                for error in errors:
                    logging.warning(f"  - {error}")

            return True

        except Exception as e:
            logging.error(f"❌ Erro crítico: {e}", exc_info=True)
            return False

        finally:
            if self.driver:
                try:
                    self.driver.quit()
                    logging.info("🔒 Driver Selenium fechado")
                except:
                    pass


def main():
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    email_recipients = os.getenv("EMAIL_RECIPIENTS", "").split(",")

    if not gmail_user or not gmail_password or not email_recipients:
        print("❌ Variáveis de ambiente não configuradas")
        sys.exit(1)

    monitor = MultiSiteMonitor(
        email_recipients=email_recipients,
        gmail_user=gmail_user,
        gmail_password=gmail_password,
    )

    sys.exit(0 if monitor.run() else 1)


if __name__ == "__main__":
    main()
