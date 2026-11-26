from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from typing import Literal, Optional
from pydantic import BaseModel, Field

from app.database import supabase
from app.dependencies.auth import verify_firebase_token
from app.services import notificacoes as notificacoes_service

router = APIRouter(prefix="/agendamentos", tags=["Agendamentos"])

STATUS_FINAIS = ("Cancelado", "Redirecionado", "Concluído")


class AgendamentoCreate(BaseModel):
    aluno: Optional[str] = None
    alunoEmail: Optional[str] = None
    aluno_matricula: Optional[str] = None
    coordinator_id: Optional[int] = None
    nome: str
    data: str
    horario: str
    descricao: Optional[str] = None
    curso: Optional[str] = None
    periodo: Optional[str] = None
    turma: Optional[str] = None
    telefone: Optional[str] = None


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
    status: str
    descricao: Optional[str] = None
    curso: Optional[str] = None
    periodo: Optional[str] = None
    turma: Optional[str] = None
    telefone: Optional[str] = None

    class Config:
        from_attributes = True


class DesvalidarAgendamento(BaseModel):
    status: Literal["Cancelado", "Redirecionado"]
    observacao: str = Field(min_length=1, max_length=2000)


class AlterarStatusAgendamento(BaseModel):
    status: Literal["Pendente", "Confirmado", "Concluído", "Cancelado", "Redirecionado"]
    observacao: str = Field(min_length=1, max_length=2000)


class ObservacaoResponse(BaseModel):
    id: int
    agendamento_id: int
    usuario_id: Optional[int] = None
    usuario_nome: Optional[str] = None
    status_anterior: Optional[str] = None
    status_novo: str
    observacao: str
    criado_em: str


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


def _pode_gerenciar_agendamento(usuario: dict, agendamento: dict) -> bool:
    """
    Regra de gestão (confirmar/alterar status):
    - suporte: qualquer agendamento;
    - coordenador: apenas os destinados a ele (coordinator_id);
    - aluno: não gerencia.
    """
    tipo = _tipo_usuario(usuario)
    if tipo == "suporte":
        return True
    if tipo == "coordenador":
        return agendamento.get("coordinator_id") == usuario.get("id")
    return False


def _pode_ver_agendamento(usuario: dict, agendamento: dict) -> bool:
    """
    Regra de visibilidade:
    - suporte: todos os agendamentos;
    - aluno: apenas os próprios (criador, matrícula ou e-mail);
    - coordenador: apenas os destinados a ele (coordinator_id).
    """
    tipo = _tipo_usuario(usuario)
    user_id = usuario.get("id")

    if tipo == "suporte":
        return True
    if tipo == "aluno":
        matricula = usuario.get("matricula")
        email = (usuario.get("email") or "").lower()
        return (
            agendamento.get("created_by") == user_id
            or (matricula and agendamento.get("aluno_matricula") == matricula)
            or (agendamento.get("alunoEmail") or "").lower() == email
        )
    if tipo == "coordenador":
        return agendamento.get("coordinator_id") == user_id
    return False


def _resultado_rpc(resposta) -> dict:
    resultado = resposta.data
    if isinstance(resultado, list):
        resultado = resultado[0] if resultado else {}
    return resultado or {}


def _executar_alteracao_status(
    agendamento_id: int,
    usuario: dict,
    novo_status: str,
    observacao: str,
) -> dict:
    """Executa a RPC de alteração de status e traduz os erros para HTTP."""
    try:
        resposta = supabase.rpc(
            "alterar_status_agendamento",
            {
                "p_agendamento_id": agendamento_id,
                "p_usuario_id": usuario.get("id"),
                "p_status": novo_status,
                "p_observacao": observacao,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 - devolve erro controlado ao frontend
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Não foi possível alterar o status do agendamento: {exc}",
        ) from exc

    resultado = _resultado_rpc(resposta)
    if resultado.get("id"):
        return resultado

    motivo = resultado.get("motivo")
    if motivo == "nao_encontrado":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agendamento não encontrado.",
        )
    if motivo == "mesmo_status":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O novo status deve ser diferente do status atual.",
        )
    if motivo == "finalizado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este agendamento está concluído e não pode ser alterado.",
        )
    if motivo == "transicao_invalida":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível concluir um agendamento confirmado.",
        )
    if motivo == "slot_ocupado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "O horário deste agendamento já está ocupado por outro "
                "agendamento ativo. Cancele o outro agendamento antes de reativar."
            ),
        )
    if motivo in ("status_invalido", "observacao_obrigatoria"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dados inválidos para alterar o status do agendamento.",
        )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Não foi possível alterar o status do agendamento.",
    )


def _observacao_automatica(usuario: dict, acao: str) -> str:
    nome = (usuario.get("nome") or usuario.get("email") or "Usuário").strip()
    return f"{acao} por {nome}."


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
        # Suporte acompanha todos os agendamentos do sistema.
        filtrados = todos
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

    if not _pode_ver_agendamento(usuario, agendamento):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para visualizar este agendamento.",
        )
    return agendamento


@router.get("/{agendamento_id}/observacoes", response_model=list[ObservacaoResponse])
def listar_observacoes(
    agendamento_id: int,
    token_data: dict = Depends(verify_firebase_token),
):
    """Histórico de desvalidações/cancelamentos com a justificativa de cada autor."""
    agendamento = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)

    if not _pode_ver_agendamento(usuario, agendamento):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para visualizar as observações deste agendamento.",
        )

    resultado = (
        supabase
        .table("agendamentos_observacoes")
        .select("*")
        .eq("agendamento_id", agendamento_id)
        .order("criado_em", desc=True)
        .execute()
    )
    observacoes = resultado.data or []

    ids_usuarios = {
        item.get("usuario_id")
        for item in observacoes
        if item.get("usuario_id") is not None
    }
    nomes: dict[int, Optional[str]] = {}
    if ids_usuarios:
        usuarios = (
            supabase
            .table("usuarios")
            .select("id,nome")
            .in_("id", list(ids_usuarios))
            .execute()
        )
        nomes = {u["id"]: u.get("nome") for u in (usuarios.data or [])}

    return [
        {**item, "usuario_nome": nomes.get(item.get("usuario_id"))}
        for item in observacoes
    ]


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
        "status": "Pendente",
        "descricao": agendamento.descricao,
        "curso": agendamento.curso,
        "periodo": agendamento.periodo,
        "turma": agendamento.turma,
        "telefone": agendamento.telefone,
    }

    resultado = supabase.table("agendamentos").insert(payload).execute()
    dados = resultado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível criar o agendamento.",
        )
    criado = dados[0]
    notificacoes_service.notificar_agendamento_pendente(criado, usuario)
    return criado


@router.patch("/{agendamento_id}", response_model=AgendamentoResponse)
def cancelar_agendamento(
    agendamento_id: int,
    background: BackgroundTasks,
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
    elif tipo == "coordenador":
        # Coordenador cancela apenas os agendamentos destinados a ele.
        pode_editar = ag.get("coordinator_id") == user_id
    elif tipo == "suporte":
        # Suporte pode cancelar qualquer agendamento.
        pode_editar = True

    if not pode_editar:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para cancelar este agendamento.",
        )

    if ag.get("status") in STATUS_FINAIS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este agendamento já está finalizado.",
        )

    observacao = _observacao_automatica(usuario, "Cancelado")
    resultado = _executar_alteracao_status(
        agendamento_id,
        usuario,
        "Cancelado",
        observacao,
    )
    notificacoes_service.notificar_mudanca_status(
        agendamento=ag,
        status_anterior=ag.get("status"),
        status_novo="Cancelado",
        ator=usuario,
        background=background,
        observacao=observacao,
    )
    return resultado


@router.patch("/{agendamento_id}/validar", response_model=AgendamentoResponse)
def validar_agendamento(
    agendamento_id: int,
    background: BackgroundTasks,
    token_data: dict = Depends(verify_firebase_token),
):
    agendamento = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)

    if not _pode_gerenciar_agendamento(usuario, agendamento):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para validar este agendamento.",
        )

    if agendamento.get("status") != "Pendente":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível confirmar agendamentos pendentes.",
        )

    observacao = _observacao_automatica(usuario, "Confirmado")
    resultado = _executar_alteracao_status(
        agendamento_id,
        usuario,
        "Confirmado",
        observacao,
    )
    notificacoes_service.notificar_mudanca_status(
        agendamento=agendamento,
        status_anterior="Pendente",
        status_novo="Confirmado",
        ator=usuario,
        background=background,
        observacao=observacao,
    )
    return resultado


@router.patch("/{agendamento_id}/desvalidar", response_model=AgendamentoResponse)
def desvalidar_agendamento(
    agendamento_id: int,
    dados: DesvalidarAgendamento,
    background: BackgroundTasks,
    token_data: dict = Depends(verify_firebase_token),
):
    """
    Muda o status para Cancelado ou Redirecionado e registra a justificativa
    junto com o id do usuário que realizou a alteração (transação no banco).
    """
    agendamento = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)
    user_id = usuario.get("id")

    if not _pode_gerenciar_agendamento(usuario, agendamento):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para desvalidar este agendamento.",
        )

    if agendamento.get("status") in STATUS_FINAIS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Este agendamento já está finalizado.",
        )

    observacao = dados.observacao.strip()
    if not observacao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe uma observação justificando a alteração.",
        )

    try:
        resposta = supabase.rpc(
            "desvalidar_agendamento",
            {
                "p_agendamento_id": agendamento_id,
                "p_usuario_id": user_id,
                "p_status": dados.status,
                "p_observacao": observacao,
            },
        ).execute()
    except Exception as exc:  # noqa: BLE001 - devolve erro controlado ao frontend
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Não foi possível desvalidar o agendamento: {exc}",
        ) from exc

    resultado = resposta.data
    if isinstance(resultado, list):
        resultado = resultado[0] if resultado else {}
    resultado = resultado or {}

    if not resultado or not resultado.get("id"):
        motivo = resultado.get("motivo")
        if motivo == "finalizado":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Este agendamento já está finalizado.",
            )
        if motivo == "nao_encontrado":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agendamento não encontrado.",
            )
        if motivo in ("status_invalido", "observacao_obrigatoria"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dados inválidos para desvalidar o agendamento.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível desvalidar o agendamento.",
        )
    notificacoes_service.notificar_mudanca_status(
        agendamento=agendamento,
        status_anterior=agendamento.get("status"),
        status_novo=dados.status,
        ator=usuario,
        background=background,
        observacao=observacao,
    )
    return resultado


@router.patch("/{agendamento_id}/status", response_model=AgendamentoResponse)
def alterar_status_agendamento(
    agendamento_id: int,
    dados: AlterarStatusAgendamento,
    background: BackgroundTasks,
    token_data: dict = Depends(verify_firebase_token),
):
    """
    Altera o status de um agendamento (inclusive reverter Cancelado/Redirecionado)
    e registra a justificativa no histórico de alterações.
    """
    agendamento = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)
    user_id = usuario.get("id")

    if not _pode_gerenciar_agendamento(usuario, agendamento):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para alterar o status deste agendamento.",
        )

    if dados.status == agendamento.get("status"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O novo status deve ser diferente do status atual.",
        )

    observacao = dados.observacao.strip()
    if not observacao:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe uma observação justificando a alteração.",
        )

    resultado = _executar_alteracao_status(
        agendamento_id,
        usuario,
        dados.status,
        observacao,
    )
    notificacoes_service.notificar_mudanca_status(
        agendamento=agendamento,
        status_anterior=agendamento.get("status"),
        status_novo=dados.status,
        ator=usuario,
        background=background,
        observacao=observacao,
    )
    return resultado


@router.patch("/{agendamento_id}/concluir", response_model=AgendamentoResponse)
def concluir_agendamento(
    agendamento_id: int,
    background: BackgroundTasks,
    token_data: dict = Depends(verify_firebase_token),
):
    """Marca um agendamento confirmado como atendimento realizado (definitivo)."""
    agendamento = _buscar_agendamento(agendamento_id)
    usuario = _get_usuario_logado(token_data)

    if not _pode_gerenciar_agendamento(usuario, agendamento):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Você não tem permissão para concluir este agendamento.",
        )

    if agendamento.get("status") != "Confirmado":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Só é possível concluir um agendamento confirmado.",
        )

    observacao = _observacao_automatica(usuario, "Atendimento marcado como realizado")
    resultado = _executar_alteracao_status(
        agendamento_id,
        usuario,
        "Concluído",
        observacao,
    )
    notificacoes_service.notificar_mudanca_status(
        agendamento=agendamento,
        status_anterior="Confirmado",
        status_novo="Concluído",
        ator=usuario,
        background=background,
        observacao=observacao,
    )
    return resultado
