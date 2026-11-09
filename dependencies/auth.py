from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from firebase_admin import auth
import app.core.firebase  # Garante que o Firebase está inicializado

security = HTTPBearer()

def verify_firebase_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """
    Decodifica e valida o ID Token do Firebase enviado pelo Vue.js no cabeçalho Authorization.
    """
    token = credentials.credentials
    try:
        # Decodifica o token enviado do Vue.js
        decoded_token = auth.verify_id_token(token)
        return decoded_token  # Retorna o dicionário com 'uid', 'email', etc.
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticação inválido ou expirado.",
            headers={"WWW-Authenticate": "Bearer"},
        )