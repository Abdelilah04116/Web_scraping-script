import streamlit as st
import yaml
import json
import os
import re
import asyncio
import base64
from main import load_pipeline, execute_pipeline
from config import Config
from loguru import logger
from PIL import Image
import io
import time

# Set Windows event loop policy to avoid NotImplementedError
if os.name == 'nt':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Streamlit page configuration
st.set_page_config(page_title="Web Scraper Dashboard", layout="wide")

# Title and description
st.title("Web Scraper Dashboard")
st.markdown("Configure and run web scraping tasks, view scraped images in real-time, and download results.")

# Sidebar for configuration
st.sidebar.header("Configuration")

# Input for pipeline YAML file
pipeline_file = st.sidebar.text_input("Pipeline YAML File", value="pipeline.yaml")
if not os.path.exists(pipeline_file):
    st.sidebar.error("Pipeline file not found!")
    pipeline_config = {}
else:
    pipeline_config = load_pipeline(pipeline_file)
    st.sidebar.success("Pipeline file loaded successfully.")

# Input for single URL (optional)
single_url = st.sidebar.text_input("Single URL to Scrape (Optional)", "")
scraper_mode = st.sidebar.selectbox(
    "Scraper Mode",
    ["simple", "selenium", "scrapy", "pyppeteer", "playwright"],
    index=4  # Default to 'playwright'
)
output_file = st.sidebar.text_input("Output File", value="scraped_data.json")
extract_images = st.sidebar.checkbox("Extract Images", value=True)

# Placeholder for real-time image display
image_container = st.empty()
image_grid = []

# Function to display images in a grid
def display_images(images):
    if not images:
        image_container.markdown("No images scraped yet.")
        return
    # CSS for grid layout
    css = """
    <style>
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
    </style>
    """
    # HTML for image grid
    html = css + '<div class="image-grid">'
    for img in images:
        if img.startswith('data:image'):
            # Base64-encoded image
            html += f'<img src="{img}" alt="Scraped Image">'
        elif img.startswith('http'):
            # URL
            html += f'<img src="{img}" alt="Scraped Image">'
        else:
            # Local file
            try:
                with open(img, "rb") as f:
                    img_data = base64.b64encode(f.read()).decode()
                    html += f'<img src="data:image/jpeg;base64,{img_data}" alt="Scraped Image">'
            except Exception as e:
                logger.warning(f"Could not load image {img}: {str(e)}")
    html += '</div>'
    image_container.markdown(html, unsafe_allow_html=True)

# Function to run scraping with real-time updates
async def run_scraping(pipeline_config):
    try:
        # Initialize config
        config = Config("config.yaml")
        
        # Initialize components
        scraper = ScraperFactory.get_scraper(scraper_mode, config)
        parser = Parser(config)
        storage = StorageFactory.get_storage(config)
        
        # Get URLs
        urls = pipeline_config.get('urls', [])
        site_name = pipeline_config.get('site_name')
        if site_name:
            site_config = config.get_site_config(site_name)
            site_urls = site_config.get('urls', [])
            urls.extend(site_urls)
        
        if not urls:
            st.error("No URLs specified in pipeline or site config")
            return False
        
        # Get selectors
        selectors = pipeline_config.get('selectors', {})
        if not selectors and site_name:
            selectors = config.get_site_config(site_name).get('selectors', {})
        
        # Progress bar
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        all_results = []
        for i, url in enumerate(urls):
            status_text.text(f"Scraping {url} ({i+1}/{len(urls)})")
            try:
                # Scrape URL
                html_content = await scraper.scrape(url)
                
                if html_content is None:
                    logger.warning(f"Failed to get content from {url}")
                    continue
                
                # Parse HTML
                parsed_data = parser.parse_html(html_content, selectors)
                parsed_data['url'] = url
                parsed_data['timestamp'] = time.time()
                parsed_data['site_name'] = site_name
                
                # Extract images if enabled
                if extract_images:
                    parsed_data['images'] = parser.extract_images(html_content, url)
                    # Update image grid
                    if parsed_data['images']:
                        image_grid.extend(parsed_data['images'])
                        display_images(image_grid)
                
                # Save data
                storage.save(parsed_data)
                all_results.append(parsed_data)
                
                # Update progress
                progress_bar.progress((i + 1) / len(urls))
                
                # Delay
                await asyncio.sleep(config.get_delay_between_requests())
                
            except Exception as e:
                logger.error(f"Error processing URL {url}: {str(e)}")
                continue
        
        status_text.text(f"Scraped {len(all_results)} URLs successfully")
        
        # Post-processing
        if pipeline_config.get('post_processing'):
            all_results = post_process(all_results, pipeline_config['post_processing'])
        
        # Save final results
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_results, f, indent=2)
        
        # Close resources
        await scraper.close()
        storage.close()
        
        return True
        
    except Exception as e:
        logger.error(f"Error executing pipeline: {str(e)}")
        return False

# Button to start scraping
if st.sidebar.button("Start Scraping"):
    if single_url:
        # Validate URL
        if not re.match(r'^https?://[^\s/$.?#].[^\s]*$', single_url):
            st.error("Invalid URL format!")
        else:
            pipeline_config = {
                "urls": [single_url],
                "scraper_mode": scraper_mode,
                "storage": {
                    "type": "json",
                    "path": output_file
                },
                "extract_images": extract_images
            }
    elif not pipeline_config:
        st.error("No valid pipeline configuration or URL provided!")
    else:
        pipeline_config["scraper_mode"] = scraper_mode
        pipeline_config["storage"] = pipeline_config.get("storage", {})
        pipeline_config["storage"]["type"] = "json"
        pipeline_config["storage"]["path"] = output_file
        pipeline_config["extract_images"] = extract_images
    
    # Run scraping asynchronously
    with st.spinner("Running scraping pipeline..."):
        try:
            success = asyncio.run(run_scraping(pipeline_config))
            if success:
                st.success("Scraping completed successfully!")
                if os.path.exists(output_file):
                    with open(output_file, 'r', encoding='utf-8') as f:
                        results = json.load(f)
                        st.write("### Scraped Data")
                        st.json(results)
            else:
                st.error("Scraping failed. Check logs for details.")
        except Exception as e:
            st.error(f"Error during scraping: {str(e)}")

# Display logs
st.header("Logs")
if os.path.exists("scraper.log"):
    with open("scraper.log", "r", encoding="utf-8") as log_file:
        logs = log_file.read()
        st.text_area("Scraper Logs", logs, height=300)
        if "Timeout" in logs:
            st.warning("Scraping timed out. Consider increasing the timeout in config.yaml.")
        if "SSLError" in logs:
            st.warning("SSL verification failed. Check verify_ssl in config.yaml.")
else:
    st.write("No logs found.")

# Option to download results
if os.path.exists(output_file):
    with open(output_file, "rb") as f:
        st.download_button(
            label="Download Scraped Data",
            data=f,
            file_name=output_file,
            mime="application/json"
        )