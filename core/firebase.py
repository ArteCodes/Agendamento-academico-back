import os
import firebase_admin
from firebase_admin import credentials

# Caminho para o ficheiro JSON baixado no Passo 2
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "firebase-credentials.json")

if not firebase_admin._apps:
    cred = credentials.Certificate(CREDENTIALS_PATH)
    firebase_admin.initialize_app(cred)