from bs4 import BeautifulSoup

def parse_page(content):
    soup = BeautifulSoup(content, 'html.parser')
    data = []

    # 📝 Récupérer tous les textes visibles
    for element in soup.find_all(True):
        text = element.get_text(strip=True)
        if text:
            data.append({'type': 'texte', 'valeur': text})

    # 🖼️ Récupérer les images
    for img in soup.find_all('img'):
        src = img.get('src')
        if src:
            data.append({'type': 'image', 'valeur': src})

    # 📄 Récupérer les fichiers PDF
    for link in soup.find_all('a', href=True):
        href = link['href']
        if href.lower().endswith('.pdf'):
            data.append({'type': 'pdf', 'valeur': href})

    return data
