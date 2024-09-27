import os
import logging
import requests
import time
from bs4 import BeautifulSoup
import argparse
from urllib.parse import urljoin, urlparse
import json
import re
from dotenv import load_dotenv
import hashlib

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar variables de entorno desde un archivo .env
load_dotenv()

# Obtener las claves de API y el ID del agente desde las variables de entorno
CODEGPT_API_KEY = os.getenv('CODEGPT_API_KEY')
AGENT_ID = os.getenv('AGENT_ID')

# Tamaño máximo de archivo en bytes (1.2 MB)
MAX_FILE_SIZE = 1.2 * 1024 * 1024

# Profundidad máxima de crawling
MAX_DEPTH = 3

# Lista de frases o palabras clave a filtrar
phrases_to_filter = [
    "usamos cookies",
    "mejorar tu experiencia",
    "centro de privacidad",
    "política de privacidad",
    "términos y condiciones",
    "aviso legal",
]

# Palabras clave válidas para URLs
VALID_KEYWORDS = ['api', 'reference', 'documentation', 'endpoint', 'integration']

def should_filter_text(text):
    """Verificar si el texto contiene alguna de las frases a filtrar."""
    return any(phrase.lower() in text.lower() for phrase in phrases_to_filter)

def clean_text(text):
    # Eliminar espacios en blanco extra al principio y al final
    text = text.strip()
    # Reemplazar múltiples espacios en blanco con un solo espacio
    text = re.sub(r'\s+', ' ', text)
    return text

def scrape_url(url):
    try:
        logging.info(f"Scraping URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        logging.info("Successfully scraped URL")
        return response.text
    except requests.exceptions.RequestException as e:
        logging.error(f"Error scraping URL: {e}")
        return ""

def extract_api_endpoints(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    endpoints = []

    # Buscar endpoints en elementos <strong>
    strong_tags = soup.find_all('strong')
    for tag in strong_tags:
        if re.search(r'https?://api\.', tag.text):
            endpoints.append(tag.text.strip())

    # Buscar endpoints en celdas de tabla
    tables = soup.find_all('table')
    for table in tables:
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            for cell in cells:
                if re.search(r'/[a-zA-Z0-9_/]+', cell.text):
                    endpoints.append(cell.text.strip())

    return endpoints

def extract_tables(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    tables = soup.find_all('table')
    extracted_tables = []

    for table in tables:
        table_data = []
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['th', 'td'])
            row_data = [cell.text.strip() for cell in cells]
            table_data.append(row_data)
        extracted_tables.append(table_data)

    return extracted_tables

def analyze_with_codegpt(content):
    headers = {
        "Authorization": f"Bearer {CODEGPT_API_KEY}",
        "Content-Type": "application/json"
    }
    
    prompt = (
        "Extract and return only the main content from the following text. "
        "Preserve all headings, subheadings, and their hierarchy exactly as they appear. "
        "Keep all technical details, examples, and code snippets intact. "
        "Maintain the original language and formatting. "
        "Do not summarize, translate, or alter any information, including headings and code examples:\n\n" 
        + content
    )
    
    for attempt in range(3):
        try:
            logging.info(f"Attempt {attempt + 1} to analyze with CodeGPT")
            response = requests.post(
                "https://api.codegpt.co/api/v1/chat/completions",
                headers=headers,
                json={
                    "agent": AGENT_ID,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ]
                }
            )
            
            response.raise_for_status()
            
            if not response.text.strip():
                return ""
            
            try:
                json_response = response.json()
                analyzed_content = json_response['choices'][0]['message']['content']
            except json.JSONDecodeError:
                analyzed_content = response.text
            
            if not analyzed_content.strip():
                return ""
            
            return analyzed_content
        
        except requests.exceptions.RequestException:
            if attempt < 2:
                time.sleep(2)
            else:
                return ""
        except KeyError:
            return ""
    
    return ""

def analyze_content(html_content):
    logging.info("Analyzing HTML content")
    soup = BeautifulSoup(html_content, 'html.parser')

    for tag in soup(['header', 'footer', 'nav', 'script', 'style', 'meta', 'link', 'noscript', 'iframe', 'object', 'embed']):
        tag.decompose()

    content = []
    for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'code']):
        text = element.text.strip()
        if should_filter_text(text):
            continue  # Omitir el texto si contiene alguna frase a filtrar
        if element.name.startswith('h'):
            level = int(element.name[1])
            prefix = '#' * level
            content.append(f"\n{prefix} {text}\n")
        elif element.name in ['pre', 'code']:
            code_content = element.text.strip()
            content.append(f"\n```\n{code_content}\n```\n")
        else:
            content.append(clean_text(text))
    
    text_content = "\n".join(content)
    
    logging.info("Finished analyzing HTML content")
    return text_content

def save_to_file(content, filename):
    try:
        with open(filename, "a", encoding="utf-8") as file:
            file.write(content + "\n\n")
        logging.info(f"Content saved to {filename}")
    except IOError as e:
        logging.error(f"Error saving to file: {e}")

def is_valid_url(url, base_domain):
    parsed_url = urlparse(url)
    return (parsed_url.netloc == base_domain and 
            parsed_url.scheme in ['http', 'https'] and 
            '/developers/' in parsed_url.path and
            '/docs/' in parsed_url.path)

def contains_valid_keyword(url):
    return any(keyword in url.lower() for keyword in VALID_KEYWORDS)

def get_links(html_content, base_url, base_domain):
    soup = BeautifulSoup(html_content, 'html.parser')
    links = []
    for a in soup.find_all('a', href=True):
        full_url = urljoin(base_url, a['href'])
        if is_valid_url(full_url, base_domain) and contains_valid_keyword(full_url):
            links.append(full_url)
    return links

def crawl_and_save(base_url, output_dir, company_name, depth=0):
    if depth > MAX_DEPTH:
        return

    visited = set()
    to_visit = [base_url]
    base_domain = urlparse(base_url).netloc
    current_file_size = 0
    file_counter = 1
    current_file = os.path.join(output_dir, f"{company_name}_{file_counter}.txt")
    content_hash = set()

    while to_visit:
        url = to_visit.pop(0)
        if url in visited:
            continue

        visited.add(url)
        html_content = scrape_url(url)
        
        if not html_content:
            continue

        filtered_content = analyze_content(html_content)
        analyzed_content = analyze_with_codegpt(filtered_content)

        if analyzed_content:
            # Verificar si el contenido ya ha sido guardado
            content_md5 = hashlib.md5(analyzed_content.encode()).hexdigest()
            if content_md5 in content_hash:
                continue
            content_hash.add(content_md5)

            content_size = len(analyzed_content.encode('utf-8'))
            
            if current_file_size + content_size > MAX_FILE_SIZE:
                file_counter += 1
                current_file = os.path.join(output_dir, f"{company_name}_{file_counter}.txt")
                current_file_size = 0

            save_to_file(analyzed_content, current_file)
            current_file_size += content_size

        api_endpoints = extract_api_endpoints(html_content)
        tables = extract_tables(html_content)

        # Guardar los endpoints y tablas solo si no están vacíos
        if api_endpoints:
            content = "API Endpoints:\n" + "\n".join(api_endpoints) + "\n\n"
            save_to_file(content, current_file)
            current_file_size += len(content.encode('utf-8'))

        if tables:
            content = "Tables:\n"
            for i, table in enumerate(tables, 1):
                content += f"\nTable {i}:\n"
                for row in table:
                    content += " | ".join(row) + "\n"
                content += "\n"
            save_to_file(content, current_file)
            current_file_size += len(content.encode('utf-8'))

        # Verificar si es necesario crear un nuevo archivo
        if current_file_size > MAX_FILE_SIZE:
            file_counter += 1
            current_file = os.path.join(output_dir, f"{company_name}_{file_counter}.txt")
            current_file_size = 0

        links = get_links(html_content, url, base_domain)
        for link in links:
            if link not in visited:
                crawl_and_save(link, output_dir, company_name, depth + 1)

        time.sleep(1)  # Añadir un retraso de 1 segundo entre solicitudes

def main(base_url, output_dir, company_name):
    try:
        os.makedirs(output_dir, exist_ok=True)
        if not os.access(output_dir, os.W_OK):
            return

        crawl_and_save(base_url, output_dir, company_name)

    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Web scraper and content analyzer")
    parser.add_argument("--url", default="https://www.mercadopago.com.ar/developers/es/docs", help="Base URL to start scraping")
    parser.add_argument("--output_dir", default="output", help="Directory to save the output files")
    parser.add_argument("--company_name", default="MercadoPago", help="Name of the company for file naming")
    
    args = parser.parse_args()
    main(args.url, args.output_dir, args.company_name)
