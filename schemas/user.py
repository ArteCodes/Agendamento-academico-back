from pydantic import BaseModel, EmailStr
from typing import Optional

class UserResponse(BaseModel):
    id: int
    nome: str
    email: EmailStr
    perfil: str  # 'Aluno', 'Apoio' ou 'Coordenador'
    matricula: Optional[str] = None

    class Config:
        from_attributes = True