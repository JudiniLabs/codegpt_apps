import streamlit as st
import os
import requests
import re
from bs4 import BeautifulSoup
import time
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from Lista_Agentes import obtener_agentes, obtener_nombre_agente
from Agente_Estructura import evaluar_estructura
from dotenv import load_dotenv
from Agente_Prompt import obtener_prompt_agente, analizar_prompt
import pandas as pd
import io
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Cargar variables de entorno
load_dotenv()

# Configuración de la API
API_URL = "https://api.codegpt.co/api/v1/chat/completions"
API_KEY = os.getenv("CODEGPT_API_KEY")
ORG_ID = os.getenv("CODEGPT_ORG_ID")
AGENT_PREGUNTA_ID = os.getenv("CODEGPT_AGENT_PREGUNTA_ID")

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "CodeGPT-Org-Id": ORG_ID
}

@st.cache_data
def scrape_content(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        return soup.get_text(separator='\n')
    except Exception as e:
        st.error(f"Error scraping the content from {url}: {e}")
        return None

@st.cache_data
def extract_links(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        links = [urljoin(url, a['href']) for a in soup.find_all('a', href=True)]
        return [link for link in links if es_enlace_relevante(link, url)]
    except Exception as e:
        st.error(f"Error extracting links from {url}: {e}")
        return []

def verificar_enlace(url):
    try:
        response = requests.head(url, allow_redirects=True, timeout=10)
        return response.status_code == 200
    except requests.RequestException:
        return False

def corregir_enlaces(base_url, enlaces):
    return [urljoin(base_url, enlace) for enlace in enlaces if verificar_enlace(urljoin(base_url, enlace))]

def es_enlace_relevante(url, base_url):
    parsed_base_url = urlparse(base_url)
    parsed_url = urlparse(url)
    
    mismo_dominio = parsed_url.netloc == parsed_base_url.netloc or not parsed_url.netloc
    mismo_path = parsed_url.path.startswith(parsed_base_url.path)
    
    return mismo_dominio and mismo_path and not re.search(r'(login|signup|contact|about|terms|privacy)', url, re.IGNORECASE)

def es_pregunta_similar(pregunta, preguntas_generadas, umbral=0.8):
    if not preguntas_generadas:
        return False
    vectorizer = TfidfVectorizer().fit_transform([pregunta] + list(preguntas_generadas))
    vectors = vectorizer.toarray()
    cosine_matrix = cosine_similarity(vectors)
    similarities = cosine_matrix[0][1:]
    return any(similarity > umbral for similarity in similarities)
def generar_pregunta(content, max_retries=10):
    payload = {
        "agentId": AGENT_PREGUNTA_ID,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "content": f"Based on the following documentation content, generate one specific question about the API focusing on development and analysis aspects, including endpoints, SDKs, and integration details. Include the link to the section of the documentation where the question is derived from. Format the question as a numbered list item followed by the link in parentheses.\n\n{content}",
                "role": "user"
            }
        ]
    }

    for attempt in range(max_retries):
        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            
            match = re.search(r'\d+\.\s*(.+?)\s*\((https?://[^\s]+)\)', content)
            if match:
                return match.groups()
            else:
                return None

        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                st.error(f"Error generating question: {e}")

    return None

def obtener_respuesta(agent_id, pregunta, max_retries=3):
    payload = {
        "agentId": agent_id,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "content": pregunta,
                "role": "user"
            }
        ]
    }

    for attempt in range(max_retries):
        try:
            start_time = time.time()
            response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            end_time = time.time()
            response_time = end_time - start_time
            return response.json()['choices'][0]['message']['content'], response_time
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                st.error(f"Error obtaining response: {e}")

    return None, None

def procesar_enlace(link, url_docs, preguntas_generadas):
    full_url = urljoin(url_docs, link)
    content = scrape_content(full_url)
    if not content:
        return None
    pregunta_y_enlace = generar_pregunta(content)
    if not pregunta_y_enlace:
        return None
    pregunta, enlace = pregunta_y_enlace
    if es_pregunta_similar(pregunta, preguntas_generadas):
        return None
    enlaces_corregidos = corregir_enlaces(url_docs, [enlace])
    if not enlaces_corregidos:
        return None
    return pregunta, enlaces_corregidos[0]

def analizar_evaluacion_estructura(evaluacion):
    resultados = {}
    feedback = {}
    componentes = ['Role', 'Format', 'Context', 'Error Handling']
    
    # Buscar en el formato detallado
    for componente in componentes:
        presente_match = re.search(rf'{componente}:.*?\n-\s*\*\*Present:\s*(Yes|No)\*\*', evaluacion, re.DOTALL | re.IGNORECASE)
        feedback_match = re.search(rf'{componente}:.*?\n-\s*\*\*Feedback:\s*(.*?)\*\*', evaluacion, re.DOTALL | re.IGNORECASE)
        
        if presente_match:
            resultados[componente] = presente_match.group(1)
            if feedback_match:
                feedback[componente] = feedback_match.group(1).strip()
    
    # Si no se encontraron todos los componentes, buscar en el resumen
    if len(resultados) < len(componentes):
        summary_start = evaluacion.find('### Summary:')
        if summary_start != -1:
            summary = evaluacion[summary_start:]
            for componente in componentes:
                if componente not in resultados and re.search(rf'\b{componente}\b', summary, re.IGNORECASE):
                    resultados[componente] = 'Yes'
                    feedback[componente] = 'Present in summary'
    
    # Si aún no hay todos los resultados, buscar en cualquier parte del texto
    if len(resultados) < len(componentes):
        for componente in componentes:
            if componente not in resultados:
                match = re.search(rf'\b{componente}\b.*?(Yes|No)', evaluacion, re.IGNORECASE | re.DOTALL)
                if match:
                    resultados[componente] = match.group(1)
                    feedback[componente] = 'Found in evaluation'
    
    # Si algún componente sigue sin encontrarse, marcarlo como N/A
    for componente in componentes:
        if componente not in resultados:
            resultados[componente] = 'N/A'
            feedback[componente] = 'Not found in evaluation'
    
    return resultados, feedback
def main():
    st.title("API Documentation Analyzer")

    agentes = obtener_agentes()
    agent_options = {agente['name']: agente['id'] for agente in agentes}
    agent_name = st.selectbox("Select the agent you want to use:", list(agent_options.keys()))
    agent_id = agent_options[agent_name]

    prompt = obtener_prompt_agente(agent_id)
    if prompt:
        with st.expander("Agent Prompt Analysis"):
            st.write("Agent Prompt:")
            st.text(prompt)
            analisis = analizar_prompt(prompt)
            if analisis:
                st.write("Prompt Analysis:")
                st.write(analisis)
                
                no_count = 0
                yes_count = 0
                total_count = 0
                
                for line in analisis.split('\n'):
                    if 'Present:' in line or 'Presente:' in line:
                        total_count += 1
                        if 'Present: No' in line or 'Presente: No' in line:
                            no_count += 1
                        elif any(affirmative in line for affirmative in ['Present: Yes', 'Presente: Yes', 'Presente: Sí', 'Presente: Si']):
                            yes_count += 1
                
                if total_count == 0:
                    total_count = sum(1 for line in analisis.split('\n') if any(keyword in line for keyword in ['Feedback:', 'Comentarios:']))
                
                if total_count > 0:
                    st.subheader("Agent Prompt Scorecard")
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Satisfactory Aspects", yes_count)
                    col2.metric("Areas for Improvement", no_count)
                    col3.metric("Total Aspects", total_count)
                    
                    if no_count > 0:
                        st.error(f"{no_count} out of {total_count}  aspects that need improvement were found in the agent's prompt. Please modify the prompt and try again.")
                        return
                    elif yes_count == total_count:
                        st.success(f"All {total_count} aspects of the prompt are satisfactory. Proceeding with the analysis.")
                    else:
                        st.warning(f"{total_count} aspects were evaluated in the prompt analysis, but {total_count - yes_count} aspects are not clearly marked as satisfactory. Please review the prompt and consider improving it before proceeding.")
                        if st.button("Proceed anyway"):
                            st.success("Proceeding with the analysis despite the warnings.")
                        else:
                            return
                else:
                    st.warning("No se encontraron aspectos evaluados en el análisis del prompt. Verifique la función de análisis.")
                    return
            else:
                st.error("No se pudo realizar el análisis del prompt.")
                return
    else:
        st.error("No se pudo obtener el prompt del agente seleccionado.")
        return

    url_docs = st.text_input("Enter the documentation URL:")
    if st.button("Analyze"):
        if not url_docs:
            st.error("Invalid URL. Please enter a valid documentation URL.")
            return

        links = extract_links(url_docs)
        if not links:
            st.error("No se pudieron extraer enlaces de la URL proporcionada.")
            return

        preguntas_generadas = set()
        resultados = []

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(procesar_enlace, link, url_docs, preguntas_generadas) for link in links]
            
            for future in as_completed(futures):
                result = future.result()
                if result:
                    pregunta, enlace_corregido = result
                    preguntas_generadas.add(pregunta)
                    
                    with st.expander(f"Question {len(preguntas_generadas)}"):
                        st.write(f"**Question:** {pregunta}")
                        st.write(f"**Link:** {enlace_corregido}")
                        respuesta, response_time = obtener_respuesta(agent_id, pregunta)
                        st.write(f"**Answer ({agent_name}):** {respuesta}")
                        st.write(f"**Time, Evaluation of Response:** {response_time:.2f} s")
                        
                        evaluacion_estructura = evaluar_estructura(prompt, respuesta, pregunta)
                        if evaluacion_estructura:
                            st.write("**Evaluation of Response Structure (raw):**")
                            st.code(evaluacion_estructura)
                            
                            resultados_estructura, feedback_estructura = analizar_evaluacion_estructura(evaluacion_estructura)
                            
                            if resultados_estructura:
                                st.write("**Structure Evaluation Results:**")
                                st.json(resultados_estructura)
                                
                                st.write("**Feedback:**")
                                st.json(feedback_estructura)
                                
                                for componente, presente in resultados_estructura.items():
                                    st.write(f"{componente}: {presente}")
                                
                                # Calcular y mostrar puntaje del agente de estructura
                                estructura_yes_count = sum(1 for r in resultados_estructura.values() if r.lower() == 'yes')
                                estructura_total = len([r for r in resultados_estructura.values() if r.lower() != 'n/a'])
                                st.write(f"Agent Structure Score: {estructura_yes_count}/{estructura_total}")
                            else:
                                st.warning("No se pudieron extraer resultados estructurados de la evaluación.")
                                st.write("Evaluación completa:")
                                st.write(evaluacion_estructura)
                        else:
                            st.error("No se pudo evaluar la estructura de la respuesta.")

                        resultado = {
                            "Question": pregunta,
                            "Link": enlace_corregido,
                            "Answer": respuesta,
                            "Response Time (s)": response_time,
                            "Structure Score": f"{estructura_yes_count}/{estructura_total}" if 'estructura_yes_count' in locals() else "N/A",
                            "Role": resultados_estructura.get('Role', 'N/A') if resultados_estructura else 'N/A',
                            "Format": resultados_estructura.get('Format', 'N/A') if resultados_estructura else 'N/A',
                            "Context": resultados_estructura.get('Context', 'N/A') if resultados_estructura else 'N/A',
                            "Error Handling": resultados_estructura.get('Error Handling', 'N/A') if resultados_estructura else 'N/A'
                        }
                        resultados.append(resultado)
                    
                    # Generar cuadro de puntajes después de cada verificación
                    df_resultados = pd.DataFrame(resultados)
                    st.subheader(f"Summary of Results (Question {len(preguntas_generadas)})")
                    st.dataframe(df_resultados)
                
                if len(preguntas_generadas) >= 1:
                    break

        if resultados:
            st.subheader("Estadísticas Finales")
            
            tiempo_promedio = df_resultados['Tiempo de respuesta (s)'].mean()
            st.write(f"Tiempo de respuesta promedio: {tiempo_promedio:.2f} segundos")

            # Calcular el puntaje promedio de estructura
            puntajes_estructura = df_resultados['Puntaje de estructura'].apply(lambda x: int(x.split('/')[0]) / int(x.split('/')[1]) if x != 'N/A' else 0)
            puntaje_promedio = puntajes_estructura.mean()
            st.write(f"Puntaje promedio de estructura: {puntaje_promedio:.2f}")

            # Calcular porcentajes de componentes presentes
            for componente in ['Role', 'Format', 'Context', 'Error Handling']:
                presencia = (df_resultados[componente] == 'Yes').mean() * 100
                st.write(f"Porcentaje de '{componente}' presente: {presencia:.2f}%")

            # Crear un gráfico de barras para visualizar los porcentajes
            import plotly.graph_objects as go

            fig = go.Figure(data=[
                go.Bar(name='Porcentaje de presencia', 
                       x=['Role', 'Format', 'Context', 'Error Handling'],
                       y=[(df_resultados[comp] == 'Yes').mean() * 100 for comp in ['Role', 'Format', 'Context', 'Error Handling']])
            ])
            fig.update_layout(title='Porcentaje de presencia de componentes',
                              yaxis_title='Porcentaje',
                              yaxis_range=[0, 100])
            st.plotly_chart(fig)

            csv = df_resultados.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download results as CSV",
                data=csv,
                file_name='resultados.csv',
                mime='text/csv',
            )
            
            excel_buffer = io.BytesIO()
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                df_resultados.to_excel(writer, index=False, sheet_name='Resultados')
            excel_buffer.seek(0)
            
            st.download_button(
                label="Download results as Excel",
                data=excel_buffer,
                file_name='resultados.xlsx',
                mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            )
        else:
            st.warning("No se generaron resultados.")

if __name__ == "__main__":
    main()

