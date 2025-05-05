import os
import yaml
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self, config_path='config.yaml'):
        self.config_path = config_path
        self.config = self._load_config()
        
    def _load_config(self):
        with open(self.config_path, 'r') as file:
            config = yaml.safe_load(file)
        return config
    
    def get_user_agent(self):
        return self.config.get('user_agent', 'Mozilla/5.0')
    
    def get_request_timeout(self):
        return self.config.get('request_timeout', 30)
    
    def get_delay_between_requests(self):
        return self.config.get('delay_between_requests', 1)
    
    def get_max_retries(self):
        return self.config.get('max_retries', 3)
    
    def get_storage_type(self):
        return self.config.get('storage', {}).get('type', 'csv')
    
    def get_storage_path(self):
        return self.config.get('storage', {}).get('path', 'scraped_data.csv')
    
    def get_database_config(self):
        return self.config.get('database', {})
    
    def get_site_config(self, site_name):
        sites = self.config.get('sites', {})
        return sites.get(site_name, {})
    
    def get_proxy_settings(self):
        return self.config.get('proxy', {})
    
    def get_browser_config(self):
        return self.config.get('browser', {})