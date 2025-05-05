import re
import json
from bs4 import BeautifulSoup
from loguru import logger

class Parser:
    def __init__(self, config=None):
        self.config = config
        
    def parse_html(self, html_content, selectors=None):
        """
        Parse HTML content using BeautifulSoup
        
        Args:
            html_content (str): HTML content to parse
            selectors (dict): Dictionary of CSS selectors
            
        Returns:
            dict: Parsed data
        """
        if not html_content:
            return {}
            
        soup = BeautifulSoup(html_content, 'lxml')
        
        if not selectors:
            return {"text": soup.get_text()}
            
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
    
    def extract_text(self, html_content):
        """
        Extract all text from HTML content
        
        Args:
            html_content (str): HTML content
            
        Returns:
            str: Extracted text
        """
        soup = BeautifulSoup(html_content, 'lxml')
        return soup.get_text(separator=' ', strip=True)
    
    def extract_links(self, html_content, base_url=None):
        """
        Extract all links from HTML content
        
        Args:
            html_content (str): HTML content
            base_url (str): Base URL to resolve relative URLs
            
        Returns:
            list: List of links
        """
        soup = BeautifulSoup(html_content, 'lxml')
        links = []
        
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            
            # Skip JavaScript links
            if href.startswith('javascript:'):
                continue
                
            # Resolve relative URLs if base_url is provided
            if base_url and not (href.startswith('http://') or href.startswith('https://')):
                if href.startswith('/'):
                    href = f"{base_url}{href}"
                else:
                    href = f"{base_url}/{href}"
                    
            links.append({
                'url': href,
                'text': a_tag.get_text().strip()
            })
            
        return links
    
    def extract_tables(self, html_content):
        """
        Extract all tables from HTML content
        
        Args:
            html_content (str): HTML content
            
        Returns:
            list: List of tables as lists of rows
        """
        soup = BeautifulSoup(html_content, 'lxml')
        tables = []
        
        for table in soup.find_all('table'):
            rows = []
            
            # Extract headers
            headers = []
            for th in table.find_all('th'):
                headers.append(th.get_text().strip())
                
            if headers:
                rows.append(headers)
                
            # Extract rows
            for tr in table.find_all('tr'):
                cells = []
                for td in tr.find_all(['td']):
                    cells.append(td.get_text().strip())
                
                if cells:
                    rows.append(cells)
                    
            tables.append(rows)
            
        return tables
    
    def extract_images(self, html_content, base_url=None):
        """
        Extract all images from HTML content
        
        Args:
            html_content (str): HTML content
            base_url (str): Base URL to resolve relative URLs
            
        Returns:
            list: List of image URLs
        """
        soup = BeautifulSoup(html_content, 'lxml')
        images = []
        
        for img in soup.find_all('img', src=True):
            src = img['src']
            
            # Resolve relative URLs if base_url is provided
            if base_url and not (src.startswith('http://') or src.startswith('https://')):
                if src.startswith('/'):
                    src = f"{base_url}{src}"
                else:
                    src = f"{base_url}/{src}"
                    
            alt = img.get('alt', '')
            
            images.append({
                'url': src,
                'alt': alt
            })
            
        return images
    
    def extract_metadata(self, html_content):
        """
        Extract metadata from HTML content
        
        Args:
            html_content (str): HTML content
            
        Returns:
            dict: Metadata
        """
        soup = BeautifulSoup(html_content, 'lxml')
        metadata = {}
        
        # Extract title
        title_tag = soup.find('title')
        if title_tag:
            metadata['title'] = title_tag.get_text().strip()
            
        # Extract meta tags
        for meta in soup.find_all('meta'):
            name = meta.get('name', meta.get('property', ''))
            content = meta.get('content', '')
            
            if name and content:
                metadata[name] = content
                
        return metadata
    
    def extract_json_ld(self, html_content):
        """
        Extract JSON-LD data from HTML content
        
        Args:
            html_content (str): HTML content
            
        Returns:
            list: List of JSON-LD objects
        """
        soup = BeautifulSoup(html_content, 'lxml')
        json_ld_data = []
        
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                json_ld_data.append(data)
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing JSON-LD: {e}")
                
        return json_ld_data
    
    def clean_text(self, text):
        """
        Clean text by removing extra whitespace
        
        Args:
            text (str): Text to clean
            
        Returns:
            str: Cleaned text
        """
        if not text:
            return ""
            
        # Replace multiple whitespace with a single space
        text = re.sub(r'\s+', ' ', text)
        
        # Remove leading/trailing whitespace
        return text.strip()
    
    def extract_by_regex(self, text, pattern):
        """
        Extract data using a regex pattern
        
        Args:
            text (str): Text to search in
            pattern (str): Regex pattern
            
        Returns:
            list: List of matches
        """
        return re.findall(pattern, text)