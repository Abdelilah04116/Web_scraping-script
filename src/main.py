from scraper import fetch_page
from parser import parse_page
from storage import save_to_csv
from config import load_config

def main():
    config = load_config()
    print(f"Scraping du site : {config['scraper']['base_url']}")

    page_content = fetch_page(config['scraper']['base_url'])
    if page_content:
        data = parse_page(page_content)
        save_to_csv(data, config['scraper']['output_file'])
        print(f"Données sauvegardées dans {config['scraper']['output_file']}")
    else:
        print("Échec du scraping.")

if __name__ == "__main__":
    main()