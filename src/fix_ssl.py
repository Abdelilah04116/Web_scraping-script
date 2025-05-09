#!/usr/bin/env python3
"""
Ce script modifie le fichier scraper.py pour désactiver la vérification SSL
lors des requêtes, ce qui permettra le téléchargement des médias du site
ENSIAS qui a un problème de certificat SSL.
"""

import os
import sys
import re

def update_config_class():
    """Mettre à jour la classe Config pour désactiver par défaut la vérification SSL"""
    config_file = "config.py"
    
    if not os.path.exists(config_file):
        print(f"Erreur: Le fichier {config_file} n'existe pas.")
        return False
    
    with open(config_file, 'r') as f:
        content = f.read()
    
    # Rechercher la méthode get_verify_ssl
    verify_ssl_pattern = r"def get_verify_ssl\(self\):[^\}]+?return .*?\n"
    
    if re.search(verify_ssl_pattern, content):
        # Remplacer la méthode existante
        updated_content = re.sub(
            verify_ssl_pattern,
            "def get_verify_ssl(self):\n        # SSL verification is disabled for ENSIAS website\n        return False\n",
            content
        )
    else:
        # Ajouter la méthode si elle n'existe pas
        class_pattern = r"class Config:"
        updated_content = re.sub(
            class_pattern,
            "class Config:\n    def get_verify_ssl(self):\n        # SSL verification is disabled for ENSIAS website\n        return False",
            content
        )
    
    with open(config_file, 'w') as f:
        f.write(updated_content)
    
    print(f"✅ Fichier {config_file} mis à jour avec succès")
    return True

def update_scraper_ssl_settings():
    """Mettre à jour le fichier scraper.py pour désactiver la vérification SSL"""
    scraper_file = "scraper.py"
    
    if not os.path.exists(scraper_file):
        print(f"Erreur: Le fichier {scraper_file} n'existe pas.")
        return False
    
    with open(scraper_file, 'r') as f:
        content = f.read()
    
    # Ajouter l'importation de urllib3 si elle n'existe pas déjà
    if "import urllib3" not in content:
        import_pattern = r"import re\n"
        updated_content = re.sub(
            import_pattern,
            "import re\nimport urllib3\n",
            content
        )
    else:
        updated_content = content
    
    # Désactiver les avertissements SSL dans MediaDownloader
    media_downloader_init_pattern = r"def __init__\(self, config\):[^}]+?self\.session = requests\.Session\(\)"
    
    if re.search(media_downloader_init_pattern, updated_content):
        updated_content = re.sub(
            media_downloader_init_pattern,
            """def __init__(self, config):
        self.config = config
        self.storage_config = config.config.get('storage', {})
        self.media_folder = self.storage_config.get('media_folder', 'downloaded_media')
        self.media_types = self.storage_config.get('media_types', {})
        self.max_file_size = self.storage_config.get('max_file_size', 100) * 1024 * 1024  # Convert to bytes
        self._setup_folders()
        
        # Initialiser la session avec verify=False pour ignorer les erreurs de certificat SSL
        self.session = requests.Session()
        self.session.verify = False
        
        # Désactiver les avertissements liés aux certificats non vérifiés
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)""",
            updated_content
        )
    
    # Mettre à jour la méthode download_media pour désactiver la vérification SSL
    download_media_pattern = r"response = self\.session\.get\(absolute_url, stream=True\)"
    
    if re.search(download_media_pattern, updated_content):
        updated_content = re.sub(
            download_media_pattern,
            "response = self.session.get(absolute_url, stream=True, verify=False)",
            updated_content
        )
    
    # Désactiver la vérification SSL dans SimpleScraper
    simple_scraper_init_pattern = r"def __init__\(self, config\):[^}]+?self\.session\.verify = verify_ssl"
    
    if re.search(simple_scraper_init_pattern, updated_content):
        updated_content = re.sub(
            simple_scraper_init_pattern,
            """def __init__(self, config):
        super().__init__(config)
        self.session = requests.Session()
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/119.0.2151.97 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/119.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        ]
        
        # Toujours désactiver la vérification SSL, quelle que soit la configuration
        self.session.verify = False
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)""",
            updated_content
        )
    
    # Mise à jour de la méthode scrape de SimpleScraper
    simple_scraper_scrape_pattern = r"response = self\.session\.get\(\s+url,\s+timeout=self\.timeout,\s+proxies=self\.proxies,\s+allow_redirects=True\s+\)"
    
    if re.search(simple_scraper_scrape_pattern, updated_content):
        updated_content = re.sub(
            simple_scraper_scrape_pattern,
            """response = self.session.get(
                url, 
                timeout=self.timeout,
                proxies=self.proxies,
                allow_redirects=True,
                verify=False
            )""",
            updated_content
        )
    
    # Mise à jour du PlaywrightScraper pour désactiver la vérification SSL
    playwright_launch_pattern = r"launch_options = \{[^}]+?\}"
    
    if re.search(playwright_launch_pattern, updated_content):
        updated_content = re.sub(
            playwright_launch_pattern,
            """launch_options = {
            'headless': browser_config.get("headless", True),
            'args': [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials',
                '--ignore-certificate-errors'
            ]
        }""",
            updated_content
        )
    
    # Mise à jour des options de contexte Playwright
    context_options_pattern = r"context_options = \{[^}]+?\}"
    
    if re.search(context_options_pattern, updated_content):
        updated_content = re.sub(
            context_options_pattern,
            """context_options = {
            'user_agent': self.user_agent,
            'viewport': {'width': 1920, 'height': 1080},
            'java_script_enabled': True,
            'bypass_csp': True,
            'ignore_https_errors': True
        }""",
            updated_content
        )
    
    with open(scraper_file, 'w') as f:
        f.write(updated_content)
    
    print(f"✅ Fichier {scraper_file} mis à jour avec succès")
    return True

def main():
    print("🔧 Application des correctifs pour désactiver la vérification SSL...")
    
    # Mettre à jour config.py
    config_updated = update_config_class()
    
    # Mettre à jour scraper.py
    scraper_updated = update_scraper_ssl_settings()
    
    if config_updated and scraper_updated:
        print("\n✅ Tous les fichiers ont été mis à jour avec succès!")
        print("\nVous pouvez maintenant exécuter le script principal avec:")
        print("  python main.py")
        return 0
    else:
        print("\n❌ Certaines mises à jour ont échoué. Vérifiez les messages d'erreur ci-dessus.")
        return 1

if __name__ == "__main__":
    sys.exit(main())