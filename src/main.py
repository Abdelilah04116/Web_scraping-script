import os
import argparse
import yaml
import json
from loguru import logger
from tqdm import tqdm
import time

from config import Config
from scraper import ScraperFactory
from parser import Parser
from storage import StorageFactory

def load_pipeline(pipeline_file):
    """
    Load pipeline configuration from YAML file
    
    Args:
        pipeline_file (str): Path to pipeline YAML file
        
    Returns:
        dict: Pipeline configuration
    """
    try:
        with open(pipeline_file, 'r') as file:
            return yaml.safe_load(file)
    except Exception as e:
        logger.error(f"Error loading pipeline file {pipeline_file}: {str(e)}")
        return {}

def execute_pipeline(pipeline_config):
    """
    Execute scraping pipeline
    
    Args:
        pipeline_config (dict): Pipeline configuration
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Load config
        config_path = pipeline_config.get('config', 'config.yaml')
        config = Config(config_path)
        
        # Initialize components
        scraper_mode = pipeline_config.get('scraper_mode', config.config.get('default_mode', 'simple'))
        scraper = ScraperFactory.get_scraper(scraper_mode, config)
        parser = Parser(config)
        storage = StorageFactory.get_storage(config)
        
        logger.info(f"Initialized pipeline with scraper mode: {scraper_mode}")
        
        # Get URLs to scrape
        urls = pipeline_config.get('urls', [])
        site_name = pipeline_config.get('site_name')
        
        if site_name:
            site_config = config.get_site_config(site_name)
            site_urls = site_config.get('urls', [])
            if site_urls:
                urls.extend(site_urls)
                
        if not urls:
            logger.error("No URLs specified in pipeline or site config")
            return False
            
        logger.info(f"Found {len(urls)} URLs to scrape")
        
        # Get selectors
        selectors = pipeline_config.get('selectors', {})
        if not selectors and site_name:
            selectors = config.get_site_config(site_name).get('selectors', {})
            
        # Execute scraping
        all_results = []
        
        for url in tqdm(urls, desc="Scraping URLs"):
            try:
                logger.info(f"Scraping: {url}")
                
                # Scrape URL
                html_content = scraper.scrape(url)
                
                if not html_content:
                    logger.warning(f"Failed to get content from {url}")
                    continue
                    
                # Parse HTML
                if isinstance(html_content, dict):
                    # If scraper already returned parsed data
                    parsed_data = html_content
                else:
                    # Parse HTML with selectors
                    parsed_data = parser.parse_html(html_content, selectors)
                    
                # Add metadata
                parsed_data['url'] = url
                parsed_data['timestamp'] = time.time()
                parsed_data['site_name'] = site_name
                
                # Extract additional data if specified
                if pipeline_config.get('extract_links', False):
                    parsed_data['links'] = parser.extract_links(html_content, url)
                    
                if pipeline_config.get('extract_images', False):
                    parsed_data['images'] = parser.extract_images(html_content, url)
                    
                if pipeline_config.get('extract_metadata', False):
                    parsed_data['page_metadata'] = parser.extract_metadata(html_content)
                    
                # Save data
                storage.save(parsed_data)
                
                # Add to results
                all_results.append(parsed_data)
                
                # Delay between requests
                time.sleep(config.get_delay_between_requests())
                
            except Exception as e:
                logger.error(f"Error processing URL {url}: {str(e)}")
                
        logger.info(f"Scraped {len(all_results)} URLs successfully")
        
        # Execute post-processing if specified
        if pipeline_config.get('post_processing'):
            post_process(all_results, pipeline_config['post_processing'])
            
        # Close resources
        scraper.close()
        storage.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error executing pipeline: {str(e)}")
        return False

def post_process(data, post_processing_config):
    """
    Execute post-processing on scraped data
    
    Args:
        data (list): List of scraped data
        post_processing_config (dict): Post-processing configuration
        
    Returns:
        list: Processed data
    """
    try:
        # Convert to pandas DataFrame for easier processing
        import pandas as pd
        
        df = pd.DataFrame(data)
        
        # Execute specified operations
        operations = post_processing_config.get('operations', [])
        
        for operation in operations:
            op_type = operation.get('type')
            
            if op_type == 'filter':
                column = operation.get('column')
                value = operation.get('value')
                condition = operation.get('condition', 'equals')
                
                if column and column in df.columns:
                    if condition == 'equals':
                        df = df[df[column] == value]
                    elif condition == 'contains':
                        df = df[df[column].astype(str).str.contains(value)]
                    elif condition == 'greater_than':
                        df = df[df[column] > value]
                    elif condition == 'less_than':
                        df = df[df[column] < value]
                        
            elif op_type == 'sort':
                column = operation.get('column')
                ascending = operation.get('ascending', True)
                
                if column and column in df.columns:
                    df = df.sort_values(by=column, ascending=ascending)
                    
            elif op_type == 'deduplicate':
                columns = operation.get('columns', [])
                
                if columns:
                    df = df.drop_duplicates(subset=columns)
                else:
                    df = df.drop_duplicates()
                    
        # Export results if specified
        export = post_processing_config.get('export')
        if export:
            export_format = export.get('format', 'csv')
            export_path = export.get('path', 'processed_data')
            
            if export_format == 'csv':
                df.to_csv(f"{export_path}.csv", index=False)
            elif export_format == 'json':
                df.to_json(f"{export_path}.json", orient='records')
            elif export_format == 'excel':
                df.to_excel(f"{export_path}.xlsx", index=False)
                
        return df.to_dict('records')
        
    except Exception as e:
        logger.error(f"Error in post-processing: {str(e)}")
        return data

def main():
    # Configure logger
    logger.add("scraper.log", rotation="10 MB", level="INFO")
    
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description="Web Scraper")
    parser.add_argument("--pipeline", "-p", default="pipeline.yaml", help="Pipeline YAML file")
    parser.add_argument("--url", "-u", help="Single URL to scrape")
    parser.add_argument("--output", "-o", default="scraped_data.csv", help="Output file")
    parser.add_argument("--mode", "-m", default="simple", help="Scraper mode (simple, selenium, scrapy, pyppeteer, playwright)")
    args = parser.parse_args()
    
    # If single URL specified, create simple pipeline
    if args.url:
        pipeline_config = {
            "urls": [args.url],
            "scraper_mode": args.mode,
            "storage": {
                "type": "csv",
                "path": args.output
            }
        }
    else:
        # Load pipeline from file
        pipeline_config = load_pipeline(args.pipeline)
        
    # Execute pipeline
    success = execute_pipeline(pipeline_config)
    
    if success:
        logger.info("Scraping completed successfully")
    else:
        logger.error("Scraping failed")

if __name__ == "__main__":
    main()