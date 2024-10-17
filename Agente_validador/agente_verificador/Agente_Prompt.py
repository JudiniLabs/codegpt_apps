import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://api.codegpt.co/api/v1/"
ANALIZADOR_ID = "ab91b866-da46-480b-9d17-19d7d4c6d208"  # ID del agente analizador

API_KEY = os.getenv("CODEGPT_API_KEY")
ORG_ID = os.getenv("CODEGPT_ORG_ID")

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "CodeGPT-Org-Id": ORG_ID
}

def obtener_prompt_agente(agent_id):
    try:
        response = requests.get(f"{API_URL}agent/{agent_id}", headers=headers)
        response.raise_for_status()
        agent_data = response.json()
        return agent_data.get('prompt', "No se encontró el prompt del agente.")
    except requests.RequestException as e:
        print(f"Error al obtener el prompt del agente: {e}")
        return None

def analizar_prompt(prompt):
    payload = {
        "agentId": ANALIZADOR_ID,
        "stream": False,
        "format": "json",
        "messages": [
            {
                "content": f"Analiza el siguiente prompt de un agente:\n\n{prompt}",
                "role": "user"
            }
        ]
    }
    
    try:
        response = requests.post(f"{API_URL}chat/completions", headers=headers, json=payload)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except requests.RequestException as e:
        print(f"Error al analizar el prompt: {e}")
        return None
    
