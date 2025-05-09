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
        # Use SSL verification setting from config
        verify_ssl = self.config.get_verify_ssl()
        self.session.verify = verify_ssl
        if not verify_ssl:
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
            
            # First make a GET request to get cookies
            response = self.session.get(
                url, 
                timeout=self.timeout,
                proxies=self.proxies,
                allow_redirects=True
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
        self.media_downloader = MediaDownloader(config)
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
                '--disable-site-isolation-trials'
            ]
        }
        
        self.browser = browser_type.launch(**launch_options)
        
        # Enhanced context options
        context_options = {
            'user_agent': self.user_agent,
            'viewport': {'width': 1920, 'height': 1080},
            'java_script_enabled': True,
            'bypass_csp': True,
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

    async def _wait_for_element_with_retry(self, selectors, timeout=15000, max_retries=3):
        """Wait for an element with multiple selector strategies and retries"""
        for attempt in range(max_retries):
            for selector in (selectors if isinstance(selectors, list) else [selectors]):
                try:
                    element = self.page.wait_for_selector(selector, timeout=timeout)
                    if element:
                        logger.info(f"Successfully loaded element with selector: {selector}")
                        return element
                except Exception as e:
                    logger.debug(f"Attempt {attempt + 1}/{max_retries} failed for selector {selector}: {str(e)}")
                    continue
            # Increase timeout for next retry
            timeout = int(timeout * 1.5)
        return None

    def _wait_for_youtube_content(self):
        """Wait for YouTube content to load with improved selector strategies"""
        try:
            # Basic page load states
            self.page.wait_for_load_state('domcontentloaded', timeout=30000)
            self.page.wait_for_load_state('networkidle', timeout=30000)
            
            if '/watch?' in self.page.url:
                # Multiple selector strategies for each element
                elements_to_wait = {
                    'container': ['ytd-watch-flexy', '#watch7-content'],
                    'title': [
                        'h1.ytd-video-primary-info-renderer',
                        '#container > h1',
                        'h1.title'
                    ],
                    'player': ['#movie_player', '#player'],
                    'info': [
                        'ytd-video-primary-info-renderer',
                        '#info-contents',
                        '#watch-header'
                    ]
                }
                
                elements_found = {}
                for element_type, selectors in elements_to_wait.items():
                    try:
                        # Try each selector strategy
                        element = self.page.evaluate("""(selectors) => {
                            for (const selector of selectors) {
                                const element = document.querySelector(selector);
                                if (element) return true;
                            }
                            return false;
                        }""", selectors)
                        
                        elements_found[element_type] = element
                        if element:
                            logger.info(f"Found {element_type} element using alternative selectors")
                        else:
                            logger.warning(f"Failed to find {element_type} element with any selector")
                    except Exception as e:
                        logger.warning(f"Error checking {element_type} element: {str(e)}")
                        elements_found[element_type] = False
                
                # Consider the page loaded if we found at least the container and player
                return elements_found.get('container', False) and elements_found.get('player', False)
            else:
                # For channel/playlist pages
                try:
                    found_manager = self.page.wait_for_selector("ytd-page-manager", timeout=30000) is not None
                    found_grid = self.page.wait_for_selector("ytd-rich-grid-renderer", timeout=30000) is not None
                    return found_manager or found_grid
                except Exception as e:
                    logger.warning(f"Failed to load channel/playlist elements: {str(e)}")
                    return False
                    
        except Exception as e:
            logger.warning(f"Error in YouTube content loading: {str(e)}")
            return False

    def _get_youtube_thumbnail(self, video_id):
        """Get YouTube video thumbnail URLs"""
        return {
            'maxres': f'https://img.youtube.com/vi/{video_id}/maxresdefault.jpg',
            'hq': f'https://img.youtube.com/vi/{video_id}/hqdefault.jpg',
            'mq': f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg',
            'sd': f'https://img.youtube.com/vi/{video_id}/sddefault.jpg',
            'default': f'https://img.youtube.com/vi/{video_id}/default.jpg'
        }

    def _extract_youtube_video_details(self):
        """Extract details for a single YouTube video page with improved selectors"""
        try:
            return self.page.evaluate("""() => {
                const data = {};
                
                // Helper function to safely get text content with retry
                const getText = (selectors, maxAttempts = 3) => {
                    for (let attempt = 0; attempt < maxAttempts; attempt++) {
                        for (const selector of selectors) {
                            const el = document.querySelector(selector);
                            if (el) {
                                const text = el.textContent.trim();
                                if (text) return text;
                            }
                        }
                    }
                    return null;
                };
                
                // Get video title - enhanced selectors
                data.title = getText([
                    '#title h1.ytd-video-primary-info-renderer',
                    '#above-the-fold #title',
                    'h1.title',
                    '#container h1.style-scope.ytd-watch-metadata'
                ]);
                
                // Get video description - enhanced selectors
                data.description = getText([
                    '#description-inline-expander .content',
                    '#description ytd-expandable-video-description-body-renderer',
                    '#description > yt-formatted-string',
                    '#description-inline-expander > yt-attributed-string'
                ]);
                
                // Get channel info - enhanced selectors
                const channelSelectors = [
                    '#owner #channel-name a',
                    '#top-row ytd-channel-name a',
                    '#upload-info ytd-channel-name'
                ];
                
                for (const selector of channelSelectors) {
                    const channelEl = document.querySelector(selector);
                    if (channelEl) {
                        data.channel = {
                            name: channelEl.textContent.trim(),
                            url: channelEl.href
                        };
                        break;
                    }
                }
                
                // Get view count - enhanced selectors
                data.views = getText([
                    '#view-count .view-count',
                    'ytd-video-view-count-renderer',
                    '#count .view-count',
                    '#info span.view-count'
                ]);
                
                // Get like count - enhanced selectors
                data.likes = getText([
                    '#top-level-buttons-computed ytd-toggle-button-renderer:first-child #text',
                    'ytd-menu-renderer ytd-toggle-button-renderer:first-child #text',
                    '#menu-container like-button-view-model #button'
                ]);
                
                // Get upload date - enhanced selectors
                data.uploadDate = getText([
                    '#info-strings yt-formatted-string',
                    '#upload-info .style-scope.ytd-video-primary-info-renderer',
                    '#metadata-line span:last-child'
                ]);
                
                // Get duration - enhanced selectors
                data.duration = getText([
                    '.ytp-time-duration',
                    '.video-time',
                    'span.ytd-thumbnail-overlay-time-status-renderer'
                ]);
                
                return data;
            }""")
        except Exception as e:
            logger.warning(f"Error extracting video details: {str(e)}")
            return {}

    def _extract_youtube_videos(self):
        """Extract video data from YouTube page"""
        try:
            # If this is a video page, get detailed info
            if '/watch?' in self.page.url:
                video_data = self._extract_youtube_video_details()
                video_data['url'] = self.page.url
                video_data['id'] = self.page.url.split('v=')[1].split('&')[0] if 'v=' in self.page.url else None
                return [video_data]
                
            # For channel/playlist pages
            return self.page.evaluate("""() => {
                function wait(ms) {
                    return new Promise(resolve => setTimeout(resolve, ms));
                }
                
                return new Promise(async (resolve) => {
                    await wait(2000);
                    
                    const videos = [];
                    const items = document.querySelectorAll('ytd-video-renderer, ytd-rich-item-renderer');
                    
                    for (const item of items) {
                        try {
                            const titleEl = item.querySelector('a#video-title');
                            if (!titleEl) continue;
                            
                            const video = {
                                title: titleEl.title || titleEl.textContent.trim(),
                                url: titleEl.href,
                                id: titleEl.href.split('v=')[1]?.split('&')[0]
                            };
                            
                            // Try to get thumbnail
                            const thumbnailEl = item.querySelector('img#img');
                            if (thumbnailEl) {
                                video.thumbnail = thumbnailEl.src;
                            }
                            
                            // Try to get duration
                            const durationEl = item.querySelector('span.ytd-thumbnail-overlay-time-status-renderer');
                            if (durationEl) {
                                video.duration = durationEl.textContent.trim();
                            }
                            
                            // Try to get view count
                            const viewsEl = item.querySelector('span.ytd-video-meta-block');
                            if (viewsEl) {
                                video.views = viewsEl.textContent.trim();
                            }
                            
                            if (video.title && video.url) {
                                videos.push(video);
                            }
                        } catch (e) {
                            console.warn('Error extracting video:', e);
                        }
                    }
                    
                    resolve(videos);
                });
            }""")
        except Exception as e:
            logger.warning(f"Error extracting YouTube videos: {str(e)}")
            return []

    def scrape(self, url, selectors=None, wait_time=5):
        try:
            time.sleep(self._add_jitter(self.delay))
            
            result = {
                'url': url,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
                'data': {}
            }
            
            if 'youtube.com' in url:
                try:
                    # Initial page load with increased timeout
                    self.page.goto(url, timeout=60000, wait_until='domcontentloaded')
                    
                    # Wait for initial render
                    time.sleep(3)
                    
                    # Scroll to ensure content loads
                    self.page.evaluate("""() => {
                        window.scrollBy(0, 200);
                        return new Promise(resolve => setTimeout(resolve, 1000));
                    }""")
                    
                    # Wait for content with new progressive strategy
                    content_loaded = self._wait_for_youtube_content()
                    
                    # Additional wait after content load
                    time.sleep(2)
                    
                    if content_loaded:
                        videos = self._extract_youtube_videos()
                        if (videos):
                            result['data']['videos'] = videos
                            
                            # Try to get thumbnails for video
                            if '/watch?' in url and videos[0].get('id'):
                                thumbnails = self._get_youtube_thumbnail(videos[0]['id'])
                                videos[0]['thumbnails'] = thumbnails
                                
                            logger.info(f"Successfully extracted {len(videos)} videos with details")
                        else:
                            logger.warning("No videos extracted from YouTube page")
                    else:
                        logger.warning("Failed to load all YouTube elements but continuing with extraction")
                        # Try extraction anyway in case we got partial content
                        videos = self._extract_youtube_videos()
                        if videos:
                            result['data']['videos'] = videos
                            logger.info(f"Extracted {len(videos)} videos despite loading issues")
                    
                    return result
                    
                except Exception as e:
                    logger.warning(f"Error handling YouTube content: {str(e)}")
                    return result
                    
            # Rest of the method for non-YouTube content
            self.page.goto(url, wait_until='networkidle')
            content = self.page.content()
            
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
        self.session = requests.Session()
        
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
            response = self.session.get(absolute_url, stream=True)
            
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