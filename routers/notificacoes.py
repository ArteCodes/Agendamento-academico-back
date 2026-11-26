"""Notificações do usuário logado (sino do header)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import supabase
from app.dependencies.auth import verify_firebase_token

router = APIRouter(prefix="/notificacoes", tags=["Notificações"])


def _get_usuario_logado(token_data: dict) -> dict:
    user_email = token_data.get("email")
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O token não contém um e-mail válido.",
        )
    resultado = (
        supabase
        .table("usuarios")
        .select("*")
        .eq("email", user_email.strip().lower())
        .limit(1)
        .execute()
    )
    dados = resultado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuário não registrado no banco de dados.",
        )
    return dados[0]


def _contar_nao_lidas(usuario_id: int) -> int:
    resultado = (
        supabase
        .table("notificacoes")
        .select("id")
        .eq("usuario_id", usuario_id)
        .eq("lida", False)
        .execute()
    )
    return len(resultado.data or [])


@router.get("")
def listar_notificacoes(
    limite: int = Query(default=30, ge=1, le=100),
    apenas_nao_lidas: bool = False,
    token_data: dict = Depends(verify_firebase_token),
):
    usuario = _get_usuario_logado(token_data)
    consulta = (
        supabase
        .table("notificacoes")
        .select("*")
        .eq("usuario_id", usuario["id"])
    )
    if apenas_nao_lidas:
        consulta = consulta.eq("lida", False)

    resultado = (
        consulta.order("criado_em", desc=True).limit(limite).execute()
    )
    return {
        "notificacoes": resultado.data or [],
        "nao_lidas": _contar_nao_lidas(usuario["id"]),
    }


@router.patch("/lidas")
def marcar_todas_como_lidas(token_data: dict = Depends(verify_firebase_token)):
    usuario = _get_usuario_logado(token_data)
    (
        supabase
        .table("notificacoes")
        .update({"lida": True})
        .eq("usuario_id", usuario["id"])
        .eq("lida", False)
        .execute()
    )
    return {"ok": True, "nao_lidas": 0}


@router.patch("/{notificacao_id}/lida")
def marcar_notificacao_como_lida(
    notificacao_id: int,
    token_data: dict = Depends(verify_firebase_token),
):
    usuario = _get_usuario_logado(token_data)
    resultado = (
        supabase
        .table("notificacoes")
        .update({"lida": True})
        .eq("id", notificacao_id)
        .eq("usuario_id", usuario["id"])
        .execute()
    )
    dados = resultado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificação não encontrada.",
        )
    return dados[0]
