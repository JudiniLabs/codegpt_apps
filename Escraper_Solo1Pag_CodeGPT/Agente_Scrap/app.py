import streamlit as st
import os
from escrapeador import scrape_url, analyze_content, analyze_with_codegpt, extract_api_endpoints, extract_tables

# Configuración de la página de Streamlit
st.set_page_config(page_title="Web Content Analyzer", page_icon="🌐", layout="wide")

# Título y descripción
st.title("🌐 Web Content Analyzer")
st.markdown("Esta aplicación analiza el contenido de una página web, elimina elementos no esenciales y procesa el texto utilizando CodeGPT.")

# Input para la URL
url = st.text_input("Ingrese la URL de la página web a analizar:")

if st.button("Analizar"):
    if url:
        with st.spinner("Analizando el contenido..."):
            # Proceso de análisis
            html_content = scrape_url(url)
            if html_content:
                filtered_content = analyze_content(html_content)
                analyzed_content = analyze_with_codegpt(filtered_content)
                
                if analyzed_content:
                    # Mostrar resultados
                    st.success("Análisis completado con éxito!")
                    
                    # Contenido principal
                    st.subheader("Contenido Analizado:")
                    st.text_area("", value=analyzed_content, height=300)
                    
                    # API Endpoints
                    api_endpoints = extract_api_endpoints(html_content)
                    if api_endpoints:
                        st.subheader("API Endpoints:")
                        for endpoint in api_endpoints:
                            st.text(endpoint)
                    
                    # Tablas
                    tables = extract_tables(html_content)
                    if tables:
                        st.subheader("Tablas Extraídas:")
                        for i, table in enumerate(tables, 1):
                            st.write(f"Tabla {i}:")
                            st.table(table)
                    
                    # Opción para descargar el resultado
                    full_content = analyzed_content + "\n\n"
                    if api_endpoints:
                        full_content += "API Endpoints:\n" + "\n".join(api_endpoints) + "\n\n"
                    if tables:
                        full_content += "Tables:\n"
                        for i, table in enumerate(tables, 1):
                            full_content += f"\nTable {i}:\n"
                            for row in table:
                                full_content += " | ".join(row) + "\n"
                            full_content += "\n"
                    
                    st.download_button(
                        label="Descargar resultado completo",
                        data=full_content,
                        file_name="analyzed_content.txt",
                        mime="text/plain"
                    )
                else:
                    st.error("No se pudo analizar el contenido. Por favor, intente nuevamente.")
            else:
                st.error("No se pudo acceder al contenido de la URL proporcionada.")
    else:
        st.warning("Por favor, ingrese una URL válida.")

# Información adicional
st.sidebar.header("Acerca de")
st.sidebar.info(
    "Esta aplicación utiliza web scraping y procesamiento de lenguaje natural "
    "para analizar y limpiar el contenido de páginas web. Desarrollada por CodeGPT."
)

# Footer
st.markdown("---")
st.markdown("Desarrollado con ❤️ por CodeGPT")
