import os
from dotenv import load_dotenv
import requests
import re

load_dotenv()

API_URL = "https://api.codegpt.co/api/v1/chat/completions"
API_KEY = os.getenv("CODEGPT_API_KEY")
ORG_ID = os.getenv("CODEGPT_ORG_ID")
AGENT_ESTRUCTURA_ID = "8b76e008-13f7-46e2-bbd5-f8c879223c84"

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "CodeGPT-Org-Id": ORG_ID
}

def evaluar_estructura(prompt_agente, respuesta, pregunta):
    payload = {
        "agentId": AGENT_ESTRUCTURA_ID,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "content": f"Evaluate the following response based on the agent's prompt:\n\nAgent Prompt: {prompt_agente}\n\nQuestion: {pregunta}\n\nResponse: {respuesta}\n\nProvide a detailed evaluation following the structure specified in your training.",
                "role": "user"
            }
        ]
    }

    try:
        response = requests.post(API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        evaluacion = response.json()['choices'][0]['message']['content']
        return evaluacion
    except requests.RequestException as e:
        print(f"Error evaluating structure: {e}")
        return None

def analizar_evaluacion_estructura(evaluacion):
    if evaluacion is None:
        return {}, {}

    componentes = ['Role', 'Format', 'Context', 'Error Handling']
    resultados = {}
    feedback = {}

    # Eliminar completamente las secciones no deseadas
    evaluacion = re.sub(r'(?s)Feedback detallado de la estructura:.*', '', evaluacion)
    evaluacion = re.sub(r'(?s)Summary:\s*Summary:.*', '', evaluacion)

    for componente in componentes:
        match = re.search(rf'{componente}:\s*\n\*\s*Present:\s*(Yes|No)\s*\n\*\s*Feedback:(.*?)(?=\n\n|\Z)', evaluacion, re.DOTALL)
        if match:
            resultados[componente] = match.group(1)
            feedback[componente] = match.group(2).strip()

    # Extraer el resumen
    match = re.search(r'Summary:(.*?)(?=\n\n|\Z)', evaluacion, re.DOTALL)
    if match:
        feedback['Summary'] = match.group(1).strip()

    return resultados, feedback