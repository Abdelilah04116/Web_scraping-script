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
        self.session.headers.update({'User-Agent': self.user_agent})
        
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=60))
    def scrape(self, url, selectors=None):
        try:
            self._sleep()
            response = self.session.get(url, timeout=self.timeout, proxies=self.proxies)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'lxml')
            
            if selectors is None:
                return soup
                
            result = {}
            for key, selector in selectors.items():
                elements = soup.select(selector)
                if elements:
                    result[key] = [elem.get_text().strip() for elem in elements]
                else:
                    result[key] = []
                    
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
        self.driver = self._setup_driver()
        
    def _setup_driver(self):
        browser_config = self.config.get_browser_config()
        chrome_options = Options()
        
        if browser_config.get("headless", True):
            chrome_options.add_argument("--headless")
            
        chrome_options.add_argument(f"user-agent={self.user_agent}")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        
        if not browser_config.get("load_images", False):
            chrome_options.add_argument("--blink-settings=imagesEnabled=false")
            
        window_size = browser_config.get("window_size", "1920,1080")
        chrome_options.add_argument(f"--window-size={window_size}")
        
        proxy_settings = self.config.get_proxy_settings()
        if proxy_settings.get('enabled', False) and proxy_settings.get('host') and proxy_settings.get('port'):
            proxy_url = f"{proxy_settings.get('host')}:{proxy_settings.get('port')}"
            chrome_options.add_argument(f"--proxy-server={proxy_url}")
            
        executable_path = browser_config.get("executable_path", "")
        if executable_path:
            service = Service(executable_path=executable_path)
        else:
            service = Service(ChromeDriverManager().install())
            
        return webdriver.Chrome(service=service, options=chrome_options)
        
    def scrape(self, url, selectors=None, wait_time=5):
        try:
            self._sleep()
            self.driver.get(url)
            time.sleep(wait_time)  # Wait for JavaScript to load
            
            if selectors is None:
                return self.driver.page_source
                
            result = {}
            for key, selector in selectors.items():
                elements = self.driver.find_elements("css selector", selector)
                if elements:
                    result[key] = [elem.text.strip() for elem in elements]
                else:
                    result[key] = []
                    
            return result
            
        except Exception as e:
            logger.error(f"Error scraping {url} with Selenium: {str(e)}")
            raise
            
    def close(self):
        if self.driver:
            self.driver.quit()

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
        
    def _setup_browser(self):
        browser_config = self.config.get_browser_config()
        
        self.playwright = sync_playwright().start()
        browser_type = self.playwright.chromium
        
        launch_options = {
            'headless': browser_config.get("headless", True),
            'args': [
                '--no-sandbox',
                '--disable-extensions',
                '--disable-gpu'
            ]
        }
        
        self.browser = browser_type.launch(**launch_options)
        
        context_options = {
            'user_agent': self.user_agent,
            'viewport': {'width': 1920, 'height': 1080}
        }
        
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
        
    def scrape(self, url, selectors=None, wait_time=5):
        if not self.playwright:
            self._setup_browser()
            
        time.sleep(self._add_jitter(self.delay))
        
        try:
            self.page.goto(url, timeout=self.timeout * 1000, wait_until='networkidle')
            self.page.wait_for_timeout(wait_time * 1000)
            
            if selectors is None:
                return self.page.content()
                
            result = {}
            for key, selector in selectors.items():
                elements = self.page.query_selector_all(selector)
                if elements:
                    result[key] = [elem.text_content().strip() for elem in elements]
                else:
                    result[key] = []
                    
            return result
            
        except Exception as e:
            logger.error(f"Error scraping {url} with Playwright: {str(e)}")
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