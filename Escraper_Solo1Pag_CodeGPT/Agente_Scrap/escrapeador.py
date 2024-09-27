import os
from bs4 import BeautifulSoup
import logging
import re
import requests
import time
import json
from dotenv import load_dotenv

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Cargar variables de entorno
load_dotenv()

# Obtener las claves de API y el ID del agente desde las variables de entorno
CODEGPT_API_KEY = os.getenv('CODEGPT_API_KEY')
AGENT_ID = os.getenv('AGENT_ID')

def clean_text(text):
    text = text.strip()
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

def analyze_content(html_content):
    logging.info("Analyzing HTML content")
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Eliminar elementos no deseados
    for tag in soup(['header', 'footer', 'nav', 'script', 'style', 'meta', 'link', 'noscript', 'iframe', 'object', 'embed']):
        tag.decompose()
    
    # Lista de frases o palabras clave a filtrar
    phrases_to_filter = [
        "usamos cookies",
        "mejorar tu experiencia",
        "centro de privacidad",
        "política de privacidad",
        "términos y condiciones",
        "aviso legal",
    ]
    
    content = []
    for element in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'pre', 'code']):
        text = element.text.strip()
        
        # Verificar si el texto contiene alguna de las frases a filtrar
        if not any(phrase in text.lower() for phrase in phrases_to_filter):
            if element.name.startswith('h'):
                level = int(element.name[1])
                prefix = '#' * level
                content.append(f"\n{prefix} {text}\n")
            elif element.name in ['pre', 'code']:
                content.append(f"\n```\n{text}\n```\n")
            else:
                content.append(clean_text(text))
   
    text_content = "\n".join(content)
   
    logging.info("Finished analyzing HTML content")
    return text_content

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

def analyze_webpage(url):
    html_content = scrape_url(url)
    if html_content:
        filtered_content = analyze_content(html_content)
        analyzed_content = analyze_with_codegpt(filtered_content)
        
        if analyzed_content:
            result = analyzed_content + "\n\n"
            
            api_endpoints = extract_api_endpoints(html_content)
            if api_endpoints:
                result += "API Endpoints:\n"
                for endpoint in api_endpoints:
                    result += endpoint + "\n"
                result += "\n"
            
            tables = extract_tables(html_content)
            if tables:
                result += "Tablas Extraídas:\n"
                for i, table in enumerate(tables, 1):
                    result += f"\nTabla {i}:\n"
                    for row in table:
                        result += " | ".join(row) + "\n"
                    result += "\n"
            
            # Guardar resultados en un archivo
            with open("resultados_analisis.txt", "w", encoding="utf-8") as f:
                f.write(result)
            
            logging.info("Resultados guardados en 'resultados_analisis.txt'")
        else:
            logging.error("No se pudo analizar el contenido. Por favor, intente nuevamente.")
    else:
        logging.error("No se pudo acceder al contenido de la URL proporcionada.")

# Ejemplo de uso
if __name__ == "__main__":
    url = input("Ingrese la URL de la página web a analizar: ")
    analyze_webpage(url)
