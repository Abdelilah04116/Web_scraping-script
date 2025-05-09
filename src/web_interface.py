import streamlit as st
import yaml
import json
import os
import re
import time
import base64
from datetime import datetime
from loguru import logger
from PIL import Image
import io
import pandas as pd
from urllib.parse import urlparse

from config import Config
from scraper import ScraperFactory
from parser import Parser
from storage import StorageFactory
from youtube_downloader import YouTubeDownloader

# Set page configuration
st.set_page_config(
    page_title="Web Scraper Dashboard",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        color: #1E88E5;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        color: #0D47A1;
        margin-bottom: 1rem;
    }
    .card {
        border-radius: 5px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        background-color: #f8f9fa;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    }
    .success-text {
        color: #4CAF50;
        font-weight: bold;
    }
    .error-text {
        color: #F44336;
        font-weight: bold;
    }
    .info-text {
        color: #2196F3;
        font-weight: bold;
    }
    .image-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: 10px;
        padding: 10px;
    }
    .image-grid img {
        max-width: 100%;
        height: auto;
        border-radius: 5px;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .stButton button {
        background-color: #1E88E5;
        color: white;
        font-weight: bold;
    }
    .stTextInput input {
        border-radius: 5px;
    }
    .stSelectbox select {
        border-radius: 5px;
    }
</style>
""", unsafe_allow_html=True)

# Title and description
st.markdown('<h1 class="main-header">🌐 Web Scraper Dashboard</h1>', unsafe_allow_html=True)
st.markdown('<div class="card">Configure and run web scraping tasks to extract content from websites. The tool supports scraping of text, images, and videos (including YouTube).</div>', unsafe_allow_html=True)

# Initialize session state
if 'scraping_results' not in st.session_state:
    st.session_state.scraping_results = []
if 'downloaded_media' not in st.session_state:
    st.session_state.downloaded_media = {'images': [], 'videos': []}
if 'current_tab' not in st.session_state:
    st.session_state.current_tab = "URL Input"

# Sidebar for configuration
st.sidebar.markdown('<h2 class="sub-header">Configuration</h2>', unsafe_allow_html=True)

# Tabs for different input methods
tabs = ["URL Input", "Batch URLs", "Pipeline Config"]
st.sidebar.markdown('<div class="sub-header">Input Method</div>', unsafe_allow_html=True)
selected_tab = st.sidebar.radio("", tabs, index=tabs.index(st.session_state.current_tab))
st.session_state.current_tab = selected_tab

# Scraper configuration
st.sidebar.markdown('<div class="sub-header">Scraper Settings</div>', unsafe_allow_html=True)
scraper_mode = st.sidebar.selectbox(
    "Scraper Mode",
    ["simple", "selenium", "scrapy", "pyppeteer", "playwright"],
    index=4  # Default to 'playwright'
)

# Content types to extract
st.sidebar.markdown('<div class="sub-header">Content Types</div>', unsafe_allow_html=True)
extract_text = st.sidebar.checkbox("Extract Text", value=True)
extract_images = st.sidebar.checkbox("Extract Images", value=True)
extract_videos = st.sidebar.checkbox("Extract Videos", value=True)
extract_youtube = st.sidebar.checkbox("Extract YouTube Videos", value=True)

# Output configuration
st.sidebar.markdown('<div class="sub-header">Output Settings</div>', unsafe_allow_html=True)
output_format = st.sidebar.selectbox(
    "Output Format",
    ["JSON", "CSV"],
    index=0
)
output_file = st.sidebar.text_input(
    "Output File",
    value=f"scraped_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
)

# Main content area
if selected_tab == "URL Input":
    st.markdown('<h2 class="sub-header">Single URL Scraping</h2>', unsafe_allow_html=True)
    
    # URL input
    url_input = st.text_input("Enter URL to scrape", placeholder="https://example.com")
    
    # CSS selectors (optional)
    with st.expander("Advanced: CSS Selectors (Optional)"):
        st.markdown("Specify CSS selectors to extract specific content. Leave empty to extract all content.")
        title_selector = st.text_input("Title Selector", placeholder="h1.title")
        content_selector = st.text_input("Content Selector", placeholder="div.content")
        image_selector = st.text_input("Image Selector", placeholder="img.main-image")
    
    # Start scraping button
    if st.button("Start Scraping", key="single_url_scrape"):
        if not url_input:
            st.error("Please enter a URL to scrape")
        elif not re.match(r'^https?://[^\s/$.?#].[^\s]*$', url_input):
            st.error("Invalid URL format. Please enter a valid URL starting with http:// or https://")
        else:
            # Create selectors dict if provided
            selectors = {}
            if title_selector:
                selectors['title'] = title_selector
            if content_selector:
                selectors['content'] = content_selector
            if image_selector:
                selectors['image'] = image_selector
                
            # Create pipeline config
            pipeline_config = {
                "urls": [url_input],
                "scraper_mode": scraper_mode,
                "selectors": selectors,
                "extract_text": extract_text,
                "extract_images": extract_images,
                "extract_videos": extract_videos,
                "extract_youtube": extract_youtube,
                "storage": {
                    "type": "json" if output_format == "JSON" else "csv",
                    "path": f"{output_file}.{output_format.lower()}"
                }
            }
            
            # Run scraping
            with st.spinner("Scraping in progress..."):
                try:
                    # Initialize components
                    config = Config("config.yaml")
                    scraper = ScraperFactory.get_scraper(scraper_mode, config)
                    parser = Parser(config)
                    storage = StorageFactory.get_storage(config)
                    
                    if extract_youtube and ('youtube.com' in url_input or 'youtu.be' in url_input):
                        youtube_downloader = YouTubeDownloader(config)
                        st.info("YouTube URL detected. Extracting video information...")
                        
                        # Get video info
                        video_info = youtube_downloader.get_video_info_pytube(url_input)
                        if not video_info:
                            video_info = youtube_downloader.get_video_info_ytdlp(url_input)
                            
                        if video_info:
                            st.success(f"Successfully extracted information for YouTube video: {video_info.get('title', 'Unknown')}")
                            
                            # Download thumbnail
                            thumbnail_result = youtube_downloader.download_thumbnail(url_input)
                            if thumbnail_result.get('success'):
                                st.success(f"Downloaded thumbnail: {thumbnail_result.get('file_path')}")
                                
                                # Display thumbnail
                                try:
                                    image = Image.open(thumbnail_result.get('file_path'))
                                    st.image(image, caption=f"Thumbnail for {video_info.get('title')}", width=400)
                                except Exception as e:
                                    st.warning(f"Could not display thumbnail: {str(e)}")
                            
                            # Ask if user wants to download the video
                            if st.button("Download Video"):
                                with st.spinner("Downloading video..."):
                                    download_result = youtube_downloader.download_video(url_input)
                                    if download_result.get('success'):
                                        st.success(f"Video downloaded successfully: {download_result.get('file_path')}")
                                    else:
                                        st.error(f"Failed to download video: {download_result.get('error')}")
                            
                            # Store results
                            st.session_state.scraping_results = [video_info]
                            storage.save(video_info)
                            
                        else:
                            st.error("Failed to extract YouTube video information")
                    else:
                        # Regular website scraping
                        html_content = scraper.scrape(url_input)
                        
                        if html_content is None:
                            st.error(f"Failed to get content from {url_input}")
                        else:
                            # Parse content
                            parsed_data = parser.parse_html(html_content, selectors)
                            parsed_data['url'] = url_input
                            parsed_data['timestamp'] = time.time()
                            
                            # Extract additional data if specified
                            if extract_images:
                                parsed_data['images'] = parser.extract_images(html_content, url_input)
                                
                                # Display images
                                if parsed_data['images']:
                                    st.success(f"Found {len(parsed_data['images'])} images")
                                    
                                    # Display first few images
                                    image_urls = [img['url'] for img in parsed_data['images'][:5]]
                                    st.markdown('<div class="sub-header">Sample Images</div>', unsafe_allow_html=True)
                                    st.markdown('<div class="image-grid">', unsafe_allow_html=True)
                                    for img_url in image_urls:
                                        st.markdown(f'<img src="{img_url}" alt="Scraped Image">', unsafe_allow_html=True)
                                    st.markdown('</div>', unsafe_allow_html=True)
                                    
                                    # Store for download
                                    st.session_state.downloaded_media['images'] = parsed_data['images']
                            
                            # Extract metadata
                            parsed_data['metadata'] = parser.extract_metadata(html_content)
                            
                            # Save data
                            storage.save(parsed_data)
                            
                            # Store results
                            st.session_state.scraping_results = [parsed_data]
                            
                            st.success(f"Successfully scraped {url_input}")
                            
                            # Display results
                            st.markdown('<div class="sub-header">Scraped Data</div>', unsafe_allow_html=True)
                            st.json(parsed_data)
                    
                except Exception as e:
                    st.error(f"Error during scraping: {str(e)}")
                    logger.error(f"Error scraping {url_input}: {str(e)}")

elif selected_tab == "Batch URLs":
    st.markdown('<h2 class="sub-header">Batch URL Scraping</h2>', unsafe_allow_html=True)
    
    # URL input
    urls_input = st.text_area(
        "Enter URLs to scrape (one per line)",
        placeholder="https://example.com\nhttps://another-site.com"
    )
    
    # Start scraping button
    if st.button("Start Batch Scraping", key="batch_urls_scrape"):
        if not urls_input:
            st.error("Please enter at least one URL to scrape")
        else:
            # Parse URLs
            urls = [url.strip() for url in urls_input.split('\n') if url.strip()]
            
            # Validate URLs
            invalid_urls = [url for url in urls if not re.match(r'^https?://[^\s/$.?#].[^\s]*$', url)]
            if invalid_urls:
                st.error(f"Invalid URL format for: {', '.join(invalid_urls)}")
            else:
                # Create pipeline config
                pipeline_config = {
                    "urls": urls,
                    "scraper_mode": scraper_mode,
                    "extract_text": extract_text,
                    "extract_images": extract_images,
                    "extract_videos": extract_videos,
                    "extract_youtube": extract_youtube,
                    "storage": {
                        "type": "json" if output_format == "JSON" else "csv",
                        "path": f"{output_file}.{output_format.lower()}"
                    }
                }
                
                # Run scraping
                with st.spinner(f"Scraping {len(urls)} URLs..."):
                    try:
                        # Initialize components
                        config = Config("config.yaml")
                        scraper = ScraperFactory.get_scraper(scraper_mode, config)
                        parser = Parser(config)
                        storage = StorageFactory.get_storage(config)
                        youtube_downloader = YouTubeDownloader(config)
                        
                        # Progress bar
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        all_results = []
                        for i, url in enumerate(urls):
                            status_text.text(f"Scraping {url} ({i+1}/{len(urls)})")
                            
                            try:
                                # Check if YouTube URL
                                if extract_youtube and ('youtube.com' in url or 'youtu.be' in url):
                                    # Get video info
                                    video_info = youtube_downloader.get_video_info_pytube(url)
                                    if not video_info:
                                        video_info = youtube_downloader.get_video_info_ytdlp(url)
                                        
                                    if video_info:
                                        # Download thumbnail
                                        thumbnail_result = youtube_downloader.download_thumbnail(url)
                                        if thumbnail_result.get('success'):
                                            video_info['thumbnail_path'] = thumbnail_result.get('file_path')
                                            
                                        all_results.append(video_info)
                                        storage.save(video_info)
                                    else:
                                        logger.warning(f"Failed to extract YouTube video information for {url}")
                                else:
                                    # Regular website scraping
                                    html_content = scraper.scrape(url)
                                    
                                    if html_content is None:
                                        logger.warning(f"Failed to get content from {url}")
                                        continue
                                    
                                    # Parse content
                                    parsed_data = parser.parse_html(html_content)
                                    parsed_data['url'] = url
                                    parsed_data['timestamp'] = time.time()
                                    
                                    # Extract additional data if specified
                                    if extract_images:
                                        parsed_data['images'] = parser.extract_images(html_content, url)
                                    
                                    # Extract metadata
                                    parsed_data['metadata'] = parser.extract_metadata(html_content)
                                    
                                    # Save data
                                    storage.save(parsed_data)
                                    all_results.append(parsed_data)
                                
                                # Update progress
                                progress_bar.progress((i + 1) / len(urls))
                                
                                # Delay between requests
                                time.sleep(config.get_delay_between_requests())
                                
                            except Exception as e:
                                logger.error(f"Error processing URL {url}: {str(e)}")
                                continue
                        
                        # Store results
                        st.session_state.scraping_results = all_results
                        
                        status_text.text(f"Scraped {len(all_results)} URLs successfully")
                        
                        # Display results summary
                        st.markdown('<div class="sub-header">Scraping Results Summary</div>', unsafe_allow_html=True)
                        
                        # Create summary table
                        summary_data = []
                        for result in all_results:
                            domain = urlparse(result.get('url', '')).netloc
                            images_count = len(result.get('images', []))
                            videos_count = len(result.get('videos', []))
                            
                            summary_data.append({
                                'URL': result.get('url', ''),
                                'Domain': domain,
                                'Title': result.get('title', result.get('metadata', {}).get('title', 'N/A')),
                                'Images': images_count,
                                'Videos': videos_count
                            })
                        
                        if summary_data:
                            summary_df = pd.DataFrame(summary_data)
                            st.dataframe(summary_df)
                        
                        # Close resources
                        scraper.close()
                        storage.close()
                        
                    except Exception as e:
                        st.error(f"Error during batch scraping: {str(e)}")
                        logger.error(f"Error during batch scraping: {str(e)}")

elif selected_tab == "Pipeline Config":
    st.markdown('<h2 class="sub-header">Pipeline Configuration</h2>', unsafe_allow_html=True)
    
    # Pipeline file input
    pipeline_file = st.text_input("Pipeline YAML File", value="pipeline.yaml")
    
    # Load pipeline button
    if st.button("Load Pipeline", key="load_pipeline"):
        if not os.path.exists(pipeline_file):
            st.error(f"Pipeline file {pipeline_file} not found!")
        else:
            try:
                with open(pipeline_file, 'r') as file:
                    pipeline_config = yaml.safe_load(file)
                    
                st.success(f"Successfully loaded pipeline from {pipeline_file}")
                st.json(pipeline_config)
                
                # Override with UI settings
                pipeline_config["scraper_mode"] = scraper_mode
                pipeline_config["extract_text"] = extract_text
                pipeline_config["extract_images"] = extract_images
                pipeline_config["extract_videos"] = extract_videos
                pipeline_config["extract_youtube"] = extract_youtube
                pipeline_config["storage"] = {
                    "type": "json" if output_format == "JSON" else "csv",
                    "path": f"{output_file}.{output_format.lower()}"
                }
                
                # Run pipeline button
                if st.button("Run Pipeline", key="run_pipeline"):
                    with st.spinner("Running pipeline..."):
                        from main import execute_pipeline
                        success = execute_pipeline(pipeline_config)
                        
                        if success:
                            st.success("Pipeline executed successfully!")
                        else:
                            st.error("Pipeline execution failed. Check logs for details.")
                
            except Exception as e:
                st.error(f"Error loading pipeline file: {str(e)}")

# Display logs
with st.expander("View Logs"):
    if os.path.exists("scraper.log"):
        with open("scraper.log", "r", encoding="utf-8") as log_file:
            logs = log_file.read()
            st.text_area("Scraper Logs", logs, height=300)
    else:
        st.write("No logs found.")

# Download results
if st.session_state.scraping_results:
    st.markdown('<div class="sub-header">Download Results</div>', unsafe_allow_html=True)
    
    output_path = f"{output_file}.{output_format.lower()}"
    if os.path.exists(output_path):
        with open(output_path, "rb") as f:
            st.download_button(
                label=f"Download Scraped Data ({output_format})",
                data=f,
                file_name=os.path.basename(output_path),
                mime="application/json" if output_format == "JSON" else "text/csv"
            )

# Main function
def main():
    pass

if __name__ == "__main__":
    main()
