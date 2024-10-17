# Lista_Agentes.py

import os
from dotenv import load_dotenv
import requests

load_dotenv()

API_URL = "https://api.codegpt.co/api/v1/agent"
API_KEY = os.getenv("CODEGPT_API_KEY")
ORG_ID = os.getenv("CODEGPT_ORG_ID")

headers = {
    "accept": "application/json",
    "Authorization": f"Bearer {API_KEY}",
    "CodeGPT-Org-Id": ORG_ID
}

def obtener_agentes():
    try:
        response = requests.get(API_URL, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error obtaining agents: {e}")
        return []

def imprimir_agentes(agentes):
    if not agentes:
        print("No agents found.")
        return

    for agent in agentes:
        print(f"ID: {agent['id']}")
        print(f"Name: {agent['name']}")
        print(f"Agent type: {agent['agent_type']}")
        print(f"Model: {agent['model']}")
        print(f"Is public: {agent['is_public']}")
        print(f"Created at: {agent['created_at']}")
        print(f"Welcome message: {agent['welcome']}")
        print("---")

def obtener_nombre_agente(agent_id, agentes):
    for agente in agentes:
        if agente['id'] == agent_id:
            return agente['name']
    return "Unknown Agent"