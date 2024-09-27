import streamlit as st
import asyncio
import aiohttp
import os
import webbrowser
import json
import base64
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# Cargar variables de entorno
load_dotenv()

CODEGPT_API_KEY = os.getenv("CODEGPT_API_KEY")
AGENT_ID = os.getenv("AGENT_ID")

# Verificar las claves de API
if not CODEGPT_API_KEY or not AGENT_ID:
    st.error("CODEGPT_API_KEY y AGENT_ID deben estar definidos en el archivo .env")
    st.stop()

async def fetch_resource(session, url, is_binary=False):
    try:
        async with session.get(url) as response:
            if is_binary:
                return await response.read()
            else:
                return await response.text()
    except Exception as e:
        st.warning(f"Failed to fetch resource: {url}")
        return None

async def inline_css(session, link_element):
    href = link_element['href']
    css_content = await fetch_resource(session, href)
    if css_content:
        style_element = BeautifulSoup().new_tag('style')
        style_element.string = css_content
        return style_element
    return None

async def inline_images(session, soup):
    for img in soup.find_all('img'):
        if img.get('src', '').startswith('http'):
            img_data = await fetch_resource(session, img['src'], is_binary=True)
            if img_data:
                img_base64 = base64.b64encode(img_data).decode('utf-8')
                img['src'] = f"data:image/png;base64,{img_base64}"

async def inline_scripts(session, soup):
    for script in soup.find_all('script', src=True):
        if script['src'].startswith('http'):
            script_content = await fetch_resource(session, script['src'])
            if script_content:
                new_script = soup.new_tag('script')
                new_script.string = script_content
                script.replace_with(new_script)

async def download_complete_html(session, url, output_file):
    html_content = await fetch_resource(session, url)
    if not html_content:
        st.error(f"No se pudo descargar el contenido de {url}")
        return None

    soup = BeautifulSoup(html_content, 'html.parser')

    # Inline CSS
    css_tasks = [inline_css(session, link) for link in soup.find_all('link', rel='stylesheet')]
    inlined_css = await asyncio.gather(*css_tasks)
    for link, style in zip(soup.find_all('link', rel='stylesheet'), inlined_css):
        if style:
            link.replace_with(style)

    # Inline images
    await inline_images(session, soup)

    # Inline scripts
    await inline_scripts(session, soup)

    final_html = str(soup)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(final_html)

    return final_html

async def analyze_with_codegpt(session, content, prompt):
    url = f"https://api.codegpt.co/v1/agent/{AGENT_ID}/completion"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CODEGPT_API_KEY}"
    }
    data = {
        "prompt": prompt,
        "content": content,
        "max_tokens": 500,
        "temperature": 0.7
    }

    async with session.post(url, json=data, headers=headers) as response:
        if response.status == 200:
            result = await response.json()
            return result.get('choices', [{}])[0].get('text', '').strip()
        else:
            st.error(f"Error en la solicitud a CodeGPT: {response.status}")
            return None

def apply_modifications(html_content, modifications):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    for mod in modifications:
        if mod['action'] == 'change_background':
            soup.body['style'] = f"background-color: {mod['color']};"
        elif mod['action'] == 'change_title':
            title_tag = soup.find('title')
            if title_tag:
                title_tag.string = mod['new_title']
        elif mod['action'] == 'change_logo':
            logo_img = soup.find('img', {'alt': 'logo'})  # Asumiendo que el logo tiene un alt="logo"
            if logo_img:
                logo_img['src'] = mod['new_logo_url']
    
    return str(soup)

def open_html_file(file_path):
    try:
        webbrowser.open('file://' + os.path.realpath(file_path))
        st.success(f"Archivo HTML abierto en el navegador: {file_path}")
    except Exception as e:
        st.error(f"No se pudo abrir el archivo HTML: {e}")

def validate_url(url):
    return url.startswith(('http://', 'https://'))

async def process_url(url, output_file):
    async with aiohttp.ClientSession() as session:
        html_content = await download_complete_html(session, url, output_file)
        
        if html_content:
            st.success(f"HTML descargado y guardado como '{output_file}'")
            
            st.info("Generando modificaciones con CodeGPT...")
            modifications_prompt = """
            Genera una lista de modificaciones para el HTML en formato JSON. Incluye las siguientes modificaciones:
            1. Cambiar el fondo a negro
            2. Cambiar el título por "Nicolas Leiva"
            3. Cambiar el logo por la imagen de una pera (usa una URL de imagen de pera)
            
            Formato de salida:
            [
                {"action": "change_background", "color": "black"},
                {"action": "change_title", "new_title": "Nicolas Leiva"},
                {"action": "change_logo", "new_logo_url": "URL_DE_IMAGEN_DE_PERA"}
            ]
            """
            modifications_json = await analyze_with_codegpt(session, html_content, modifications_prompt)
            
            if modifications_json:
                try:
                    modifications = json.loads(modifications_json)
                    modified_html = apply_modifications(html_content, modifications)
                    
                    # Guardar el HTML modificado
                    with open(output_file, 'w', encoding='utf-8') as f:
                        f.write(modified_html)
                    
                    st.success("HTML modificado y guardado.")
                    open_html_file(output_file)
                except json.JSONDecodeError:
                    st.error("Error al procesar las modificaciones de CodeGPT.")
            else:
                st.warning("No se pudieron obtener modificaciones de CodeGPT.")

            return html_content
        else:
            st.error("No se pudo procesar la URL.")
            return None

def main():
    st.title("Clonador y Modificador de UI Web")

    url = st.text_input("Ingrese la URL de la página web a clonar y modificar:")
    output_file = st.text_input("Nombre del archivo de salida:", value="index.html")

    if st.button("Clonar y Modificar"):
        if not validate_url(url):
            st.error("URL inválida. Por favor, ingrese una URL completa que comience con http:// o https://")
        else:
            asyncio.run(process_url(url, output_file))

if __name__ == "__main__":
    main()
