# Web Scraping Scripts

Une suite complète d'outils pour le scraping de contenu web (texte, images, vidéos, YouTube) avec une interface utilisateur web et une interface en ligne de commande.

## Fonctionnalités

- **Scraping multi-contenu** : Extraction de texte, images, vidéos et autres médias
- **Support YouTube** : Extraction et téléchargement de vidéos YouTube via pytube et yt-dlp
- **Interface utilisateur web** : Interface Streamlit pour une utilisation facile
- **Interface en ligne de commande** : Pour l'automatisation et les scripts
- **Gestion robuste des erreurs** : Retry automatique, gestion des timeouts, contournement SSL
- **Organisation des données** : Structure JSON claire et organisation des fichiers par type
- **Formats multiples** : Export en JSON, CSV et autres formats
- **Modes de scraping** : Support de plusieurs moteurs (requests, Selenium, Playwright, etc.)

## Installation

1. Cloner le dépôt :
   ```bash
   git clone
   ```

2. Créer un environnement virtuel (recommandé) :
   ```bash
   python -m venv venv
   # Sur Windows
   venv\Scripts\activate
   # Sur Linux/Mac
   source venv/bin/activate
   ```

3. Installer les dépendances :
   ```bash
   pip install -r src/requirements.txt
   ```

4. Installer les navigateurs pour Playwright (si vous utilisez ce mode) :
   ```bash
   playwright install
   ```

## Utilisation

### Interface Web (Streamlit)

1. Lancer l'interface web :
   ```bash
   cd src
   streamlit run web_interface.py
   ```

2. Ouvrir votre navigateur à l'adresse indiquée (généralement http://localhost:8501)

3. Utiliser l'interface pour :
   - Entrer des URLs à scraper
   - Sélectionner les types de contenu à extraire
   - Configurer les options de téléchargement
   - Visualiser et télécharger les résultats

### Interface en ligne de commande

#### Scraping d'une URL unique :

```bash
cd src
python cli.py --url "https://example.com" --extract-all --output-format json
```

#### Scraping d'une liste d'URLs :

```bash
cd src
python cli.py --urls-file urls.txt --extract-images --extract-videos
```

#### Utilisation d'un fichier de configuration pipeline :

```bash
cd src
python cli.py --pipeline custom_pipeline.yaml
```

#### Options principales :

- `--url` : URL unique à scraper
- `--urls-file` : Fichier contenant une liste d'URLs (une par ligne)
- `--pipeline` : Fichier de configuration pipeline YAML
- `--mode` : Mode de scraping (simple, selenium, playwright, etc.)
- `--extract-text` : Extraire le texte
- `--extract-images` : Extraire les images
- `--extract-videos` : Extraire les vidéos
- `--extract-youtube` : Extraire les vidéos YouTube
- `--extract-all` : Extraire tous les types de contenu
- `--output-format` : Format de sortie (json, csv)
- `--output-file` : Nom du fichier de sortie

### Utilisation via Python

```python
from config import Config
from scraper import ScraperFactory
from parser import Parser
from storage import StorageFactory
from youtube_downloader import YouTubeDownloader

# Charger la configuration
config = Config("config.yaml")

# Initialiser les composants
scraper = ScraperFactory.get_scraper("playwright", config)
parser = Parser(config)
storage = StorageFactory.get_storage(config)
youtube_downloader = YouTubeDownloader(config)

# Scraper une URL
html_content = scraper.scrape("https://example.com")

# Parser le contenu
parsed_data = parser.parse_html(html_content)

# Extraire des images
images = parser.extract_images(html_content, "https://example.com")

# Sauvegarder les données
storage.save(parsed_data)

# Télécharger une vidéo YouTube
video_info = youtube_downloader.get_video_info_pytube("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
download_result = youtube_downloader.download_video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
```

## Configuration

Le comportement du scraper peut être configuré via les fichiers YAML :

### config.yaml

Contient la configuration globale :
- User agent, timeouts, retries
- Configuration du stockage et des médias
- Options YouTube
- Configuration du proxy
- Configuration du navigateur

### pipeline.yaml

Définit un pipeline de scraping :
- URLs à scraper
- Mode de scraping
- Types de contenu à extraire
- Options de post-traitement

## Structure du projet

```
src/
├── app.py                # Application Streamlit (ancienne version)
├── cli.py                # Interface en ligne de commande
├── config.py             # Gestion de la configuration
├── config.yaml           # Fichier de configuration
├── fix_ssl.py            # Utilitaire pour les problèmes SSL
├── main.py               # Point d'entrée principal
├── media_downloader.py   # Téléchargement de médias
├── parser.py             # Parsing du contenu HTML
├── pipeline.yaml         # Configuration du pipeline
├── requirements.txt      # Dépendances
├── scraper.py            # Classes de scraping
├── storage.py            # Stockage des données
├── web_interface.py      # Interface web Streamlit
└── youtube_downloader.py # Téléchargement YouTube
```

## Exemples

### Exemple de fichier pipeline.yaml

```yaml
name: "YouTube Music Videos"
description: "Scrape music videos from YouTube"
scraper_mode: "playwright"
urls:
  - "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  - "https://www.youtube.com/watch?v=9bZkp7q19f0"
extract_youtube: true
youtube:
  download_videos: true
  preferred_resolution: "720p"
```

### Exemple d'utilisation CLI

```bash
# Scraper des images de sites de photos
python cli.py --urls-file photo_sites.txt --extract-images --mode playwright

# Télécharger des vidéos YouTube
python cli.py --urls-file youtube_links.txt --extract-youtube --output-file youtube_videos
```

## Licence

Ce projet est sous licence MIT.

## Contributions

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou une pull request.

#### Realiser par OURTI ABDELILAH