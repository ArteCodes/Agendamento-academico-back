from pydantic import BaseModel
from typing import Optional

class User(BaseModel):
    id: Optional[int] = None
    nome: str
    email: str
    perfil: str  # 'Aluno', 'Apoio' ou 'Coordenador'
    matricula: Optional[str] = None