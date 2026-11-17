from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional, List
from pydantic import BaseModel

from app.database import supabase
from app.dependencies.auth import verify_firebase_token

router = APIRouter(prefix="/horarios", tags=["Horários"])


class HorarioCreate(BaseModel):
    coordinator_id: int
    dia_semana: int
    hora_inicio: str
    duracao_min: int
    tipo: Optional[str] = "Atendimento"


class HorarioResponse(BaseModel):
    id: int
    coordinator_id: int
    dia_semana: int
    hora_inicio: str
    duracao_min: int
    hora_fim: Optional[str] = None
    tipo: str

    class Config:
        from_attributes = True


def _tipo_usuario(usuario: dict) -> str:
    bruto = (usuario.get("tipo") or usuario.get("perfil") or "").strip().lower()
    if bruto in ("apoio", "nao_aluno", "não aluno", "suporte"):
        return "suporte"
    return bruto


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


def _validar_acesso(usuario: dict, coordinator_id: int) -> None:
    tipo = _tipo_usuario(usuario)
    if tipo == "suporte":
        return
    if tipo != "coordenador":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas coordenador ou suporte podem gerenciar horários.",
        )
    if coordinator_id != usuario.get("id"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Coordenador só pode gerenciar os próprios horários.",
        )


def _somar_minutos(hora_str: str, minutos: int) -> Optional[str]:
    try:
        partes = hora_str.split(":")
        h = int(partes[0])
        m = int(partes[1])
        total = h * 60 + m + minutos
        if total < 0 or total > 24 * 60:
            return None
        nh = (total // 60) % 24
        nm = total % 60
        return f"{nh:02d}:{nm:02d}"
    except Exception:
        return None


@router.get("", response_model=List[HorarioResponse])
def listar_horarios(
    coordinator_id: Optional[int] = None,
    token_data: dict = Depends(verify_firebase_token)
):
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)

    if tipo == "coordenador":
        coordinator_id = usuario.get("id")
    elif tipo != "suporte":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas coordenador ou suporte podem consultar horários.",
        )

    query = supabase.table("horarios").select("*")
    if coordinator_id is not None:
        query = query.eq("coordinator_id", coordinator_id)
    resultado = query.execute()
    return resultado.data or []


@router.post("", response_model=HorarioResponse, status_code=status.HTTP_201_CREATED)
def criar_horario(
    horario: HorarioCreate,
    token_data: dict = Depends(verify_firebase_token)
):
    usuario = _get_usuario_logado(token_data)
    _validar_acesso(usuario, horario.coordinator_id)
    hora_fim = _somar_minutos(horario.hora_inicio, horario.duracao_min)

    payload = {
        "coordinator_id": horario.coordinator_id,
        "dia_semana": horario.dia_semana,
        "hora_inicio": horario.hora_inicio,
        "duracao_min": horario.duracao_min,
        "hora_fim": hora_fim,
        "tipo": horario.tipo or "Atendimento",
    }

    resultado = (
        supabase
        .table("horarios")
        .insert(payload)
        .execute()
    )
    dados = resultado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível criar o horário."
        )
    return dados[0]


@router.patch("/{horario_id}", response_model=HorarioResponse)
def atualizar_horario(
    horario_id: int,
    horario: HorarioCreate,
    token_data: dict = Depends(verify_firebase_token)
):
    existente = (
        supabase
        .table("horarios")
        .select("*")
        .eq("id", horario_id)
        .execute()
    )
    if not existente.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Horário não encontrado."
        )

    usuario = _get_usuario_logado(token_data)
    _validar_acesso(usuario, existente.data[0]["coordinator_id"])
    _validar_acesso(usuario, horario.coordinator_id)

    hora_fim = _somar_minutos(horario.hora_inicio, horario.duracao_min)

    payload = {
        "coordinator_id": horario.coordinator_id,
        "dia_semana": horario.dia_semana,
        "hora_inicio": horario.hora_inicio,
        "duracao_min": horario.duracao_min,
        "hora_fim": hora_fim,
        "tipo": horario.tipo or "Atendimento",
    }

    atualizado = (
        supabase
        .table("horarios")
        .update(payload)
        .eq("id", horario_id)
        .execute()
    )
    dados = atualizado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível atualizar o horário."
        )
    return dados[0]


@router.delete("/{horario_id}", status_code=status.HTTP_204_NO_CONTENT)
def remover_horario(
    horario_id: int,
    token_data: dict = Depends(verify_firebase_token)
):
    existente = (
        supabase
        .table("horarios")
        .select("*")
        .eq("id", horario_id)
        .execute()
    )
    if not existente.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Horário não encontrado."
        )

    usuario = _get_usuario_logado(token_data)
    _validar_acesso(usuario, existente.data[0]["coordinator_id"])

    supabase.table("horarios").delete().eq("id", horario_id).execute()
    return None