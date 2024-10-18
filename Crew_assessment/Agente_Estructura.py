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

        # Actualización para manejar el campo 'completion' en lugar de 'content'
        response_json = response.json()
        completion = response_json.get('choices', [{}])[0].get('message', {}).get('completion', None)

        if completion:
            return completion
        else:
            return f"No se encontró el campo completion. Respuesta completa: {response_json}"

    except requests.RequestException as e:
        print(f"Error evaluating structure: {e}")
        return None
