from typing import List

from fastapi import APIRouter, HTTPException, status

from app.database import supabase
from app.schemas.user import UsuarioCreate, UsuarioResponse

router = APIRouter(tags=["Usuarios"])


@router.get("/usuarios", response_model=List[UsuarioResponse])
def listar_usuarios():
    try:
        resultado = (
            supabase
            .table("usuarios")
            .select("*")
            .execute()
        )
        return resultado.data

    except Exception as erro:
        raise HTTPException(
            status_code=500,
            detail=str(erro)
        )


@router.post("/usuarios", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def criar_usuario(usuario: UsuarioCreate):
    try:
        payload = usuario.model_dump(exclude_none=True)
        resultado = (
            supabase
            .table("usuarios")
            .insert(payload)
            .execute()
        )
        return resultado.data[0]

    except Exception as erro:
        raise HTTPException(
            status_code=500,
            detail=str(erro)
        )
