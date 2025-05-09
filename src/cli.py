#!/usr/bin/env python3
import os
import sys
import argparse
import yaml
import json
import time
from typing import List, Dict, Any, Optional
from loguru import logger
from tqdm import tqdm
from urllib.parse import urlparse

from config import Config
from scraper import ScraperFactory
from parser import Parser
from storage import StorageFactory
from youtube_downloader import YouTubeDownloader
from media_downloader import MediaDownloader

def setup_logger():
    """Configure logger with rotation and level"""
    logger.remove()  # Remove default handler
    logger.add(
        "scraper.log",
        rotation="10 MB",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}"
    )
    logger.add(sys.stderr, level="INFO", format="{level} | {message}")

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Web Scraper CLI - Extract content from websites",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    # Input options
    input_group = parser.add_argument_group("Input Options")
    input_group.add_argument("--url", "-u", help="Single URL to scrape")
    input_group.add_argument("--urls-file", "-f", help="File containing URLs to scrape (one per line)")
    input_group.add_argument("--pipeline", "-p", default="pipeline.yaml", help="Pipeline YAML file")
    
    # Scraper options
    scraper_group = parser.add_argument_group("Scraper Options")
    scraper_group.add_argument(
        "--mode", "-m",
        choices=["simple", "selenium", "scrapy", "pyppeteer", "playwright"],
        default="playwright",
        help="Scraper mode"
    )
    scraper_group.add_argument("--delay", "-d", type=float, default=2.0, help="Delay between requests in seconds")
    scraper_group.add_argument("--timeout", "-t", type=int, default=30, help="Request timeout in seconds")
    scraper_group.add_argument("--retries", "-r", type=int, default=3, help="Number of retries for failed requests")
    
    # Content options
    content_group = parser.add_argument_group("Content Options")
    content_group.add_argument("--extract-text", action="store_true", help="Extract text content")
    content_group.add_argument("--extract-images", action="store_true", help="Extract images")
    content_group.add_argument("--extract-videos", action="store_true", help="Extract videos")
    content_group.add_argument("--extract-youtube", action="store_true", help="Extract YouTube videos")
    content_group.add_argument("--extract-all", action="store_true", help="Extract all content types")
    
    # Output options
    output_group = parser.add_argument_group("Output Options")
    output_group.add_argument(
        "--output-format", "-o",
        choices=["json", "csv"],
        default="json",
        help="Output format"
    )
    output_group.add_argument("--output-file", default="scraped_data", help="Output file name (without extension)")
    output_group.add_argument("--pretty", action="store_true", help="Pretty print JSON output")
    
    return parser.parse_args()

def load_urls_from_file(file_path: str) -> List[str]:
    """Load URLs from a file (one per line)"""
    try:
        with open(file_path, 'r') as f:
            return [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
    except Exception as e:
        logger.error(f"Error loading URLs from {file_path}: {str(e)}")
        return []

def load_pipeline_config(file_path: str) -> Dict[str, Any]:
    """Load pipeline configuration from YAML file"""
    try:
        with open(file_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Error loading pipeline file {file_path}: {str(e)}")
        return {}

def create_pipeline_config(args) -> Dict[str, Any]:
    """Create pipeline configuration from command line arguments"""
    # Get URLs
    urls = []
    if args.url:
        urls.append(args.url)
    if args.urls_file:
        urls.extend(load_urls_from_file(args.urls_file))
    
    # Determine content types to extract
    extract_text = args.extract_text or args.extract_all
    extract_images = args.extract_images or args.extract_all
    extract_videos = args.extract_videos or args.extract_all
    extract_youtube = args.extract_youtube or args.extract_all
    
    # Create pipeline config
    pipeline_config = {
        "urls": urls,
        "scraper_mode": args.mode,
        "extract_text": extract_text,
        "extract_images": extract_images,
        "extract_videos": extract_videos,
        "extract_youtube": extract_youtube,
        "delay_between_requests": args.delay,
        "request_timeout": args.timeout,
        "max_retries": args.retries,
        "storage": {
            "type": args.output_format,
            "path": f"{args.output_file}.{args.output_format}"
        }
    }
    
    return pipeline_config

def process_url(url: str, config: Config, scraper_mode: str, extract_options: Dict[str, bool]) -> Optional[Dict[str, Any]]:
    """Process a single URL and extract content based on options"""
    try:
        # Initialize components
        scraper = ScraperFactory.get_scraper(scraper_mode, config)
        parser = Parser(config)
        media_downloader = MediaDownloader(config)
        
        # Check if it's a YouTube URL
        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        
        if is_youtube and extract_options.get('extract_youtube', False):
            # Process YouTube URL
            youtube_downloader = YouTubeDownloader(config)
            logger.info(f"Processing YouTube URL: {url}")
            
            # Get video info
            video_info = youtube_downloader.get_video_info_pytube(url)
            if not video_info:
                video_info = youtube_downloader.get_video_info_ytdlp(url)
                
            if not video_info:
                logger.error(f"Failed to extract information from YouTube URL: {url}")
                return None
                
            # Download thumbnail
            if extract_options.get('extract_images', False):
                thumbnail_result = youtube_downloader.download_thumbnail(url)
                if thumbnail_result.get('success'):
                    video_info['thumbnail'] = thumbnail_result
                    logger.info(f"Downloaded thumbnail: {thumbnail_result.get('file_path')}")
            
            # Download video if requested
            if extract_options.get('download_videos', False):
                download_result = youtube_downloader.download_video(url)
                if download_result.get('success'):
                    video_info['video_download'] = download_result
                    logger.info(f"Downloaded video: {download_result.get('file_path')}")
            
            return {
                'url': url,
                'timestamp': time.time(),
                'type': 'youtube',
                'data': video_info
            }
        else:
            # Process regular website
            logger.info(f"Scraping URL: {url}")
            html_content = scraper.scrape(url)
            
            if html_content is None:
                logger.error(f"Failed to get content from {url}")
                return None
                
            # Parse content
            parsed_data = {
                'url': url,
                'timestamp': time.time(),
                'type': 'website',
                'domain': urlparse(url).netloc
            }
            
            # Extract text content
            if extract_options.get('extract_text', False):
                if isinstance(html_content, str):
                    parsed_data['text'] = parser.extract_text(html_content)
                    parsed_data['metadata'] = parser.extract_metadata(html_content)
                elif isinstance(html_content, dict) and 'data' in html_content:
                    parsed_data.update(html_content)
            
            # Extract media content
            if extract_options.get('extract_images', False) or extract_options.get('extract_videos', False):
                if isinstance(html_content, str):
                    media_files = media_downloader.find_and_download_media(html_content, url)
                    parsed_data['media'] = media_files
                    
                    # Log media extraction results
                    images_count = len(media_files.get('images', []))
                    videos_count = len(media_files.get('videos', []))
                    audio_count = len(media_files.get('audio', []))
                    
                    if images_count > 0:
                        logger.info(f"Extracted {images_count} images from {url}")
                    if videos_count > 0:
                        logger.info(f"Extracted {videos_count} videos from {url}")
                    if audio_count > 0:
                        logger.info(f"Extracted {audio_count} audio files from {url}")
            
            # Close scraper
            scraper.close()
            
            return parsed_data
            
    except Exception as e:
        logger.error(f"Error processing URL {url}: {str(e)}")
        return None

def execute_pipeline(pipeline_config: Dict[str, Any]) -> bool:
    """Execute scraping pipeline based on configuration"""
    try:
        # Load config
        config_path = pipeline_config.get('config', 'config.yaml')
        config = Config(config_path)
        
        # Override config with pipeline settings
        if 'delay_between_requests' in pipeline_config:
            config.config['delay_between_requests'] = pipeline_config['delay_between_requests']
        if 'request_timeout' in pipeline_config:
            config.config['request_timeout'] = pipeline_config['request_timeout']
        if 'max_retries' in pipeline_config:
            config.config['max_retries'] = pipeline_config['max_retries']
        
        # Get URLs to scrape
        urls = pipeline_config.get('urls', [])
        if not urls:
            logger.error("No URLs specified in pipeline config")
            return False
            
        logger.info(f"Found {len(urls)} URLs to scrape")
        
        # Get scraper mode
        scraper_mode = pipeline_config.get('scraper_mode', config.config.get('default_mode', 'simple'))
        
        # Get extraction options
        extract_options = {
            'extract_text': pipeline_config.get('extract_text', True),
            'extract_images': pipeline_config.get('extract_images', False),
            'extract_videos': pipeline_config.get('extract_videos', False),
            'extract_youtube': pipeline_config.get('extract_youtube', False),
            'download_videos': pipeline_config.get('download_videos', False)
        }
        
        # Initialize storage
        storage = StorageFactory.get_storage(config)
        
        # Process URLs
        all_results = []
        for url in tqdm(urls, desc="Scraping URLs"):
            result = process_url(url, config, scraper_mode, extract_options)
            if result:
                all_results.append(result)
                storage.save(result)
                
            # Delay between requests
            time.sleep(config.get_delay_between_requests())
            
        logger.info(f"Scraped {len(all_results)} URLs successfully")
        
        # Close storage
        storage.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error executing pipeline: {str(e)}")
        return False

def main():
    """Main entry point for the CLI"""
    # Setup logger
    setup_logger()
    
    # Parse arguments
    args = parse_arguments()
    
    # Load or create pipeline config
    if args.url or args.urls_file:
        # Create pipeline config from arguments
        pipeline_config = create_pipeline_config(args)
    else:
        # Load pipeline config from file
        pipeline_config = load_pipeline_config(args.pipeline)
        
        # Override with command line arguments if specified
        if args.mode:
            pipeline_config['scraper_mode'] = args.mode
        if args.output_format:
            pipeline_config['storage'] = pipeline_config.get('storage', {})
            pipeline_config['storage']['type'] = args.output_format
        if args.output_file:
            pipeline_config['storage'] = pipeline_config.get('storage', {})
            pipeline_config['storage']['path'] = f"{args.output_file}.{args.output_format}"
    
    # Execute pipeline
    success = execute_pipeline(pipeline_config)
    
    if success:
        logger.info("Scraping completed successfully")
    else:
        logger.error("Scraping failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
