import streamlit as st
import yaml
import os
from main import load_pipeline, execute_pipeline
from config import Config

# Streamlit page configuration
st.set_page_config(page_title="Web Scraper Dashboard", layout="wide")

# Title and description
st.title("Web Scraper Dashboard")
st.markdown("Configure and run web scraping tasks with ease.")

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
    index=4  # Default to 'playwright' as per config.yaml
)
output_file = st.sidebar.text_input("Output File", value="scraped_data.json")

# Button to start scraping
if st.sidebar.button("Start Scraping"):
    if single_url:
        # Create a simple pipeline for a single URL
        pipeline_config = {
            "urls": [single_url],
            "scraper_mode": scraper_mode,
            "storage": {
                "type": "json",
                "path": output_file
            }
        }
    elif not pipeline_config:
        st.error("No valid pipeline configuration or URL provided!")
    else:
        # Use the loaded pipeline configuration
        pipeline_config["scraper_mode"] = scraper_mode
        pipeline_config["storage"] = pipeline_config.get("storage", {})
        pipeline_config["storage"]["type"] = "json"
        pipeline_config["storage"]["path"] = output_file

    # Execute the pipeline
    with st.spinner("Running scraping pipeline..."):
        success = execute_pipeline(pipeline_config)
        if success:
            st.success("Scraping completed successfully!")
            # Display results (if stored in JSON)
            if os.path.exists(output_file):
                with open(output_file, 'r', encoding='utf-8') as f:
                    results = yaml.safe_load(f)
                    st.write("### Scraped Data")
                    st.json(results)
        else:
            st.error("Scraping failed. Check logs for details.")

# Display logs
st.header("Logs")
if os.path.exists("scraper.log"):
    with open("scraper.log", "r", encoding="utf-8") as log_file:
        logs = log_file.read()
        st.text_area("Scraper Logs", logs, height=300)
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