"""Notificações persistentes do sistema de agendamento.

As notificações são gravadas pelo backend depois que a operação principal é
concluída com sucesso. Falhas ao notificar nunca devem derrubar a operação.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable, Optional

from fastapi import BackgroundTasks

from app.database import supabase
from app.services import email as email_service

# Tipos gravados na coluna `notificacoes.tipo`.
TIPO_PENDENTE = "pendente"
TIPO_CONFIRMADO = "confirmado"
TIPO_CANCELADO = "cancelado"
TIPO_REDIRECIONADO = "redirecionado"
TIPO_CONCLUIDO = "concluido"

_TIPO_POR_STATUS = {
    "Pendente": TIPO_PENDENTE,
    "Confirmado": TIPO_CONFIRMADO,
    "Cancelado": TIPO_CANCELADO,
    "Redirecionado": TIPO_REDIRECIONADO,
    "Concluído": TIPO_CONCLUIDO,
}


def _tipo_usuario(usuario: Optional[dict]) -> str:
    if not usuario:
        return ""
    bruto = (usuario.get("tipo") or usuario.get("perfil") or "").strip().lower()
    if bruto in ("apoio", "nao_aluno", "não aluno", "suporte"):
        return "suporte"
    return bruto


def _id_usuario(usuario: Optional[dict]) -> Optional[int]:
    if not usuario:
        return None
    try:
        return int(usuario.get("id"))
    except (TypeError, ValueError):
        return None


def _nome_usuario(usuario: Optional[dict]) -> str:
    if not usuario:
        return "Sistema"
    return (usuario.get("nome") or usuario.get("email") or "Sistema").strip()


def _formatar_data(valor) -> str:
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor or "").strip()
    partes = texto.split("-")
    if len(partes) == 3:
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return texto


def _resumo_agendamento(agendamento: dict) -> str:
    aluno = agendamento.get("aluno") or agendamento.get("alunoEmail") or "aluno"
    data = _formatar_data(agendamento.get("data"))
    horario = agendamento.get("horario") or ""
    return f"#{agendamento.get('id')} de {aluno} para {data} às {horario}"


def _buscar_aluno_do_agendamento(agendamento: dict) -> Optional[dict]:
    """Resolve o usuário aluno dono do agendamento, quando existir."""
    created_by = agendamento.get("created_by")
    if created_by is not None:
        try:
            resultado = (
                supabase.table("usuarios")
                .select("id,nome,email,tipo,perfil,matricula")
                .eq("id", created_by)
                .limit(1)
                .execute()
            )
            dados = resultado.data or []
            if dados and _tipo_usuario(dados[0]) == "aluno":
                return dados[0]
        except Exception:
            pass

    email = str(agendamento.get("alunoEmail") or "").strip().lower()
    if email:
        try:
            resultado = (
                supabase.table("usuarios")
                .select("id,nome,email,tipo,perfil,matricula")
                .eq("email", email)
                .limit(1)
                .execute()
            )
            dados = resultado.data or []
            if dados and _tipo_usuario(dados[0]) == "aluno":
                return dados[0]
        except Exception:
            pass

    matricula = agendamento.get("aluno_matricula")
    if matricula:
        try:
            resultado = (
                supabase.table("usuarios")
                .select("id,nome,email,tipo,perfil,matricula")
                .eq("matricula", matricula)
                .limit(1)
                .execute()
            )
            dados = resultado.data or []
            if dados and _tipo_usuario(dados[0]) == "aluno":
                return dados[0]
        except Exception:
            pass

    return None


def _ids_suporte() -> list[int]:
    try:
        resultado = supabase.table("usuarios").select("id").eq("tipo", "suporte").execute()
        return [
            int(item["id"])
            for item in (resultado.data or [])
            if item.get("id") is not None
        ]
    except Exception:
        return []


def _destinatarios(
    evento: str,
    agendamento: dict,
    ator_id: Optional[int],
    *,
    aluno: Optional[dict] = None,
    incluir_suporte: bool = False,
    incluir_aluno: bool = False,
) -> list[int]:
    ids: list[int] = []

    coordinator_id = agendamento.get("coordinator_id")
    if coordinator_id is not None:
        try:
            ids.append(int(coordinator_id))
        except (TypeError, ValueError):
            pass

    if incluir_suporte:
        ids.extend(_ids_suporte())

    if incluir_aluno:
        aluno_id = _id_usuario(aluno)
        if aluno_id is not None:
            ids.append(aluno_id)

    # O autor da ação não recebe a própria notificação.
    return list({i for i in ids if i != ator_id})


def _mensagem(evento: str, agendamento: dict, ator_nome: str) -> str:
    resumo = _resumo_agendamento(agendamento)
    if evento == TIPO_PENDENTE:
        return f"Novo agendamento pendente {resumo}."
    if evento == TIPO_CONFIRMADO:
        return f"{ator_nome} confirmou o agendamento {resumo}."
    if evento == TIPO_CANCELADO:
        return f"{ator_nome} cancelou o agendamento {resumo}."
    if evento == TIPO_REDIRECIONADO:
        return f"{ator_nome} redirecionou o agendamento {resumo}."
    if evento == TIPO_CONCLUIDO:
        return f"{ator_nome} marcou como concluído o agendamento {resumo}."
    return f"{ator_nome} alterou o agendamento {resumo}."


def _inserir_notificacoes(
    destinatarios: Iterable[int],
    *,
    agendamento: dict,
    evento: str,
    status_anterior: Optional[str],
    status_novo: Optional[str],
    ator: Optional[dict],
    mensagem: str,
) -> None:
    ator_id = _id_usuario(ator)
    ator_nome = _nome_usuario(ator)
    linhas = [
        {
            "usuario_id": usuario_id,
            "agendamento_id": agendamento.get("id"),
            "tipo": evento,
            "status_anterior": status_anterior,
            "status_novo": status_novo,
            "ator_usuario_id": ator_id,
            "ator_nome": ator_nome,
            "mensagem": mensagem,
            "lida": False,
        }
        for usuario_id in destinatarios
    ]
    if not linhas:
        return

    try:
        supabase.table("notificacoes").insert(linhas).execute()
    except Exception as exc:  # noqa: BLE001 - notificação não pode quebrar a operação
        print(f"[notificacoes] Falha ao inserir notificações: {exc}")


def _email_aluno(agendamento: dict, aluno: Optional[dict]) -> str:
    """Prefere o e-mail informado no formulário; cai para o cadastro do usuário."""
    for valor in (agendamento.get("alunoEmail"), (aluno or {}).get("email")):
        email = str(valor or "").strip().lower()
        if email:
            return email
    return ""


def _agendar_email_status(
    background: Optional[BackgroundTasks],
    *,
    agendamento: dict,
    status_anterior: Optional[str],
    status_novo: str,
    ator: Optional[dict],
    aluno: Optional[dict],
    observacao: Optional[str],
) -> None:
    destinatario = _email_aluno(agendamento, aluno)
    if not destinatario:
        return

    ator_email = str((ator or {}).get("email") or "").strip().lower()
    if ator_email and ator_email == destinatario:
        # O aluno não recebe e-mail sobre a própria ação (mesma regra do sino).
        return

    kwargs = {
        "agendamento": agendamento,
        "status_novo": status_novo,
        "destinatario": destinatario,
        "ator": ator,
        "aluno": aluno,
        "status_anterior": status_anterior,
        "observacao": observacao,
    }
    if background is not None:
        background.add_task(email_service.enviar_email_status, **kwargs)
    else:
        email_service.enviar_email_status(**kwargs)


def notificar_agendamento_pendente(agendamento: dict, ator: Optional[dict]) -> None:
    """Novo agendamento: coordenador responsável + todos os suportes."""
    evento = TIPO_PENDENTE
    destinatarios = _destinatarios(
        evento,
        agendamento,
        _id_usuario(ator),
        incluir_suporte=True,
    )
    _inserir_notificacoes(
        destinatarios,
        agendamento=agendamento,
        evento=evento,
        status_anterior=None,
        status_novo=agendamento.get("status") or "Pendente",
        ator=ator,
        mensagem=_mensagem(evento, agendamento, _nome_usuario(ator)),
    )


def notificar_mudanca_status(
    agendamento: dict,
    status_anterior: Optional[str],
    status_novo: str,
    ator: Optional[dict],
    *,
    background: Optional[BackgroundTasks] = None,
    observacao: Optional[str] = None,
) -> None:
    """Mudança de status conforme a matriz de destinatários do sistema."""
    evento = _TIPO_POR_STATUS.get(status_novo)
    if not evento:
        return

    # O aluno acompanha confirmação, cancelamento e redirecionamento.
    incluir_aluno = evento in (TIPO_CONFIRMADO, TIPO_CANCELADO, TIPO_REDIRECIONADO)

    # Suporte acompanha apenas eventos que deixam o agendamento pendente.
    incluir_suporte = evento == TIPO_PENDENTE

    aluno = _buscar_aluno_do_agendamento(agendamento) if incluir_aluno else None

    destinatarios = _destinatarios(
        evento,
        agendamento,
        _id_usuario(ator),
        aluno=aluno,
        incluir_suporte=incluir_suporte,
        incluir_aluno=incluir_aluno,
    )
    _inserir_notificacoes(
        destinatarios,
        agendamento=agendamento,
        evento=evento,
        status_anterior=status_anterior,
        status_novo=status_novo,
        ator=ator,
        mensagem=_mensagem(evento, agendamento, _nome_usuario(ator)),
    )

    if incluir_aluno:
        _agendar_email_status(
            background,
            agendamento=agendamento,
            status_anterior=status_anterior,
            status_novo=status_novo,
            ator=ator,
            aluno=aluno,
            observacao=observacao,
        )
