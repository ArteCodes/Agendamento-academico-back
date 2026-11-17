import os
import logging
import firebase_admin
from firebase_admin import credentials

logger = logging.getLogger(__name__)

# app/ (pasta pai de core/)
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# raiz do repositório (pasta pai de app/)
PROJECT_DIR = os.path.dirname(APP_DIR)


def _resolver_credenciais() -> str:
    """Aceita caminho absoluto, relativo à raiz ou relativo à pasta app/."""
    bruto = os.getenv("FIREBASE_CREDENTIALS")
    candidatos = []

    if bruto:
        if os.path.isabs(bruto):
            candidatos.append(bruto)
        else:
            candidatos.append(os.path.join(PROJECT_DIR, bruto))
            candidatos.append(os.path.join(APP_DIR, bruto))

    # Padrão do projeto: app/core/firebase-credentials.json
    candidatos.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "firebase-credentials.json"))

    for caminho in candidatos:
        if os.path.exists(caminho):
            return caminho

    return candidatos[-1]


CREDENTIALS_PATH = _resolver_credenciais()

if not os.path.exists(CREDENTIALS_PATH):
    mensagem = (
        f"Arquivo de credenciais do Firebase não encontrado: {CREDENTIALS_PATH}. "
        "Gere uma nova chave privada no Firebase Console (Project Settings > Service Accounts > "
        "Generate new private key) e salve-a como firebase-credentials.json na pasta app/core/."
    )
    logger.error(mensagem)
    raise FileNotFoundError(mensagem)

if not firebase_admin._apps:
    cred = credentials.Certificate(CREDENTIALS_PATH)
    firebase_admin.initialize_app(cred)
    logger.info("Firebase Admin SDK inicializado com sucesso.")
