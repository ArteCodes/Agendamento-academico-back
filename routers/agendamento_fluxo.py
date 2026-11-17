"""
Router do novo fluxo de agendamento (5 telas).

Responsabilidades:
- listar coordenadores com cargo/foto (tabelas cargos e fotos_coordenadores);
- devolver os horários concretos dos próximos dias a partir dos horários semanais;
- criar/liberar bloqueios temporários com TTL;
- converter o bloqueio em agendamento definitivo de forma atômica (RPC).

As operações de escrita chamam funções Postgres (supabase/002_fluxo_agendamento.sql),
que garantem atomicidade e evitam condição de corrida entre usuários.
"""

import os
import uuid as uuid_lib
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.database import supabase
from app.dependencies.auth import verify_firebase_token

router = APIRouter(prefix="/agendamento-fluxo", tags=["Fluxo de Agendamento"])

# Mensagem exigida pelo fluxo (não alterar nenhum caractere).
MENSAGEM_HORARIO_OCUPADO = (
    "Ops... Parece que já ocuparam esse horario, volte e atualize a pagina "
    "para marcar um novo agendamento."
)

# Campo fora do formulário novo, mas obrigatório no schema atual de agendamentos.
NOME_ATENDIMENTO_PADRAO = "Atendimento com coordenador"

DIAS_PADRAO = 7
DIAS_MAXIMO = 14


class BloqueioCreate(BaseModel):
    coordinator_id: int
    data: date
    horario: str = Field(pattern=r"^\d{2}:\d{2}$")


class ConfirmacaoCreate(BaseModel):
    token: str = Field(min_length=36, max_length=36)
    nome: str = Field(min_length=2, max_length=200)
    matricula: str = Field(min_length=1, max_length=60)
    curso: str = Field(min_length=1, max_length=150)
    periodo: str = Field(min_length=1, max_length=60)
    turma: str = Field(min_length=1, max_length=60)
    telefone: str = Field(min_length=8, max_length=30)
    email: EmailStr
    descricao: str = Field(min_length=1, max_length=2000)


# -----------------------------------------------------------------------------
# Helpers (seguem o padrão dos routers existentes)
# -----------------------------------------------------------------------------
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


def _exigir_criador(usuario: dict) -> None:
    """Somente aluno ou suporte podem criar agendamentos (regra canCreate)."""
    if _tipo_usuario(usuario) not in ("aluno", "suporte"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas aluno ou suporte podem solicitar agendamentos.",
        )


def _buscar_coordenador(coordinator_id: int) -> dict:
    resultado = (
        supabase
        .table("usuarios")
        .select("id,nome,email,tipo,perfil")
        .eq("id", coordinator_id)
        .limit(1)
        .execute()
    )
    dados = resultado.data or []
    if not dados or _tipo_usuario(dados[0]) != "coordenador":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coordenador não encontrado.",
        )
    return dados[0]


def _ttl_minutos() -> int:
    """TTL do bloqueio em minutos (configurável, padrão 10)."""
    try:
        valor = int(os.getenv("AGENDAMENTO_LOCK_TTL_MINUTOS", "10"))
    except (TypeError, ValueError):
        valor = 10
    return max(1, min(valor, 60))


def _erro_slot_ocupado() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=MENSAGEM_HORARIO_OCUPADO,
    )


def _executar_rpc(nome: str, parametros: dict) -> dict:
    try:
        resposta = supabase.rpc(nome, parametros).execute()
    except Exception as exc:  # noqa: BLE001 - devolve erro controlado ao frontend
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Não foi possível executar a operação no banco de dados ({nome}): {exc}",
        ) from exc

    dados = resposta.data
    if isinstance(dados, list):
        dados = dados[0] if dados else {}
    return dados or {}


def _dia_semana_banco(dia: date) -> int:
    """Converte o dia da semana do Python (Seg=0) para o padrão do banco (Dom=0)."""
    return (dia.weekday() + 1) % 7


def _somar_minutos(hora_str: str, minutos: int) -> Optional[str]:
    try:
        h, m = (int(parte) for parte in str(hora_str).split(":")[:2])
        total = h * 60 + m + int(minutos)
        if total < 0 or total > 24 * 60:
            return None
        return f"{(total // 60) % 24:02d}:{total % 60:02d}"
    except (TypeError, ValueError):
        return None


def _horario_do_coordenador(coordinator_id: int, dia: date, horario: str) -> dict:
    """Confirma que o slot existe na grade semanal do coordenador."""
    resultado = (
        supabase
        .table("horarios")
        .select("id,hora_inicio,hora_fim,duracao_min,tipo")
        .eq("coordinator_id", coordinator_id)
        .eq("dia_semana", _dia_semana_banco(dia))
        .eq("hora_inicio", horario)
        .limit(1)
        .execute()
    )
    dados = resultado.data or []
    if not dados:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Horário não disponível para este coordenador.",
        )
    return dados[0]


def _validar_token(valor: str) -> str:
    try:
        return str(uuid_lib.UUID(str(valor)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token de bloqueio inválido.",
        ) from exc


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@router.get("/coordenadores")
def listar_coordenadores(token_data: dict = Depends(verify_firebase_token)):
    """Lista os coordenadores reais com cargo e foto fictícia (quando cadastrados)."""
    _get_usuario_logado(token_data)

    resultado = supabase.table("usuarios").select("id,nome,email,tipo,perfil").order("nome").execute()
    coordenadores = [
        usuario
        for usuario in (resultado.data or [])
        if _tipo_usuario(usuario) == "coordenador"
    ]

    ids = [coordenador["id"] for coordenador in coordenadores]
    cargos: dict[int, str] = {}
    fotos: dict[int, str] = {}

    if ids:
        resultado_cargos = (
            supabase.table("cargos").select("usuario_id,cargo").in_("usuario_id", ids).execute()
        )
        cargos = {
            item["usuario_id"]: item["cargo"]
            for item in (resultado_cargos.data or [])
        }

        resultado_fotos = (
            supabase
            .table("fotos_coordenadores")
            .select("usuario_id,url")
            .in_("usuario_id", ids)
            .execute()
        )
        fotos = {
            item["usuario_id"]: item["url"]
            for item in (resultado_fotos.data or [])
        }

    return [
        {
            "id": coordenador["id"],
            "nome": coordenador["nome"],
            "email": coordenador.get("email"),
            "cargo": cargos.get(coordenador["id"]) or "Coordenador(a)",
            "foto_url": fotos.get(coordenador["id"]),
        }
        for coordenador in coordenadores
    ]


@router.get("/perfil-agendante")
def obter_perfil_agendante(token_data: dict = Depends(verify_firebase_token)):
    """Dados usados no preenchimento automático do formulário."""
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)

    perfil = {
        "tipo": tipo,
        "nome": usuario.get("nome") or "",
        "matricula": usuario.get("matricula"),
        "telefone": usuario.get("telefone"),
        "email": usuario.get("email") or "",
        "curso": None,
        "periodo": None,
        "turma": None,
    }

    if tipo == "aluno":
        resultado = (
            supabase
            .table("alunos")
            .select("curso,periodo,turma")
            .eq("usuario_id", usuario["id"])
            .limit(1)
            .execute()
        )
        dados = resultado.data or []
        if dados:
            perfil.update(
                {
                    "curso": dados[0].get("curso"),
                    "periodo": dados[0].get("periodo"),
                    "turma": dados[0].get("turma"),
                }
            )

    return perfil


@router.get("/horarios")
def listar_horarios_fluxo(
    coordinator_id: int,
    dias: int = DIAS_PADRAO,
    token_data: dict = Depends(verify_firebase_token),
):
    """
    Expande os horários semanais do coordenador nos próximos `dias` dias e
    classifica cada slot como livre, ocupado ou bloqueado.
    """
    usuario = _get_usuario_logado(token_data)
    coordenador = _buscar_coordenador(coordinator_id)

    dias = max(1, min(int(dias), DIAS_MAXIMO))
    hoje = date.today()
    limite = hoje + timedelta(days=dias - 1)
    agora_hhmm = datetime.now().strftime("%H:%M")

    horarios = (
        supabase
        .table("horarios")
        .select("*")
        .eq("coordinator_id", coordinator_id)
        .execute()
    ).data or []

    agendamentos = (
        supabase
        .table("agendamentos")
        .select("data,horario,status")
        .eq("coordinator_id", coordinator_id)
        .gte("data", hoje.isoformat())
        .lte("data", limite.isoformat())
        .execute()
    ).data or []
    ocupados = {
        (str(item.get("data")), item.get("horario"))
        for item in agendamentos
        if item.get("status") not in ("Cancelado", "Redirecionado")
    }

    bloqueios = (
        supabase
        .table("bloqueios_horario")
        .select("data,horario,usuario_id,expira_em")
        .eq("coordinator_id", coordinator_id)
        .gte("data", hoje.isoformat())
        .lte("data", limite.isoformat())
        .gt("expira_em", datetime.now(timezone.utc).isoformat())
        .execute()
    ).data or []
    dono_do_bloqueio = {
        (str(item.get("data")), item.get("horario")): item.get("usuario_id")
        for item in bloqueios
    }

    dias_resposta = []
    for indice in range(dias):
        dia = hoje + timedelta(days=indice)
        dia_semana = _dia_semana_banco(dia)
        chave_dia = dia.isoformat()

        slots = []
        for horario in horarios:
            if int(horario.get("dia_semana", -1)) != dia_semana:
                continue

            hora_inicio = horario.get("hora_inicio")
            if not hora_inicio:
                continue

            # Horário de hoje que já passou não é ofertado.
            if dia == hoje and hora_inicio < agora_hhmm:
                continue

            chave_slot = (chave_dia, hora_inicio)
            if chave_slot in ocupados:
                situacao = "ocupado"
            elif chave_slot in dono_do_bloqueio:
                situacao = (
                    "bloqueado_por_mim"
                    if dono_do_bloqueio[chave_slot] == usuario.get("id")
                    else "bloqueado"
                )
            else:
                situacao = "livre"

            duracao = int(horario.get("duracao_min") or 0)
            slots.append(
                {
                    "horario": hora_inicio,
                    "hora_fim": horario.get("hora_fim") or _somar_minutos(hora_inicio, duracao),
                    "duracao_min": duracao,
                    "tipo": horario.get("tipo") or "Atendimento",
                    "status": situacao,
                }
            )

        slots.sort(key=lambda slot: slot["horario"])
        dias_resposta.append(
            {"data": chave_dia, "dia_semana": dia_semana, "slots": slots}
        )

    return {
        "coordenador": {"id": coordenador["id"], "nome": coordenador["nome"]},
        "ttl_min": _ttl_minutos(),
        "dias": dias_resposta,
    }


@router.post("/bloqueios", status_code=status.HTTP_201_CREATED)
def criar_bloqueio(
    bloqueio: BloqueioCreate,
    token_data: dict = Depends(verify_firebase_token),
):
    """Reserva temporariamente um horário livre (atômico no banco)."""
    usuario = _get_usuario_logado(token_data)
    _exigir_criador(usuario)

    hoje = date.today()
    if bloqueio.data < hoje:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Não é possível agendar em uma data passada.",
        )

    _buscar_coordenador(bloqueio.coordinator_id)
    _horario_do_coordenador(bloqueio.coordinator_id, bloqueio.data, bloqueio.horario)

    resultado = _executar_rpc(
        "bloquear_horario",
        {
            "p_coordinator_id": bloqueio.coordinator_id,
            "p_data": bloqueio.data.isoformat(),
            "p_horario": bloqueio.horario,
            "p_usuario_id": usuario["id"],
            "p_ttl_min": _ttl_minutos(),
        },
    )

    if not resultado.get("ok"):
        # 'ocupado' e 'bloqueado' são conflitos de concorrência para o usuário.
        raise _erro_slot_ocupado()

    return {
        "token": resultado.get("token"),
        "expira_em": resultado.get("expira_em"),
        "ttl_min": _ttl_minutos(),
        "coordinator_id": bloqueio.coordinator_id,
        "data": bloqueio.data.isoformat(),
        "horario": bloqueio.horario,
    }


@router.delete("/bloqueios/{token}")
def liberar_bloqueio(
    token: str,
    token_data: dict = Depends(verify_firebase_token),
):
    """Libera um bloqueio do próprio usuário (idempotente)."""
    usuario = _get_usuario_logado(token_data)
    token_normalizado = _validar_token(token)

    _executar_rpc(
        "liberar_bloqueio",
        {
            "p_token": token_normalizado,
            "p_usuario_id": usuario["id"],
        },
    )

    return {"ok": True}


@router.post("/confirmar", status_code=status.HTTP_201_CREATED)
def confirmar_agendamento(
    confirmacao: ConfirmacaoCreate,
    token_data: dict = Depends(verify_firebase_token),
):
    """Converte o bloqueio em agendamento definitivo (atômico no banco)."""
    usuario = _get_usuario_logado(token_data)
    _exigir_criador(usuario)
    token_normalizado = _validar_token(confirmacao.token)

    resultado = _executar_rpc(
        "confirmar_agendamento",
        {
            "p_token": token_normalizado,
            "p_usuario_id": usuario["id"],
            "p_aluno": confirmacao.nome.strip(),
            "p_aluno_email": str(confirmacao.email).strip().lower(),
            "p_aluno_matricula": confirmacao.matricula.strip(),
            "p_curso": confirmacao.curso.strip(),
            "p_periodo": confirmacao.periodo.strip(),
            "p_turma": confirmacao.turma.strip(),
            "p_telefone": confirmacao.telefone.strip(),
            "p_descricao": confirmacao.descricao.strip(),
            "p_nome_atendimento": NOME_ATENDIMENTO_PADRAO,
        },
    )

    if not resultado.get("ok"):
        raise _erro_slot_ocupado()

    return resultado.get("agendamento") or {}
