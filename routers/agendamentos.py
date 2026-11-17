from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional
from pydantic import BaseModel

from app.database import supabase
from app.dependencies.auth import verify_firebase_token

router = APIRouter(prefix="/agendamentos", tags=["Agendamentos"])


class AgendamentoCreate(BaseModel):
    aluno: Optional[str] = None
    alunoEmail: Optional[str] = None
    aluno_matricula: Optional[str] = None
    coordinator_id: Optional[int] = None
    nome: str
    data: str
    horario: str
    local: str
    descricao: Optional[str] = None


class AgendamentoResponse(BaseModel):
    id: int
    aluno: str
    alunoEmail: str
    aluno_matricula: Optional[str] = None
    created_by: Optional[int] = None
    coordinator_id: Optional[int] = None
    nome: str
    data: str
    horario: str
    local: str
    status: str
    descricao: Optional[str] = None

    class Config:
        from_attributes = True


def _tipo_usuario(usuario: dict) -> str:
    """Normaliza o perfil/tipo do usuário: aluno, coordenador ou suporte."""
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


def _coordenador_padrao() -> Optional[int]:
    """Retorna o primeiro coordenador cadastrado, usado quando o aluno não escolhe um."""
    resultado = (
        supabase.table("usuarios")
        .select("id")
        .eq("tipo", "coordenador")
        .order("id")
        .limit(1)
        .execute()
    )
    dados = resultado.data or []
    return dados[0]["id"] if dados else None


def _buscar_agendamento(agendamento_id: int) -> dict:
    resultado = (
        supabase
        .table("agendamentos")
        .select("*")
        .eq("id", agendamento_id)
        .limit(1)
        .execute()
    )
    dados = resultado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado.",
        )
    return dados[0]


@router.get("", response_model=list[AgendamentoResponse])
def listar_agendamentos(token_data: dict = Depends(verify_firebase_token)):
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)
    user_id = usuario.get("id")
    matricula = usuario.get("matricula")
    email = (usuario.get("email") or "").lower()

    resultado = supabase.table("agendamentos").select("*").order("data").execute()
    todos = resultado.data or []

    if tipo == "aluno":
        filtrados = [
            a for a in todos
            if a.get("created_by") == user_id
            or (matricula and a.get("aluno_matricula") == matricula)
            or (a.get("alunoEmail") or "").lower() == email
        ]
    elif tipo == "coordenador":
        filtrados = [a for a in todos if a.get("coordinator_id") == user_id]
    elif tipo == "suporte":
        filtrados = [a for a in todos if a.get("created_by") == user_id]
    else:
        filtrados = []

    return filtrados


@router.get("/{agendamento_id}", response_model=AgendamentoResponse)
def obter_agendamento(
    agendamento_id: int,
    token_data: dict = Depends(verify_firebase_token),
):
    agendamento = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)
    user_id = usuario.get("id")
    matricula = usuario.get("matricula")
    email = (usuario.get("email") or "").lower()

    if tipo == "aluno":
        permitido = (
            agendamento.get("created_by") == user_id
            or (matricula and agendamento.get("aluno_matricula") == matricula)
            or (agendamento.get("alunoEmail") or "").lower() == email
        )
    elif tipo == "coordenador":
        permitido = agendamento.get("coordinator_id") == user_id
    elif tipo == "suporte":
        permitido = agendamento.get("created_by") == user_id
    else:
        permitido = False

    if not permitido:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para visualizar este agendamento.",
        )
    return agendamento


@router.post("", response_model=AgendamentoResponse, status_code=status.HTTP_201_CREATED)
def criar_agendamento(
    agendamento: AgendamentoCreate,
    token_data: dict = Depends(verify_firebase_token),
):
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)
    user_id = usuario.get("id")
    matricula = usuario.get("matricula")
    email = (usuario.get("email") or "").lower()

    coordinator_id = agendamento.coordinator_id
    if tipo == "aluno":
        # O aluno não escolhe o coordenador; o backend atribui o coordenador padrão.
        coordinator_id = _coordenador_padrao()
    elif tipo == "coordenador":
        coordinator_id = user_id
    elif tipo == "suporte":
        coordinator_id = coordinator_id or _coordenador_padrao()

    payload = {
        "aluno": agendamento.aluno or usuario.get("nome") or email,
        "alunoEmail": (agendamento.alunoEmail or email).lower(),
        "aluno_matricula": agendamento.aluno_matricula or matricula,
        "created_by": user_id,
        "coordinator_id": coordinator_id,
        "nome": agendamento.nome,
        "data": agendamento.data,
        "horario": agendamento.horario,
        "local": agendamento.local,
        "status": "Pendente",
        "descricao": agendamento.descricao,
    }

    resultado = supabase.table("agendamentos").insert(payload).execute()
    dados = resultado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível criar o agendamento.",
        )
    return dados[0]


@router.patch("/{agendamento_id}", response_model=AgendamentoResponse)
def cancelar_agendamento(
    agendamento_id: int,
    token_data: dict = Depends(verify_firebase_token),
):
    ag = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)
    user_id = usuario.get("id")
    matricula = usuario.get("matricula")
    email = (usuario.get("email") or "").lower()

    pode_editar = False
    if tipo == "aluno":
        pode_editar = (
            ag.get("created_by") == user_id
            or (matricula and ag.get("aluno_matricula") == matricula)
            or (ag.get("alunoEmail") or "").lower() == email
        )
    elif tipo == "suporte":
        pode_editar = ag.get("created_by") == user_id

    if not pode_editar:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para cancelar este agendamento.",
        )

    atualizado = (
        supabase
        .table("agendamentos")
        .update({"status": "Cancelado"})
        .eq("id", agendamento_id)
        .execute()
    )
    dados_att = atualizado.data or []
    if not dados_att:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível cancelar o agendamento.",
        )
    return dados_att[0]


@router.patch("/{agendamento_id}/validar", response_model=AgendamentoResponse)
def validar_agendamento(
    agendamento_id: int,
    token_data: dict = Depends(verify_firebase_token),
):
    agendamento = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)
    user_id = usuario.get("id")

    if tipo == "coordenador":
        permitido = agendamento.get("coordinator_id") == user_id
    elif tipo == "suporte":
        permitido = agendamento.get("created_by") == user_id
    else:
        permitido = False

    if not permitido:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para validar este agendamento.",
        )

    atualizado = (
        supabase
        .table("agendamentos")
        .update({"status": "Confirmado"})
        .eq("id", agendamento_id)
        .execute()
    )
    dados_att = atualizado.data or []
    if not dados_att:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível validar o agendamento.",
        )
    return dados_att[0]
