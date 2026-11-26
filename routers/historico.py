"""Histórico geral de agendamentos com filtros.

A tela de histórico do coordenador usa este router para listar os agendamentos
e as respectivas alterações em uma única resposta.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database import supabase
from app.dependencies.auth import verify_firebase_token

router = APIRouter(prefix="/historico", tags=["Histórico"])

STATUS_VALIDOS = ("Pendente", "Confirmado", "Concluído", "Cancelado", "Redirecionado")
STATUS_FINAIS = ("Concluído", "Cancelado", "Redirecionado")


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


def _pode_ver(usuario: dict, agendamento: dict) -> bool:
    tipo = _tipo_usuario(usuario)
    user_id = usuario.get("id")
    if tipo == "suporte":
        return True
    if tipo == "coordenador":
        return agendamento.get("coordinator_id") == user_id
    if tipo == "aluno":
        matricula = usuario.get("matricula")
        email = (usuario.get("email") or "").lower()
        return (
            agendamento.get("created_by") == user_id
            or (matricula and agendamento.get("aluno_matricula") == matricula)
            or (agendamento.get("alunoEmail") or "").lower() == email
        )
    return False


def _status_solicitados(status_param: Optional[str], finalizados: bool) -> list[str]:
    statuses: list[str] = []
    if status_param:
        # Filtro de status explícito é exato: devolve apenas o que foi pedido.
        for valor in status_param.split(","):
            limpo = valor.strip()
            if limpo in STATUS_VALIDOS and limpo not in statuses:
                statuses.append(limpo)
        return statuses

    if finalizados:
        # Sem filtro de status e com "finalizados" ligado: todos os status.
        return []

    # Por padrão, "Concluído" fica oculto.
    return [status for status in STATUS_VALIDOS if status != "Concluído"]


def _buscar_observacoes(ids: list[int]) -> dict[int, list[dict]]:
    if not ids:
        return {}

    resultado = (
        supabase
        .table("agendamentos_observacoes")
        .select("*")
        .in_("agendamento_id", ids)
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

    por_agendamento: dict[int, list[dict]] = {}
    for item in observacoes:
        registro = {**item, "usuario_nome": nomes.get(item.get("usuario_id"))}
        por_agendamento.setdefault(item["agendamento_id"], []).append(registro)
    return por_agendamento


@router.get("/agendamentos")
def listar_historico(
    agendamento_id: Optional[int] = Query(default=None, alias="id"),
    aluno: Optional[str] = None,
    descricao: Optional[str] = None,
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    status_filtro: Optional[str] = Query(default=None, alias="status"),
    finalizados: bool = False,
    incluir_sem_historico: bool = False,
    coordinator_id: Optional[int] = None,
    pagina: int = Query(default=1, ge=1),
    limite: int = Query(default=20, ge=1, le=200),
    token_data: dict = Depends(verify_firebase_token),
):
    usuario = _get_usuario_logado(token_data)
    tipo = _tipo_usuario(usuario)

    consulta = supabase.table("agendamentos").select("*")

    if agendamento_id is not None:
        consulta = consulta.eq("id", agendamento_id)

    if aluno:
        consulta = consulta.ilike("aluno", f"%{aluno.strip()}%")

    if descricao:
        consulta = consulta.ilike("descricao", f"%{descricao.strip()}%")

    if data_inicio:
        consulta = consulta.gte("data", data_inicio.isoformat())

    if data_fim:
        consulta = consulta.lte("data", data_fim.isoformat())

    statuses = _status_solicitados(status_filtro, finalizados)
    if statuses:
        consulta = consulta.in_("status", statuses)

    # Regras de visibilidade por perfil.
    if tipo == "coordenador":
        consulta = consulta.eq("coordinator_id", usuario.get("id"))
    elif tipo == "suporte" and coordinator_id is not None:
        consulta = consulta.eq("coordinator_id", coordinator_id)
    # O aluno é filtrado em memória para aceitar created_by/matrícula/e-mail.

    consulta = consulta.order("data", desc=True).order("horario", desc=True)
    resultado = consulta.execute()
    agendamentos = resultado.data or []

    if tipo == "aluno":
        agendamentos = [a for a in agendamentos if _pode_ver(usuario, a)]
    elif tipo not in ("coordenador", "suporte"):
        agendamentos = []

    ids_todos = [item["id"] for item in agendamentos]
    observacoes_por_id = _buscar_observacoes(ids_todos)

    if not incluir_sem_historico:
        agendamentos = [
            item for item in agendamentos if observacoes_por_id.get(item["id"])
        ]

    total = len(agendamentos)
    inicio = (pagina - 1) * limite
    pagina_itens = agendamentos[inicio : inicio + limite]

    itens = []
    for agendamento in pagina_itens:
        historico = observacoes_por_id.get(agendamento["id"], [])
        itens.append(
            {
                "agendamento": agendamento,
                "historico": historico,
                "tem_historico": bool(historico),
                "ultima_alteracao": historico[0] if historico else None,
            }
        )

    total_paginas = (total + limite - 1) // limite if total else 0

    return {
        "itens": itens,
        "total": total,
        "pagina": pagina,
        "limite": limite,
        "total_paginas": total_paginas,
    }
