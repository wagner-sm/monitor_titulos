"""
URBS Monitor - Versão Otimizada para GitHub Actions
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


class URBSMonitor:

    URBS_URL = "https://www.urbs.curitiba.pr.gov.br/transporte/boletim-de-transportes"

    def __init__(self, email_recipients, gmail_user, gmail_password):
        self.email_recipients = email_recipients
        self.gmail_user = gmail_user
        self.gmail_password = gmail_password

        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.hash_file = self.data_dir / "urbs_hash.json"
        self.content_file = self.data_dir / "urbs_content.txt"

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
        
        # Estratégia de carregamento - CRÍTICO
        options.page_load_strategy = "none"  # Mudado de 'eager' para 'none'
        
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

        # Timeouts mais agressivos
        self.driver.set_page_load_timeout(30)
        self.driver.set_script_timeout(30)

        logging.info("✅ Driver Selenium criado")

    def get_urbs_content(self) -> str:
        logging.info(f"🌐 Acessando {self.URBS_URL}")

        if not self.driver:
            self.create_selenium_driver()

        # Usar get() sem esperar carregamento completo
        self.driver.get(self.URBS_URL)
        
        # Esperar apenas pelo DOM inicial (mais rápido)
        try:
            WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            logging.info("✅ Body detectado")
        except TimeoutException:
            logging.warning("⚠️ Timeout esperando body, continuando...")
        
        # Dar tempo para JavaScript carregar conteúdo dinâmico
        time.sleep(8)
        
        # Tentar parar o carregamento da página
        try:
            self.driver.execute_script("window.stop();")
            logging.info("🛑 Carregamento parado manualmente")
        except:
            pass
        
        html = self.driver.page_source
        
        # Validar se pegamos conteúdo útil
        if len(html) < 5000:
            raise ValueError(f"HTML muito pequeno: {len(html)} bytes")
        
        logging.info(f"✅ Página carregada ({len(html)} chars)")
        return self.extract_content(html)

    # ------------------------------------------------------------------
    # CONTEÚDO
    # ------------------------------------------------------------------
    def extract_content(self, html: str) -> str:
        if not html:
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # Remover tags desnecessárias
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        titles = []
        for h in soup.find_all(["h1", "h2", "h3"]):
            text = h.get_text(" ", strip=True)
            if len(text) >= 10:
                titles.append(text)

        return "\n".join(sorted(set(titles)))

    def calculate_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def load_last_hash(self) -> str:
        if not self.hash_file.exists():
            return ""
        with open(self.hash_file, "r") as f:
            return json.load(f).get("hash", "")

    def save_hash(self, content_hash: str):
        with open(self.hash_file, "w") as f:
            json.dump(
                {
                    "hash": content_hash,
                    "timestamp": datetime.now(LOCAL_TZ).isoformat(),
                },
                f,
                indent=2,
            )

    def save_content(self, content: str):
        with open(self.content_file, "w", encoding="utf-8") as f:
            f.write(content)

    def detect_change(self, content: str) -> bool:
        if not content or len(content) < 50:  # Reduzido de 100 para 50
            logging.warning(f"⚠️ Conteúdo inválido (tamanho: {len(content)})")
            return False

        new_hash = self.calculate_hash(content)
        old_hash = self.load_last_hash()

        self.save_content(content)

        if not old_hash:
            self.save_hash(new_hash)
            logging.info("🆕 Hash inicial salvo")
            return False

        if new_hash == old_hash:
            logging.info("✅ Nenhuma mudança detectada")
            return False

        logging.info("🔔 MUDANÇA DETECTADA")
        self.save_hash(new_hash)
        return True

    # ------------------------------------------------------------------
    # EMAIL
    # ------------------------------------------------------------------
    def send_email_notification(self):
        logging.info("📧 Enviando email de notificação...")

        msg = MIMEMultipart("alternative")
        msg["From"] = formataddr(
            (str(Header("URBS Monitor", "utf-8")), self.gmail_user)
        )
        msg["To"] = ", ".join(self.email_recipients)
        msg["Subject"] = Header(
            "🚨 Mudança Detectada no Boletim da URBS", "utf-8"
        )

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; background:#f5f5f5;">
          <div style="max-width:600px;margin:auto;background:#ffffff;padding:20px;border-radius:8px">
            <h2 style="color:#1e88e5;">🚨 Mudança Detectada</h2>
            <p>O boletim de transportes da URBS foi atualizado.</p>
            <ul>
              <li><b>Data/Hora:</b> {datetime.now(LOCAL_TZ).strftime('%d/%m/%Y %H:%M:%S')}</li>
              <li><b>URL:</b> <a href="{self.URBS_URL}">{self.URBS_URL}</a></li>
            </ul>
            <p>
              <a href="{self.URBS_URL}"
                 style="display:inline-block;padding:12px 20px;
                        background:#1e88e5;color:#fff;
                        text-decoration:none;border-radius:5px">
                 Acessar boletim
              </a>
            </p>
            <hr>
            <small>URBS Monitor • envio automático</small>
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
        logging.info("🚀 URBS MONITOR - Iniciando")
        logging.info("=" * 60)

        try:
            content = self.get_urbs_content()
            if not content:
                raise RuntimeError("Conteúdo vazio")

            if self.detect_change(content):
                self.send_email_notification()

            logging.info("✅ Monitor concluído")
            return True

        except Exception as e:
            logging.error(f"❌ Erro: {e}", exc_info=True)
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

    monitor = URBSMonitor(
        email_recipients=email_recipients,
        gmail_user=gmail_user,
        gmail_password=gmail_password,
    )

    sys.exit(0 if monitor.run() else 1)


if __name__ == "__main__":
    main()
