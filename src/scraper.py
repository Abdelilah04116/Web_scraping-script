import time
import random
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from playwright.sync_api import sync_playwright
import scrapy
from scrapy.crawler import CrawlerProcess
import pyppeteer
import asyncio
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from config import Config
try:
    from youtube_downloader import YouTubeDownloader
except ImportError:
    logger.warning("YouTubeDownloader not found, YouTube download functionality will be disabled")
    YouTubeDownloader = None

try:
    from soundcloud_downloader import SoundCloudDownloader
except ImportError:
    logger.warning("SoundCloudDownloader not found, SoundCloud download functionality will be disabled")
    SoundCloudDownloader = None

import os
import aiohttp
import asyncio
from urllib.parse import urljoin, urlparse
import mimetypes
import hashlib
from pathlib import Path
import re

class ScraperFactory:
    @staticmethod
    def get_scraper(mode="simple", config=None):
        if config is None:
            config = Config()

        scrapers = {
            "simple": SimpleScraper,
            "selenium": SeleniumScraper,
            "scrapy": ScrapyScraper,
            "pyppeteer": PyppeteerScraper,
            "playwright": PlaywrightScraper
        }

        if mode not in scrapers:
            logger.warning(f"Mode {mode} not supported, falling back to simple mode")
            mode = "simple"

        return scrapers[mode](config)

class BaseScraper:
    def __init__(self, config):
        self.config = config
        self.session = None
        self.delay = self.config.get_delay_between_requests()
        self.user_agent = self.config.get_user_agent()
        self.timeout = self.config.get_request_timeout()
        self.max_retries = self.config.get_max_retries()
        self.proxies = self._get_proxies()

        # Désactiver les avertissements SSL
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get_proxies(self):
        proxy_settings = self.config.get_proxy_settings()
        if not proxy_settings.get('enabled', False):
            return None

        proxy_type = proxy_settings.get('type', 'http')
        host = proxy_settings.get('host', '')
        port = proxy_settings.get('port', '')
        username = proxy_settings.get('username', '')
        password = proxy_settings.get('password', '')

        if not host or not port:
            return None

        proxy_url = f"{proxy_type}://"
        if username and password:
            proxy_url += f"{username}:{password}@"
        proxy_url += f"{host}:{port}"

        return {
            "http": proxy_url,
            "https": proxy_url
        }

    def _add_jitter(self, delay):
        return delay * (1 + random.uniform(-0.2, 0.2))

    def _sleep(self):
        time.sleep(self._add_jitter(self.delay))

    def scrape(self, url):
        raise NotImplementedError("Subclasses must implement scrape method")

    def close(self):
        pass

class SimpleScraper(BaseScraper):
    def __init__(self, config):
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
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _get_headers(self):
        """Get request headers with a random user agent"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60))
    def scrape(self, url, selectors=None):
        try:
            self._sleep()

            # Get new headers for each request
            headers = self._get_headers()
            self.session.headers.update(headers)

            # First make a GET request to get cookies - verify=False explicitement spécifié
            response = self.session.get(
                url,
                timeout=self.timeout,
                proxies=self.proxies,
                allow_redirects=True,
                verify=False  # Important: désactiver la vérification SSL
            )
            response.raise_for_status()

            # Add a small delay between requests
            time.sleep(2)

            if not response.text:
                logger.warning(f"Empty response from {url}")
                return None

            if selectors is None:
                return response.text

            soup = BeautifulSoup(response.text, 'lxml')
            result = {}
            for key, selector in selectors.items():
                elements = soup.select(selector)
                if elements:
                    result[key] = [elem.get_text().strip() for elem in elements]
                    if len(result[key]) == 1:
                        result[key] = result[key][0]
                else:
                    result[key] = None

            return result

        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            raise

    def close(self):
        if self.session:
            self.session.close()

class SeleniumScraper(BaseScraper):
    def __init__(self, config):
        super().__init__(config)
        self.driver = None
        try:
            self.driver = self._setup_driver()
        except Exception as e:
            logger.error(f"Error initializing Selenium driver: {str(e)}")
            raise

    def _setup_driver(self):
        try:
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options

            # Basic Chrome options
            chrome_options = Options()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument(f"user-agent={self.user_agent}")

            # Create the WebDriver instance with basic options
            return webdriver.Chrome(options=chrome_options)

        except Exception as e:
            logger.error(f"Error in _setup_driver: {str(e)}")
            raise

    def scrape(self, url, selectors=None, wait_time=5):
        try:
            self._sleep()
            self.driver.get(url)
            time.sleep(wait_time)

            if selectors is None:
                return self.driver.page_source

            result = {}
            for key, selector in selectors.items():
                try:
                    from selenium.webdriver.common.by import By
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        result[key] = [elem.text.strip() for elem in elements if elem.text.strip()]
                        if len(result[key]) == 1:
                            result[key] = result[key][0]
                    else:
                        result[key] = None
                except Exception as e:
                    logger.warning(f"Error getting element with selector {selector}: {str(e)}")
                    result[key] = None

            return result

        except Exception as e:
            logger.error(f"Error scraping {url} with Selenium: {str(e)}")
            raise

    def close(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                logger.error(f"Error closing Selenium driver: {str(e)}")

class ScrapyScraper(BaseScraper):
    def __init__(self, config):
        super().__init__(config)
        self.process = CrawlerProcess({
            'USER_AGENT': self.user_agent,
            'DOWNLOAD_DELAY': self.delay
        })

    def scrape(self, url, selectors=None):
        # Scrapy requires more complex setup, typically through a Spider class
        # This implementation is simplified for demonstration
        results = []

        class SimpleSpider(scrapy.Spider):
            name = 'simple_spider'
            start_urls = [url]

            def parse(self, response):
                if selectors is None:
                    results.append(response.text)
                    return

                result = {}
                for key, selector in selectors.items():
                    elements = response.css(selector)
                    if elements:
                        result[key] = [elem.get().strip() for elem in elements]
                    else:
                        result[key] = []
                results.append(result)

        self.process.crawl(SimpleSpider)
        self.process.start()

        return results[0] if results else None

class PyppeteerScraper(BaseScraper):
    def __init__(self, config):
        super().__init__(config)
        self.browser = None
        self.page = None

    async def _setup_browser(self):
        browser_config = self.config.get_browser_config()

        launch_options = {
            'headless': browser_config.get("headless", True),
            'args': [
                f'--window-size={browser_config.get("window_size", "1920,1080")}',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-extensions'
            ]
        }

        if not browser_config.get("load_images", False):
            launch_options['args'].append('--blink-settings=imagesEnabled=false')

        proxy_settings = self.config.get_proxy_settings()
        if proxy_settings.get('enabled', False) and proxy_settings.get('host') and proxy_settings.get('port'):
            proxy_url = f"{proxy_settings.get('host')}:{proxy_settings.get('port')}"
            launch_options['args'].append(f'--proxy-server={proxy_url}')

        self.browser = await pyppeteer.launch(launch_options)
        self.page = await self.browser.newPage()
        await self.page.setUserAgent(self.user_agent)

    async def _scrape_async(self, url, selectors=None, wait_time=5):
        if not self.browser:
            await self._setup_browser()

        await asyncio.sleep(self._add_jitter(self.delay))
        await self.page.goto(url, {'timeout': self.timeout * 1000, 'waitUntil': 'networkidle0'})
        await asyncio.sleep(wait_time)

        if selectors is None:
            return await self.page.content()

        result = {}
        for key, selector in selectors.items():
            elements = await self.page.querySelectorAll(selector)
            if elements:
                result[key] = [await self.page.evaluate('(element) => element.textContent', elem) for elem in elements]
            else:
                result[key] = []

        return result

    def scrape(self, url, selectors=None, wait_time=5):
        return asyncio.get_event_loop().run_until_complete(self._scrape_async(url, selectors, wait_time))

    def close(self):
        if self.browser:
            asyncio.get_event_loop().run_until_complete(self.browser.close())

class PlaywrightScraper(BaseScraper):
    def __init__(self, config):
        super().__init__(config)
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

        # Créer une nouvelle instance de MediaDownloader
        try:
            from media_downloader import MediaDownloader
            self.media_downloader = MediaDownloader(config)
        except ImportError as e:
            logger.error(f"Error importing MediaDownloader: {str(e)}")
            # Create a fallback minimal version if import fails
            class FallbackMediaDownloader:
                def __init__(self, config):
                    self.config = config
                def find_and_download_media(self, html_content, page_url):
                    return {'images': [], 'videos': [], 'audio': [], 'documents': [], 'other': []}
            self.media_downloader = FallbackMediaDownloader(config)

        # Initialiser YouTubeDownloader si disponible
        self.youtube_downloader = None
        if YouTubeDownloader is not None:
            try:
                self.youtube_downloader = YouTubeDownloader(config)
                logger.info("YouTubeDownloader initialized successfully")
            except Exception as e:
                logger.error(f"Error initializing YouTubeDownloader: {str(e)}")

        # Initialiser SoundCloudDownloader si disponible
        self.soundcloud_downloader = None
        if SoundCloudDownloader is not None:
            try:
                self.soundcloud_downloader = SoundCloudDownloader(config)
                logger.info("SoundCloudDownloader initialized successfully")
            except Exception as e:
                logger.error(f"Error initializing SoundCloudDownloader: {str(e)}")

        # Vérifier si le téléchargement YouTube est activé dans la configuration
        self.download_youtube_videos = config.config.get('youtube', {}).get('download_videos', False)
        self.download_youtube_thumbnails = config.config.get('youtube', {}).get('download_thumbnails', True)
        self.preferred_resolution = config.config.get('youtube', {}).get('preferred_resolution', '720p')

        # Vérifier si le téléchargement SoundCloud est activé dans la configuration
        self.download_soundcloud_tracks = config.config.get('sites', {}).get('soundcloud', {}).get('download', {}).get('tracks', False)
        self.download_soundcloud_artwork = config.config.get('sites', {}).get('soundcloud', {}).get('download', {}).get('artwork', False)
        self.soundcloud_audio_format = config.config.get('sites', {}).get('soundcloud', {}).get('download', {}).get('format', 'mp3')
        self.soundcloud_audio_quality = config.config.get('sites', {}).get('soundcloud', {}).get('download', {}).get('quality', '192k')

        self._setup_browser()

    def _setup_browser(self):
        browser_config = self.config.get_browser_config()

        self.playwright = sync_playwright().start()
        browser_type = self.playwright.chromium

        # Enhanced browser options for better stability
        launch_options = {
            'headless': browser_config.get("headless", True),
            'args': [
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials',
                # Ajouter cette option pour ignorer les erreurs de certificat
                '--ignore-certificate-errors'
            ]
        }

        self.browser = browser_type.launch(**launch_options)

        # Enhanced context options
        context_options = {
            'user_agent': self.user_agent,
            'viewport': {'width': 1920, 'height': 1080},
            'java_script_enabled': True,
            'bypass_csp': True,
            # Important: ignorer les erreurs HTTPS
            'ignore_https_errors': True
        }

        # Add proxy if configured
        proxy_settings = self.config.get_proxy_settings()
        if proxy_settings.get('enabled', False) and proxy_settings.get('host') and proxy_settings.get('port'):
            context_options['proxy'] = {
                'server': f"{proxy_settings.get('type', 'http')}://{proxy_settings.get('host')}:{proxy_settings.get('port')}"
            }
            if proxy_settings.get('username') and proxy_settings.get('password'):
                context_options['proxy']['username'] = proxy_settings.get('username')
                context_options['proxy']['password'] = proxy_settings.get('password')

        self.context = self.browser.new_context(**context_options)
        self.page = self.context.new_page()

    def _wait_for_youtube_content(self):
        """
        Wait for YouTube content to load with progressive strategy

        Returns:
            bool: True if content loaded successfully
        """
        try:
            # Try to wait for key elements with increasing timeouts
            try:
                # Wait for video player to be visible
                self.page.wait_for_selector('#player-container', timeout=10000)

                # Wait for video title
                self.page.wait_for_selector('h1.title', timeout=5000)

                # Check if we're on a watch page or shorts page
                if '/watch?' in self.page.url:
                    # Wait for description
                    self.page.wait_for_selector('#description-inline-expander', timeout=5000)

                    # Wait for channel info
                    self.page.wait_for_selector('#owner', timeout=5000)
                elif '/shorts/' in self.page.url:
                    # Wait for shorts specific elements - different selectors for shorts
                    try:
                        # Try different selectors for shorts as they can vary
                        self.page.wait_for_selector('ytd-reel-video-renderer', timeout=3000)
                    except:
                        try:
                            self.page.wait_for_selector('#shorts-container', timeout=3000)
                        except:
                            # Last resort - just wait for any video element
                            self.page.wait_for_selector('video', timeout=5000)

                return True
            except Exception as e:
                logger.warning(f"Some YouTube elements failed to load: {str(e)}")
                return False

        except Exception as e:
            logger.error(f"Error waiting for YouTube content: {str(e)}")
            return False

    def _extract_youtube_videos(self):
        """
        Extract video information from YouTube page

        Returns:
            list: List of video information dictionaries
        """
        try:
            videos = []

            # Check if we're on a watch page or shorts page
            if '/watch?' in self.page.url:
                # Extract video ID from URL
                video_id = self.page.url.split('v=')[1].split('&')[0] if 'v=' in self.page.url else None

                if not video_id:
                    return []

                # Extract video title
                title_elem = self.page.query_selector('h1.title')
                title = title_elem.text_content().strip() if title_elem else "Unknown Title"

                # Extract channel name
                channel_elem = self.page.query_selector('#owner-name a')
                channel = channel_elem.text_content().strip() if channel_elem else "Unknown Channel"

                # Extract view count
                view_count_elem = self.page.query_selector('span.view-count')
                view_count = view_count_elem.text_content().strip() if view_count_elem else "Unknown Views"

                # Extract description
                description_elem = self.page.query_selector('#description-inline-expander')
                description = description_elem.text_content().strip() if description_elem else ""

                videos.append({
                    'id': video_id,
                    'title': title,
                    'channel': channel,
                    'views': view_count,
                    'description': description,
                    'url': self.page.url
                })

            elif '/shorts/' in self.page.url:
                # Extract video ID from URL
                video_id = self.page.url.split('/shorts/')[1].split('?')[0] if '/shorts/' in self.page.url else None

                if not video_id:
                    return []

                # Try multiple selectors for shorts as the UI can vary
                # Method 1: Try standard selectors
                title = "Unknown Title"
                channel = "Unknown Channel"
                likes = "Unknown Likes"

                # Try different title selectors
                for title_selector in [
                    'ytd-reel-player-header-renderer h2',
                    '#shorts-title',
                    '.title.style-scope.ytd-shorts',
                    'h2.title'
                ]:
                    title_elem = self.page.query_selector(title_selector)
                    if title_elem:
                        title = title_elem.text_content().strip()
                        break

                # Try different channel selectors
                for channel_selector in [
                    'ytd-reel-player-header-renderer a.yt-simple-endpoint',
                    '#text-container.ytd-channel-name a',
                    '.short-channel-info a',
                    '#channel-name a'
                ]:
                    channel_elem = self.page.query_selector(channel_selector)
                    if channel_elem:
                        channel = channel_elem.text_content().strip()
                        break

                # Try to get likes count
                for likes_selector in [
                    '.like-button-renderer-like-button-unclicked span',
                    '#like-button span',
                    '.like-count'
                ]:
                    likes_elem = self.page.query_selector(likes_selector)
                    if likes_elem:
                        likes = likes_elem.text_content().strip()
                        break

                # Method 2: Extract from page metadata if available
                try:
                    # Get metadata from script tags
                    script_content = self.page.evaluate('''() => {
                        const scripts = Array.from(document.querySelectorAll('script'));
                        for (const script of scripts) {
                            if (script.textContent.includes('"shortDescription"')) {
                                return script.textContent;
                            }
                        }
                        return '';
                    }''')

                    if script_content:
                        import json
                        import re

                        # Try to extract JSON data
                        match = re.search(r'var ytInitialData = (.+?);</script>', script_content)
                        if match:
                            data = json.loads(match.group(1))
                            # Extract data from the complex YouTube structure
                            # This is a simplified approach and might need adjustments
                            video_data = data.get('contents', {}).get('twoColumnWatchNextResults', {})
                            if video_data:
                                # Extract more accurate information if available
                                title = title  # Keep existing title as fallback
                                channel = channel  # Keep existing channel as fallback
                except Exception as e:
                    logger.warning(f"Error extracting metadata from shorts page: {str(e)}")

                videos.append({
                    'id': video_id,
                    'title': title,
                    'channel': channel,
                    'likes': likes,
                    'url': self.page.url,
                    'is_short': True,
                    'thumbnail': self._get_youtube_thumbnail(video_id)
                })

            return videos

        except Exception as e:
            logger.error(f"Error extracting YouTube videos: {str(e)}")
            return []

    def _get_youtube_thumbnail(self, video_id):
        """
        Get YouTube thumbnail URLs for a video

        Args:
            video_id: YouTube video ID

        Returns:
            dict: Dictionary of thumbnail URLs
        """
        try:
            return {
                'default': f"https://img.youtube.com/vi/{video_id}/default.jpg",
                'medium': f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg",
                'high': f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                'standard': f"https://img.youtube.com/vi/{video_id}/sddefault.jpg",
                'maxres': f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            }
        except Exception as e:
            logger.error(f"Error getting YouTube thumbnails: {str(e)}")
            return {}

    def _extract_soundcloud_tracks(self):
        """
        Extract track information from SoundCloud page

        Returns:
            list: List of track information dictionaries
        """
        try:
            tracks = []

            # Vérifier si nous sommes sur une page SoundCloud
            if 'soundcloud.com' not in self.page.url:
                return []

            # Extraire les informations de la piste
            # Pour une piste individuelle
            if '/sets/' not in self.page.url:
                # Extraire l'ID de la piste à partir de l'URL
                track_url = self.page.url

                # Extraire le titre de la piste
                title_elem = self.page.query_selector('h1.soundTitle__title')
                title = title_elem.text_content().strip() if title_elem else "Unknown Title"

                # Extraire le nom de l'artiste
                artist_elem = self.page.query_selector('a.soundTitle__username')
                artist = artist_elem.text_content().strip() if artist_elem else "Unknown Artist"

                # Extraire le nombre de lectures
                plays_elem = self.page.query_selector('span.sc-ministats-plays')
                plays = plays_elem.text_content().strip() if plays_elem else ""

                # Extraire le nombre de likes
                likes_elem = self.page.query_selector('span.sc-ministats-likes')
                likes = likes_elem.text_content().strip() if likes_elem else ""

                # Extraire l'URL de l'artwork
                artwork_url = ""
                try:
                    artwork_elem = self.page.query_selector('div.image__full span.image__full')
                    if artwork_elem:
                        style = self.page.evaluate('(element) => window.getComputedStyle(element).backgroundImage', artwork_elem)
                        if style and 'url(' in style:
                            artwork_url = style.split('url(')[1].split(')')[0].strip('"\'')
                except Exception as e:
                    logger.warning(f"Error extracting artwork URL: {str(e)}")

                tracks.append({
                    'url': track_url,
                    'title': title,
                    'artist': artist,
                    'plays': plays,
                    'likes': likes,
                    'artwork_url': artwork_url
                })

            # Pour une playlist
            else:
                # Extraire les informations de la playlist
                playlist_title_elem = self.page.query_selector('h1.soundTitle__title')
                playlist_title = playlist_title_elem.text_content().strip() if playlist_title_elem else "Unknown Playlist"

                # Extraire les pistes de la playlist
                track_elements = self.page.query_selector_all('li.trackList__item')

                for track_elem in track_elements:
                    try:
                        # Extraire l'URL de la piste
                        track_link = track_elem.query_selector('a.trackItem__trackTitle')
                        track_url = track_link.get_attribute('href') if track_link else ""
                        if track_url and not track_url.startswith('http'):
                            track_url = f"https://soundcloud.com{track_url}"

                        # Extraire le titre de la piste
                        title = track_link.text_content().strip() if track_link else "Unknown Track"

                        # Extraire l'artiste
                        artist_elem = track_elem.query_selector('a.trackItem__username')
                        artist = artist_elem.text_content().strip() if artist_elem else "Unknown Artist"

                        tracks.append({
                            'url': track_url,
                            'title': title,
                            'artist': artist,
                            'playlist': playlist_title
                        })
                    except Exception as e:
                        logger.warning(f"Error extracting track from playlist: {str(e)}")

            return tracks

        except Exception as e:
            logger.error(f"Error extracting SoundCloud tracks: {str(e)}")
            return []

    def scrape(self, url, selectors=None, wait_time=5):
        try:
            time.sleep(self._add_jitter(self.delay))

            result = {
                'url': url,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'data': {}
            }

            if 'youtube.com' in url or 'youtu.be' in url:
                try:
                    # Initial page load with increased timeout
                    self.page.goto(url, timeout=60000, wait_until='domcontentloaded')

                    # Wait for initial render
                    time.sleep(wait_time / 2)  # Use half of the wait_time for initial render

                    # Scroll to ensure content loads
                    self.page.evaluate("""() => {
                        window.scrollBy(0, 200);
                        return new Promise(resolve => setTimeout(resolve, 1000));
                    }""")

                    # Wait for content with new progressive strategy
                    content_loaded = self._wait_for_youtube_content()

                    # Additional wait after content load
                    time.sleep(wait_time / 2)  # Use remaining wait_time

                    if content_loaded:
                        videos = self._extract_youtube_videos()
                        if (videos):
                            result['data']['videos'] = videos

                            # Try to get thumbnails for video
                            if '/watch?' in url and videos[0].get('id'):
                                thumbnails = self._get_youtube_thumbnail(videos[0]['id'])
                                videos[0]['thumbnails'] = thumbnails

                            logger.info(f"Successfully extracted {len(videos)} videos with details")

                            # Download video and thumbnail if enabled and YouTubeDownloader is available
                            if self.youtube_downloader is not None:
                                video_id = videos[0].get('id')
                                if video_id:
                                    # Download thumbnail if enabled
                                    if self.download_youtube_thumbnails:
                                        logger.info(f"Downloading thumbnail for video {video_id}")
                                        thumbnail_result = self.youtube_downloader.download_thumbnail(url)
                                        if thumbnail_result.get('success'):
                                            videos[0]['thumbnail_download'] = thumbnail_result
                                            logger.info(f"Thumbnail downloaded successfully: {thumbnail_result.get('file_path')}")
                                        else:
                                            logger.warning(f"Failed to download thumbnail: {thumbnail_result.get('error')}")

                                    # Vérifier si on doit télécharger l'audio uniquement
                                    audio_only = self.config.config.get('youtube', {}).get('download_audio_only', False)

                                    if audio_only:
                                        # Télécharger l'audio uniquement
                                        audio_format = self.config.config.get('youtube', {}).get('audio_format', 'mp3')
                                        audio_quality = self.config.config.get('youtube', {}).get('audio_quality', '192k')
                                        logger.info(f"Downloading audio for video {video_id} in {audio_format} format at {audio_quality} quality")
                                        audio_result = self.youtube_downloader.download_audio(url, audio_format, audio_quality)
                                        if audio_result.get('success'):
                                            videos[0]['audio_download'] = audio_result
                                            logger.info(f"Audio downloaded successfully: {audio_result.get('file_path')}")
                                        else:
                                            logger.warning(f"Failed to download audio: {audio_result.get('error')}")

                                    # Download video if enabled and not audio_only
                                    elif self.download_youtube_videos:
                                        logger.info(f"Downloading video {video_id} with resolution {self.preferred_resolution}")
                                        download_result = self.youtube_downloader.download_video(url, self.preferred_resolution)
                                        if download_result.get('success'):
                                            videos[0]['video_download'] = download_result
                                            logger.info(f"Video downloaded successfully: {download_result.get('file_path')}")
                                        else:
                                            logger.warning(f"Failed to download video: {download_result.get('error')}")

                                        # Extraire l'audio si demandé
                                        extract_audio = self.config.config.get('youtube', {}).get('extract_audio', False)
                                        if extract_audio:
                                            audio_format = self.config.config.get('youtube', {}).get('audio_format', 'mp3')
                                            audio_quality = self.config.config.get('youtube', {}).get('audio_quality', '192k')
                                            logger.info(f"Extracting audio from video {video_id}")
                                            audio_result = self.youtube_downloader.download_audio(url, audio_format, audio_quality)
                                            if audio_result.get('success'):
                                                videos[0]['audio_download'] = audio_result
                                                logger.info(f"Audio extracted successfully: {audio_result.get('file_path')}")
                                            else:
                                                logger.warning(f"Failed to extract audio: {audio_result.get('error')}")
                        else:
                            logger.warning("No videos extracted from YouTube page")
                    else:
                        logger.warning("Failed to load all YouTube elements but continuing with extraction")
                        # Try extraction anyway in case we got partial content
                        videos = self._extract_youtube_videos()
                        if videos:
                            result['data']['videos'] = videos
                            logger.info(f"Extracted {len(videos)} videos despite loading issues")

                            # Try to download even with loading issues
                            if self.youtube_downloader is not None and videos[0].get('id'):
                                # Download thumbnail if enabled
                                if self.download_youtube_thumbnails:
                                    thumbnail_result = self.youtube_downloader.download_thumbnail(url)
                                    if thumbnail_result.get('success'):
                                        videos[0]['thumbnail_download'] = thumbnail_result

                                # Vérifier si on doit télécharger l'audio uniquement
                                audio_only = self.config.config.get('youtube', {}).get('download_audio_only', False)

                                if audio_only:
                                    # Télécharger l'audio uniquement
                                    audio_format = self.config.config.get('youtube', {}).get('audio_format', 'mp3')
                                    audio_quality = self.config.config.get('youtube', {}).get('audio_quality', '192k')
                                    audio_result = self.youtube_downloader.download_audio(url, audio_format, audio_quality)
                                    if audio_result.get('success'):
                                        videos[0]['audio_download'] = audio_result

                                # Download video if enabled and not audio_only
                                elif self.download_youtube_videos:
                                    download_result = self.youtube_downloader.download_video(url, self.preferred_resolution)
                                    if download_result.get('success'):
                                        videos[0]['video_download'] = download_result

                                    # Extraire l'audio si demandé
                                    extract_audio = self.config.config.get('youtube', {}).get('extract_audio', False)
                                    if extract_audio:
                                        audio_format = self.config.config.get('youtube', {}).get('audio_format', 'mp3')
                                        audio_quality = self.config.config.get('youtube', {}).get('audio_quality', '192k')
                                        audio_result = self.youtube_downloader.download_audio(url, audio_format, audio_quality)
                                        if audio_result.get('success'):
                                            videos[0]['audio_download'] = audio_result

                    return result

                except Exception as e:
                    logger.warning(f"Error handling YouTube content: {str(e)}")
                    return result

            # Gestion de SoundCloud
            if 'soundcloud.com' in url:
                try:
                    # Charger la page SoundCloud
                    self.page.goto(url, wait_until='networkidle', timeout=60000)
                    content = self.page.content()

                    # Extraire les pistes SoundCloud
                    tracks = self._extract_soundcloud_tracks()
                    if tracks:
                        result['data']['tracks'] = tracks
                        logger.info(f"Successfully extracted {len(tracks)} tracks from SoundCloud")

                        # Télécharger les pistes et les artworks si activé
                        if self.soundcloud_downloader is not None and tracks:
                            for i, track in enumerate(tracks):
                                track_url = track.get('url')
                                if track_url:
                                    # Télécharger la piste audio
                                    if self.download_soundcloud_tracks:
                                        logger.info(f"Downloading track: {track.get('title')} by {track.get('artist')}")
                                        track_result = self.soundcloud_downloader.download_track(
                                            track_url,
                                            self.soundcloud_audio_format,
                                            self.soundcloud_audio_quality
                                        )
                                        if track_result.get('success'):
                                            tracks[i]['track_download'] = track_result
                                            logger.info(f"Track downloaded successfully: {track_result.get('file_path')}")
                                        else:
                                            logger.warning(f"Failed to download track: {track_result.get('error')}")

                                    # Télécharger l'artwork
                                    if self.download_soundcloud_artwork:
                                        logger.info(f"Downloading artwork for track: {track.get('title')}")
                                        artwork_result = self.soundcloud_downloader.download_artwork(track_url)
                                        if artwork_result.get('success'):
                                            tracks[i]['artwork_download'] = artwork_result
                                            logger.info(f"Artwork downloaded successfully: {artwork_result.get('file_path')}")
                                        else:
                                            logger.warning(f"Failed to download artwork: {artwork_result.get('error')}")

                    # Utiliser notre MediaDownloader pour extraire d'autres médias
                    media_files = self.media_downloader.find_and_download_media(content, url)
                    result['media'] = media_files

                    return result

                except Exception as e:
                    logger.warning(f"Error handling SoundCloud content: {str(e)}")
                    return result

            # Rest of the method for other content
            # Utiliser l'option ignore_https_errors=True lors de la navigation
            self.page.goto(url, wait_until='networkidle', timeout=60000)
            content = self.page.content()

            # Utiliser notre MediaDownloader modifié avec SSL vérifié désactivé
            if 'youtube.com' not in url:
                media_files = self.media_downloader.find_and_download_media(content, url)
                result['media'] = media_files

            if selectors:
                for key, selector in selectors.items():
                    try:
                        elements = self.page.query_selector_all(selector)
                        if elements:
                            texts = [elem.text_content().strip() for elem in elements if elem.text_content().strip()]
                            if texts:
                                result['data'][key] = texts[0] if len(texts) == 1 else texts
                    except Exception as e:
                        logger.warning(f"Error extracting {key} with selector {selector}: {str(e)}")

            return result

        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            raise

    def close(self):
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

class MediaDownloader:
    def __init__(self, config):
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
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _setup_folders(self):
        # Create main media folder
        os.makedirs(self.media_folder, exist_ok=True)
        # Create subfolders for different media types
        os.makedirs(os.path.join(self.media_folder, 'images'), exist_ok=True)
        os.makedirs(os.path.join(self.media_folder, 'videos'), exist_ok=True)

    def _get_extension(self, url, content_type=None):
        # Try to get extension from URL first
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        if ext and self._is_valid_extension(ext):
            return ext

        # Try to get extension from content-type
        if content_type:
            ext = mimetypes.guess_extension(content_type)
            if ext and self._is_valid_extension(ext):
                return ext

        return None

    def _is_valid_extension(self, ext):
        if not ext.startswith('.'):
            ext = '.' + ext
        return (ext in self.media_types.get('images', []) or
                ext in self.media_types.get('videos', []))

    def _get_media_type(self, ext):
        if not ext.startswith('.'):
            ext = '.' + ext
        if ext in self.media_types.get('images', []):
            return 'images'
        if ext in self.media_types.get('videos', []):
            return 'videos'
        return None

    def download_media(self, url, page_url):
        if not self.storage_config.get('download_media', True):
            return None

        try:
            absolute_url = urljoin(page_url, url)

            # Assurez-vous que verify=False est utilisé pour cette requête
            response = self.session.get(absolute_url, stream=True, verify=False)

            if response.status_code != 200:
                return None

            # Check content length
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > self.max_file_size:
                return None

            # Get file extension
            content_type = response.headers.get('content-type', '')
            ext = self._get_extension(url, content_type)
            if not ext:
                return None

            # Determine media type and subfolder
            media_type = self._get_media_type(ext)
            if not media_type:
                return None

            # Download content in chunks
            content = b''
            for chunk in response.iter_content(chunk_size=8192):
                content += chunk
                if len(content) > self.max_file_size:
                    return None

            # Generate unique filename
            file_hash = hashlib.md5(content).hexdigest()[:10]
            filename = f"{file_hash}{ext}"
            filepath = os.path.join(self.media_folder, media_type, filename)

            # Save file
            with open(filepath, 'wb') as f:
                f.write(content)

            return {
                'original_url': url,
                'local_path': filepath,
                'media_type': media_type,
                'size': len(content),
                'filename': filename
            }

        except Exception as e:
            logger.error(f"Error downloading media from {url}: {str(e)}")
            return None

    def find_and_download_media(self, html_content, page_url):
        media_files = {
            'images': [],
            'videos': []
        }

        # Find all image tags
        img_tags = re.findall(r'<img[^>]+src=["\'](.*?)["\']', html_content)
        # Find all video tags
        video_tags = re.findall(r'<video[^>]*>.*?<source[^>]+src=["\'](.*?)["\']', html_content, re.DOTALL)
        video_tags += re.findall(r'<video[^>]+src=["\'](.*?)["\']', html_content)

        # Download images
        for img_url in img_tags:
            result = self.download_media(img_url, page_url)
            if result:
                media_files['images'].append(result)

        # Download videos
        for video_url in video_tags:
            result = self.download_media(video_url, page_url)
            if result:
                media_files['videos'].append(result)

        return media_files