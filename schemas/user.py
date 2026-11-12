from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserResponse(BaseModel):
    id: int
    nome: str
    email: EmailStr
    perfil: str  # 'Aluno', 'Apoio' ou 'Coordenador'
    matricula: Optional[str] = None

    class Config:
        from_attributes = True


class UsuarioBase(BaseModel):
    nome: str
    matricula: str
    tipo_usuario: str
    curso_id: int


class UsuarioCreate(UsuarioBase):
    pass


class UsuarioResponse(UsuarioBase):
    id: Optional[int] = None
    criado_em: Optional[datetime] = None

    class Config:
        from_attributes = True
