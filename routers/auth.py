from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db  # Sua função para obter a sessão da BD
from app.dependencies.auth import verify_firebase_token
from app.schemas.user import UserResponse
from app.models.user import User  # Seu modelo SQLAlchemy do utilizador

router = APIRouter(prefix="/routers/auth", tags=["Autenticação"])

@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    token_data: dict = Depends(verify_firebase_token),
    db: Session = Depends(get_db)
):
    # O email do utilizador autenticado vem no token decodificado do Firebase
    user_email = token_data.get("email")
    
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O token não contém um e-mail válido."
        )

    # Procura o utilizador na sua base de dados PostgreSQL pelo e-mail
    user = db.query(User).filter(User.email == user_email).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utilizador não registado no banco de dados."
        )

    return user