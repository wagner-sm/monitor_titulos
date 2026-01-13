"""
URBS Monitor - Versão Simplificada e Específica
Monitor focado no site da URBS Curitiba com Selenium
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

# Imports Selenium
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
    SELENIUM_AVAILABLE = True
except ImportError:
    print("❌ ERRO: Selenium não instalado!")
    print("Execute: pip install selenium")
    sys.exit(1)

# Webdriver Manager (opcional - baixa Chrome automaticamente)
try:
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    WEBDRIVER_MANAGER_AVAILABLE = True
except ImportError:
    WEBDRIVER_MANAGER_AVAILABLE = False
    # Não é fatal, apenas uma opção

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    print("❌ ERRO: BeautifulSoup não instalado!")
    print("Execute: pip install beautifulsoup4")
    sys.exit(1)

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr


class URBSMonitor:
    """Monitor específico para o site da URBS"""
    
    # URL fixa do boletim
    URBS_URL = "https://www.urbs.curitiba.pr.gov.br/transporte/boletim-de-transportes"
    
    def __init__(self, email_recipients: list, gmail_user: str, gmail_password: str):
        """
        Inicializa o monitor
        
        Args:
            email_recipients: Lista de emails para notificação
            gmail_user: Email Gmail para enviar
            gmail_password: Senha de app do Gmail
        """
        self.email_recipients = email_recipients
        self.gmail_user = gmail_user
        self.gmail_password = gmail_password
        
        # Arquivos de dados (organizados em pasta)
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        self.hash_file = self.data_dir / "urbs_hash.json"
        self.content_file = self.data_dir / "urbs_content.txt"
        
        # Configurar logging
        self.setup_logging()
        
        # Driver Selenium
        self.driver = None
    
    def setup_logging(self):
        """Configura logging simples"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    def create_selenium_driver(self):
        """Cria driver Chrome com anti-detecção (tenta múltiplas opções)"""
        logging.info("🚀 Criando driver Selenium...")
        
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        options.add_argument('--window-size=1920,1080')
        options.add_argument('--disable-gpu')
        
        # OPÇÃO 1: Tentar com webdriver-manager (melhor opção - automático)
        if WEBDRIVER_MANAGER_AVAILABLE:
            try:
                logging.info("📦 Usando webdriver-manager (download automático)...")
                service = Service(ChromeDriverManager().install())
                self.driver = webdriver.Chrome(service=service, options=options)
                self.driver.set_page_load_timeout(30)
                
                try:
                    self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
                    })
                except:
                    pass
                
                logging.info("✅ Driver criado com webdriver-manager")
                return True
            except Exception as e:
                logging.warning(f"⚠️ webdriver-manager falhou: {e}")
        
        # OPÇÃO 2: Tentar encontrar Chrome instalado
        chrome_paths = [
            '/usr/bin/google-chrome',
            '/usr/bin/chromium',
            '/usr/bin/chromium-browser',
            '/snap/bin/chromium',
            'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
            'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
        ]
        
        chrome_found = None
        for path in chrome_paths:
            if Path(path).exists():
                chrome_found = path
                logging.info(f"✅ Chrome encontrado: {path}")
                options.binary_location = path
                break
        
        if chrome_found:
            try:
                self.driver = webdriver.Chrome(options=options)
                self.driver.set_page_load_timeout(30)
                
                try:
                    self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                        'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
                    })
                except:
                    pass
                
                logging.info("✅ Driver criado com Chrome local")
                return True
            except Exception as e:
                logging.error(f"❌ Erro ao criar driver: {e}")
        
        # Falhou
        logging.error("")
        logging.error("❌ NÃO FOI POSSÍVEL CRIAR O DRIVER SELENIUM")
        logging.error("")
        logging.error("💡 SOLUÇÕES:")
        logging.error("")
        logging.error("   OPÇÃO 1 (RECOMENDADA - AUTOMÁTICA):")
        logging.error("      pip install webdriver-manager")
        logging.error("")
        logging.error("   OPÇÃO 2 (INSTALAR CHROME MANUALMENTE):")
        logging.error("      Ubuntu/Debian: sudo apt-get install chromium-browser")
        logging.error("      Fedora: sudo dnf install chromium")
        logging.error("      Arch: sudo pacman -S chromium")
        logging.error("      Windows: https://www.google.com/chrome/")
        logging.error("")
        return False
    
    def get_urbs_content(self) -> str:
        """Obtém conteúdo do site da URBS"""
        logging.info(f"🌐 Acessando {self.URBS_URL}")
        
        try:
            if not self.driver:
                if not self.create_selenium_driver():
                    return ""
            
            # Carregar página
            self.driver.get(self.URBS_URL)
            
            # Aguardar carregamento
            time.sleep(5)
            
            # Aguardar body
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except TimeoutException:
                logging.warning("⚠️ Timeout esperando body")
            
            # Obter HTML
            html = self.driver.page_source
            
            logging.info(f"✅ Página carregada: {len(html)} caracteres")
            
            # Extrair conteúdo relevante
            content = self.extract_content(html)
            
            return content
        
        except Exception as e:
            logging.error(f"❌ Erro ao obter conteúdo: {e}")
            return ""
    
    def extract_content(self, html: str) -> str:
        """Extrai conteúdo relevante do HTML"""
        if not html:
            return ""
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remover elementos irrelevantes
            for element in soup(['script', 'style', 'meta', 'link', 'iframe', 
                               'noscript', 'nav', 'footer', 'header', 'aside']):
                element.decompose()
            
            content_parts = []
            
            # Extrair títulos principais
            for heading in soup.find_all(['h1', 'h2', 'h3']):
                text = heading.get_text(strip=True)
                if text and len(text) > 3:
                    content_parts.append(f"TÍTULO: {text}")
            
            # Extrair tabelas (provavelmente onde estão os dados de transporte)
            for table in soup.find_all('table'):
                table_data = []
                for row in table.find_all('tr')[:30]:  # Primeiras 30 linhas
                    cells = row.find_all(['td', 'th'])
                    if cells:
                        row_text = ' | '.join(
                            cell.get_text(strip=True) 
                            for cell in cells 
                            if cell.get_text(strip=True)
                        )
                        if row_text:
                            table_data.append(row_text)
                
                if table_data:
                    content_parts.append("TABELA:")
                    content_parts.extend(table_data)
            
            # Extrair parágrafos importantes
            for p in soup.find_all('p'):
                text = p.get_text(strip=True)
                if text and len(text) > 30:
                    content_parts.append(text)
            
            # Extrair listas
            for ul in soup.find_all(['ul', 'ol']):
                for li in ul.find_all('li'):
                    text = li.get_text(strip=True)
                    if text and len(text) > 10:
                        content_parts.append(f"• {text}")
            
            # Juntar tudo
            full_content = '\n'.join(content_parts)
            
            # NORMALIZAR: remover timestamps, datas, horários dinâmicos
            full_content = self.normalize_content(full_content)
            
            logging.info(f"📄 Conteúdo extraído: {len(full_content)} caracteres")
            logging.info(f"📋 {len(content_parts)} elementos encontrados")
            
            return full_content
        
        except Exception as e:
            logging.error(f"❌ Erro ao extrair conteúdo: {e}")
            return ""
    
    def normalize_content(self, content: str) -> str:
        """Normaliza conteúdo para evitar falsos positivos"""
        import re
        
        # Remover timestamps e datas
        content = re.sub(r'\d{1,2}/\d{1,2}/\d{2,4}', '', content)
        content = re.sub(r'\d{1,2}:\d{2}(?::\d{2})?', '', content)
        
        # Remover "atualizado em", "última atualização", etc
        content = re.sub(r'(?i)(atualizado|última atualização|last update).*?\n', '', content)
        
        # Remover linhas muito curtas (ruído)
        lines = [line.strip() for line in content.split('\n') if len(line.strip()) > 10]
        
        # Ordenar linhas para ignorar mudanças de ordem
        lines.sort()
        
        return '\n'.join(lines)
    
    def load_last_hash(self) -> str:
        """Carrega último hash salvo"""
        if not self.hash_file.exists():
            return ""
        
        try:
            with open(self.hash_file, 'r') as f:
                data = json.load(f)
                return data.get('hash', '')
        except:
            return ""
    
    def save_hash(self, content_hash: str):
        """Salva hash atual"""
        try:
            data = {
                'hash': content_hash,
                'timestamp': datetime.now(LOCAL_TZ).isoformat(),
                'url': self.URBS_URL
            }
            with open(self.hash_file, 'w') as f:
                json.dump(data, f, indent=2)
            logging.info("💾 Hash salvo")
        except Exception as e:
            logging.error(f"❌ Erro ao salvar hash: {e}")
    
    def save_content(self, content: str):
        """Salva conteúdo para referência"""
        try:
            with open(self.content_file, 'w', encoding='utf-8') as f:
                f.write(content)
            logging.info("💾 Conteúdo salvo")
        except Exception as e:
            logging.error(f"❌ Erro ao salvar conteúdo: {e}")
    
    def calculate_hash(self, content: str) -> str:
        """Calcula hash SHA256 do conteúdo"""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def detect_change(self, new_content: str) -> bool:
        """Detecta se houve mudança"""
        if not new_content or len(new_content) < 100:
            logging.warning("⚠️ Conteúdo muito curto ou vazio")
            return False
        
        new_hash = self.calculate_hash(new_content)
        old_hash = self.load_last_hash()
        
        # Salvar novo conteúdo
        self.save_content(new_content)
        
        # Primeira execução
        if not old_hash:
            logging.info("🆕 Primeira execução - salvando hash inicial")
            self.save_hash(new_hash)
            return False
        
        # Comparar hashes
        if new_hash == old_hash:
            logging.info("✅ Nenhuma mudança detectada")
            return False
        
        # Mudança detectada!
        logging.info("🔔 MUDANÇA DETECTADA!")
        logging.info(f"   Hash anterior: {old_hash[:16]}...")
        logging.info(f"   Hash novo: {new_hash[:16]}...")
        
        self.save_hash(new_hash)
        return True
    
    def send_email_notification(self):
        """Envia notificação por email"""
        logging.info("📧 Enviando notificação por email...")
        
        if not self.gmail_user or not self.gmail_password:
            logging.error("❌ Credenciais Gmail não configuradas")
            return False
        
        try:
            msg = MIMEMultipart("alternative")
            msg["From"] = formataddr((str(Header("URBS Monitor", "utf-8")), self.gmail_user))
            msg["To"] = ", ".join(self.email_recipients)
            msg["Subject"] = Header("🚨 Mudança Detectada no Boletim da URBS", "utf-8")
            
            # Conteúdo HTML
            html_content = f"""
            <html>
            <head>
            <meta charset="UTF-8">
            <style>
            body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; background: #f5f5f5; }}
            .container {{ max-width: 600px; margin: 20px auto; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
            .header {{ background: #1e88e5; color: white; padding: 20px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 22px; }}
            .content {{ padding: 20px; }}
            .info-box {{ background: #e3f2fd; border-left: 4px solid #1e88e5; padding: 15px; margin: 15px 0; border-radius: 4px; }}
            .button {{ display: inline-block; background: #1e88e5; color: white; padding: 12px 24px; text-decoration: none; border-radius: 4px; margin: 15px 0; }}
            .footer {{ background: #757575; color: white; padding: 15px; text-align: center; font-size: 12px; }}
            </style>
            </head>
            <body>
            <div class="container">
            <div class="header">
            <h1>🚨 Mudança Detectada no Boletim da URBS</h1>
            </div>
            
            <div class="content">
            <div class="info-box">
            <p><strong>🌐 Site:</strong> URBS - Boletim de Transportes</p>
            <p><strong>🕐 Data/Hora:</strong> {datetime.now(LOCAL_TZ).strftime('%d/%m/%Y %H:%M:%S')}</p>
            <p><strong>📍 URL:</strong> <a href="{self.URBS_URL}">{self.URBS_URL}</a></p>
            </div>
            
            <p>O sistema detectou uma mudança no conteúdo do Boletim de Transportes da URBS.</p>
            
            <p style="text-align: center;">
            <a href="{self.URBS_URL}" class="button">Acessar Boletim</a>
            </p>
            </div>
            
            <div class="footer">
            🤖 URBS Monitor - Sistema Automático de Monitoramento<br>
            <small>Não responda este e-mail</small>
            </div>
            </div>
            </body>
            </html>
            """
            
            html_part = MIMEText(html_content, "html", "utf-8")
            msg.attach(html_part)
            
            # Enviar via Gmail SMTP
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(self.gmail_user, self.gmail_password)
                server.sendmail(self.gmail_user, self.email_recipients, msg.as_string())
            
            logging.info("✅ Email enviado com sucesso!")
            return True
        
        except Exception as e:
            logging.error(f"❌ Erro ao enviar email: {e}")
            return False
    
    def run(self):
        """Executa o monitoramento"""
        logging.info("=" * 60)
        logging.info("🚀 URBS MONITOR - Iniciando")
        logging.info("=" * 60)
        
        try:
            # Obter conteúdo
            content = self.get_urbs_content()
            
            if not content:
                logging.error("❌ Falha ao obter conteúdo")
                return False
            
            # Detectar mudança
            changed = self.detect_change(content)
            
            if changed:
                logging.info("🔔 Mudança detectada! Enviando notificação...")
                self.send_email_notification()
            
            logging.info("=" * 60)
            logging.info("✅ URBS MONITOR - Concluído")
            logging.info("=" * 60)
            
            return True
        
        except Exception as e:
            logging.error(f"❌ Erro fatal: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        finally:
            # Fechar driver
            if self.driver:
                try:
                    self.driver.quit()
                    logging.info("🔒 Driver Selenium fechado")
                except:
                    pass


def main():
    """Função principal"""
    
    # Obter configurações de variáveis de ambiente
    gmail_user = os.getenv("GMAIL_USER")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    email_recipients = os.getenv("EMAIL_RECIPIENTS", "").split(",")
    
    # Validar configurações
    if not gmail_user or not gmail_password:
        print("❌ ERRO: Configure as variáveis de ambiente:")
        print("   GMAIL_USER - seu email Gmail")
        print("   GMAIL_APP_PASSWORD - senha de app do Gmail")
        sys.exit(1)
    
    if not email_recipients or email_recipients == ['']:
        print("❌ ERRO: Configure EMAIL_RECIPIENTS")
        print("   Exemplo: export EMAIL_RECIPIENTS='email1@example.com,email2@example.com'")
        sys.exit(1)
    
    # Criar e executar monitor
    monitor = URBSMonitor(
        email_recipients=email_recipients,
        gmail_user=gmail_user,
        gmail_password=gmail_password
    )
    
    success = monitor.run()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
