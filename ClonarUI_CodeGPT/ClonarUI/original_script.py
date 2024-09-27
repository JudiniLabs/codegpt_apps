import asyncio
import aiohttp
from bs4 import BeautifulSoup
import base64
from urllib.parse import urljoin, urlparse
import re
import os
from dotenv import load_dotenv
import logging
import argparse
import webbrowser
import sys
import json

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Cargar variables de entorno
load_dotenv()

# Obtener las claves de API y los IDs desde las variables de entorno
CODEGPT_API_KEY = os.getenv('CODEGPT_API_KEY')
AGENT_ID = os.getenv('AGENT_ID')
CODEGPT_ORG_ID = os.getenv('CODEGPT_ORG_ID')

if not CODEGPT_API_KEY or not AGENT_ID:
    logger.error("CODEGPT_API_KEY y AGENT_ID deben estar definidos en el archivo .env")
    sys.exit(1)

async def fetch_resource(session, url, is_binary=False, timeout=30, max_retries=3):
    for attempt in range(max_retries):
        try:
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    if is_binary:
                        content = await response.read()
                        return f"data:{response.headers['Content-Type']};base64,{base64.b64encode(content).decode('utf-8')}"
                    else:
                        return await response.text()
                elif response.status == 404:
                    logger.error(f"Recurso no encontrado: {url}")
                    return None
                else:
                    logger.warning(f"Error al obtener recurso: {url}. Estado: {response.status}")
        except asyncio.TimeoutError:
            logger.warning(f'Timeout fetching resource: {url}. Intento {attempt + 1} de {max_retries}')
        except Exception as e:
            logger.error(f'Error al obtener recurso: {url}. Error: {e}. Intento {attempt + 1} de {max_retries}')
        
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)  # Espera exponencial entre intentos
    
    return None

async def inline_css(session, link_element, base_url):
    href = urljoin(base_url, link_element['href'])
    css_content = await fetch_resource(session, href)
    if css_content:
        resolved_css = re.sub(
            r'url\((?![\'"]?(?:data:|https?:|ftp:))[\'"]?([^\'"]+)[\'"]?\)',
            lambda m: f'url({urljoin(href, m.group(1))})',
            css_content
        )
        return f'<style>{resolved_css}</style>'
    return ''

async def inline_images(session, soup, base_url):
    images = soup.find_all('img')
    tasks = []
    for img in images:
        if img.get('src'):
            src = urljoin(base_url, img['src'])
            task = asyncio.create_task(fetch_resource(session, src, is_binary=True))
            tasks.append((img, task))
    
    for img, task in tasks:
        data_uri = await task
        if data_uri:
            img['src'] = data_uri

async def inline_scripts(session, soup, base_url):
    scripts = soup.find_all('script', src=True)
    for script in scripts:
        src = urljoin(base_url, script['src'])
        script_content = await fetch_resource(session, src)
        if script_content:
            new_script = soup.new_tag('script')
            new_script.string = script_content
            script.replace_with(new_script)

async def download_complete_html(session, url, output_file='index.html'):
    logger.info(f"Descargando HTML de {url}")
    html_content = await fetch_resource(session, url)
    if not html_content:
        logger.error(f"No se pudo obtener el contenido HTML de {url}")
        return None

    soup = BeautifulSoup(html_content, 'html.parser')

    # Inline CSS
    logger.info("Incrustando CSS")
    css_tasks = []
    for link in soup.find_all('link', rel='stylesheet'):
        css_tasks.append(inline_css(session, link, url))
    inlined_css = await asyncio.gather(*css_tasks)
    for link, style in zip(soup.find_all('link', rel='stylesheet'), inlined_css):
        if style:
            link.replace_with(BeautifulSoup(style, 'html.parser'))

    # Inline images
    logger.info("Incrustando imágenes")
    await inline_images(session, soup, url)

    # Inline scripts
    logger.info("Incrustando scripts")
    await inline_scripts(session, soup, url)

    # Add base tag to ensure relative links work correctly
    base_tag = soup.new_tag('base', href=url)
    soup.head.insert(0, base_tag)

    final_html = str(soup)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(final_html)

    logger.info(f"HTML completo descargado y guardado como '{output_file}'")
    return final_html

async def analyze_with_codegpt(session, content, system_prompt, max_retries=5, initial_delay=1):
    headers = {
        "Authorization": f"Bearer {CODEGPT_API_KEY}",
        "Content-Type": "application/json"
    }
    
    if CODEGPT_ORG_ID:
        headers["CodeGPT-Org-Id"] = CODEGPT_ORG_ID
    
    data = {
        "agentId": AGENT_ID,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": content[:4000]
            }
        ]
    }
    
    api_url = "https://api.codegpt.co/api/v1/chat/completions"
    
    delay = initial_delay
    for attempt in range(max_retries):
        try:
            logger.info(f"Haciendo solicitud a CodeGPT API: {api_url} (Intento {attempt + 1})")
            async with session.post(api_url, headers=headers, json=data, timeout=30) as response:
                logger.info(f"Código de estado de la respuesta: {response.status}")
                if response.status == 200:
                    result = await response.text()
                    logger.info(f"Respuesta completa de CodeGPT: {result}")
                    try:
                        json_result = json.loads(result)
                        return json_result['choices'][0]['message']['content']
                    except json.JSONDecodeError:
                        logger.error(f"Error al decodificar JSON: {result}")
                        return None
                elif response.status in [429, 500, 502, 503, 504]:
                    if attempt < max_retries - 1:
                        logger.warning(f"Error {response.status}. Reintentando en {delay} segundos...")
                        await asyncio.sleep(delay)
                        delay *= 2
                    else:
                        logger.error(f"Error {response.status} persistente después de {max_retries} intentos.")
                        return None
                else:
                    error_text = await response.text()
                    logger.error(f"Error en la llamada a CodeGPT API: {response.status}")
                    logger.error(f"Respuesta de error: {error_text}")
                    return None
        except asyncio.TimeoutError:
            logger.warning(f"Timeout en la solicitud a CodeGPT API. Intento {attempt + 1}")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                logger.error("Timeout persistente en la solicitud a CodeGPT API")
                return None
        except Exception as e:
            logger.error(f"Error al comunicarse con CodeGPT API: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
            else:
                return None

    return None

def validate_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def open_html_file(file_path):
    try:
        webbrowser.open('file://' + os.path.realpath(file_path))
        logger.info(f"Archivo HTML abierto en el navegador: {file_path}")
    except Exception as e:
        logger.error(f"No se pudo abrir el archivo HTML: {e}")

async def modify_html_with_codegpt(session, html_content, modification_prompt):
    system_prompt = """
    Eres un experto en modificación de HTML, CSS y JavaScript. Tu tarea es modificar el código HTML 
    proporcionado según las instrucciones del usuario. Debes devolver SOLO los cambios necesarios 
    en formato JSON, sin ningún texto adicional o marcadores de código. Por ejemplo:
    {
        "type": "style",
        "selector": "body",
        "properties": {
            "background-color": "#121212",
            "color": "#ffffff"
        }
    }
    O para cambios de texto:
    {
        "type": "text",
        "selector": "title",
        "text": "Nuevo título"
    }
    Asegúrate de que tus modificaciones sean precisas y no rompan la estructura del documento.
    """
    
    user_prompt = f"Modifica el siguiente HTML según esta instrucción: {modification_prompt}\n\nHTML:\n{html_content[:1000]}..."
    
    response = await analyze_with_codegpt(session, user_prompt, system_prompt)
    
    if response:
        logger.info(f"Respuesta de CodeGPT: {response}")
        try:
            # Eliminar comillas triples y la palabra "json" si están presentes
            cleaned_response = response.strip().lstrip('`').rstrip('`').lstrip('json').strip()
            changes = json.loads(cleaned_response)
            
            soup = BeautifulSoup(html_content, 'html.parser')
            
            if changes['type'] == 'style':
                # Buscar o crear la etiqueta <style>
                style_tag = soup.find('style')
                if not style_tag:
                    style_tag = soup.new_tag('style')
                    soup.head.append(style_tag)
                
                # Crear la regla CSS
                css_rule = f"{changes['selector']} {{"
                for prop, value in changes['properties'].items():
                    css_rule += f"{prop}: {value};"
                css_rule += "}"
                
                # Añadir la regla CSS al contenido de la etiqueta <style>
                style_tag.string = style_tag.string + css_rule if style_tag.string else css_rule
            elif changes['type'] == 'text':
                # Modificar el texto del elemento seleccionado
                element = soup.select_one(changes['selector'])
                if element:
                    element.string = changes['text']
                else:
                    logger.warning(f"No se encontró el elemento con el selector: {changes['selector']}")
            
            return str(soup)
        except json.JSONDecodeError as e:
            logger.error(f"Error al decodificar JSON de la respuesta de CodeGPT: {e}")
            logger.error(f"Respuesta recibida: {response}")
            return html_content
        except Exception as e:
            logger.error(f"Error al procesar la respuesta de CodeGPT: {e}")
            logger.error(f"Respuesta recibida: {response}")
            return html_content
    else:
        logger.error("No se pudo obtener una respuesta de CodeGPT para la modificación.")
        return html_content

async def main(url, output_file):
    if not validate_url(url):
        logger.error("URL inválida. Por favor, ingrese una URL completa que comience con http:// o https://")
        return

    async with aiohttp.ClientSession() as session:
        html_content = await download_complete_html(session, url, output_file)
        if not html_content:
            logger.error("No se pudo descargar el HTML. Saliendo del programa.")
            return

        open_html_file(output_file)
        
        while True:
            user_input = input("\nIngrese una instrucción para modificar la UI (o 'salir' para terminar): ")
            if user_input.lower() == 'salir':
                break

            logger.info("Modificando el HTML con CodeGPT...")
            modified_html = await modify_html_with_codegpt(session, html_content, user_input)
            
            if modified_html != html_content:
                html_content = modified_html
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info(f"HTML modificado y guardado en '{output_file}'")
                
                # Imprimir un resumen de los cambios
                soup_original = BeautifulSoup(html_content, 'html.parser')
                soup_modified = BeautifulSoup(modified_html, 'html.parser')
                
                if soup_original.title != soup_modified.title:
                    logger.info(f"Título modificado: '{soup_original.title.string}' -> '{soup_modified.title.string}'")
                
                open_html_file(output_file)
            else:
                logger.info("No se realizaron cambios en el HTML.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Descarga, analiza y modifica una página web")
    parser.add_argument("url", help="URL de la página web a descargar y modificar")
    parser.add_argument("-o", "--output", default="index.html", help="Nombre del archivo de salida (por defecto: index.html)")
    args = parser.parse_args()

    try:
        asyncio.run(main(args.url, args.output))
    except KeyboardInterrupt:
        logger.info("Programa interrumpido por el usuario.")
    except Exception as e:
        logger.error(f"Error inesperado: {e}")
        logger.exception("Detalles del error:")
