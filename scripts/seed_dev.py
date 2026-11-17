"""
Popula o ambiente de desenvolvimento com usuários e dados de demonstração.

Uso (a partir da raiz do projeto):
    app\\.venv\\Scripts\\python.exe app\\scripts\\seed_dev.py

Pré-requisitos:
- app/.env preenchido com SUPABASE_URL, SUPABASE_KEY e FIREBASE_CREDENTIALS
- app/core/firebase-credentials.json presente
- schema criado com supabase/001_schema.sql

O script é idempotente:
- cria/atualiza os usuários no Firebase Auth e na tabela usuarios;
- só insere agendamentos e horários de exemplo se as tabelas estiverem vazias.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(APP_DIR / ".env")

from firebase_admin import auth as firebase_auth  # noqa: E402

from app.database import supabase  # noqa: E402
import app.core.firebase  # noqa: E402,F401  (inicializa o Firebase Admin)

SENHA_PADRAO = "Teste12345"

USUARIOS = [
    {
        "nome": "Maria Silva",
        "email": "aluno@teste.com",
        "perfil": "Aluno",
        "tipo": "aluno",
        "matricula": "2026001",
        "cpf": None,
        "telefone": "(81) 99999-0001",
        "carga_horaria_semanal": None,
    },
    {
        "nome": "João Santos",
        "email": "coord@teste.com",
        "perfil": "Coordenador",
        "tipo": "coordenador",
        "matricula": None,
        "cpf": None,
        "telefone": "(81) 99999-0002",
        "carga_horaria_semanal": 20,
    },
    {
        "nome": "Suporte Silva",
        "email": "suporte@teste.com",
        "perfil": "Apoio",
        "tipo": "suporte",
        "matricula": "S001",
        "cpf": None,
        "telefone": "(81) 99999-0003",
        "carga_horaria_semanal": None,
    },
]


def garantir_usuario_firebase(email: str, nome: str, senha: str) -> None:
    try:
        usuario = firebase_auth.get_user_by_email(email)
        firebase_auth.update_user(usuario.uid, password=senha, display_name=nome)
        print(f"  Firebase: usuário já existia e foi atualizado ({email}).")
    except firebase_auth.UserNotFoundError:
        firebase_auth.create_user(email=email, password=senha, display_name=nome)
        print(f"  Firebase: usuário criado ({email}).")


def garantir_usuario_supabase(dados: dict) -> int:
    email = dados["email"].lower()
    existente = (
        supabase.table("usuarios").select("id").eq("email", email).limit(1).execute()
    )
    if existente.data:
        supabase.table("usuarios").update(dados).eq("email", email).execute()
        print(f"  Supabase: usuário já existia e foi atualizado ({email}).")
        return existente.data[0]["id"]

    criado = supabase.table("usuarios").insert(dados).execute()
    print(f"  Supabase: usuário criado ({email}).")
    return criado.data[0]["id"]


def criar_usuarios() -> dict[str, int]:
    print("\n[1/3] Criando usuários de teste...")
    ids: dict[str, int] = {}
    for usuario in USUARIOS:
        email = usuario["email"].lower()
        garantir_usuario_firebase(email, usuario["nome"], SENHA_PADRAO)
        ids[email] = garantir_usuario_supabase({**usuario, "email": email})
    return ids


def criar_agendamentos(ids: dict[str, int]) -> None:
    print("\n[2/3] Criando agendamentos de exemplo...")
    total = (
        supabase.table("agendamentos").select("*", count="exact").limit(1).execute().count
    )
    if total:
        print(f"  Já existem {total} agendamento(s); nenhum dado de exemplo foi inserido.")
        return

    hoje = date.today()
    coord_id = ids["coord@teste.com"]
    aluno_id = ids["aluno@teste.com"]
    suporte_id = ids["suporte@teste.com"]

    exemplos = [
        {
            "aluno": "Maria Silva",
            "alunoEmail": "aluno@teste.com",
            "aluno_matricula": "2026001",
            "created_by": aluno_id,
            "coordinator_id": coord_id,
            "nome": "Consulta Psicológica",
            "data": (hoje + timedelta(days=2)).isoformat(),
            "horario": "14:00",
            "status": "Confirmado",
            "descricao": "Sessão de acompanhamento psicológico individual.",
        },
        {
            "aluno": "Maria Silva",
            "alunoEmail": "aluno@teste.com",
            "aluno_matricula": "2026001",
            "created_by": aluno_id,
            "coordinator_id": coord_id,
            "nome": "Orientação Acadêmica",
            "data": (hoje + timedelta(days=5)).isoformat(),
            "horario": "10:30",
            "status": "Pendente",
            "descricao": "Orientação sobre grade curricular e equivalência de matérias.",
        },
        {
            "aluno": "Carlos Souza",
            "alunoEmail": "carlos@teste.com",
            "aluno_matricula": "2026002",
            "created_by": suporte_id,
            "coordinator_id": coord_id,
            "nome": "Atendimento Social",
            "data": (hoje + timedelta(days=7)).isoformat(),
            "horario": "09:00",
            "status": "Pendente",
            "descricao": "Avaliação socioeconômica para auxílio permanência.",
        },
        {
            "aluno": "Maria Silva",
            "alunoEmail": "aluno@teste.com",
            "aluno_matricula": "2026001",
            "created_by": aluno_id,
            "coordinator_id": coord_id,
            "nome": "Consulta Nutricional",
            "data": (hoje + timedelta(days=9)).isoformat(),
            "horario": "11:00",
            "status": "Confirmado",
            "descricao": "Acompanhamento nutricional e reeducação alimentar.",
        },
    ]

    supabase.table("agendamentos").insert(exemplos).execute()
    print(f"  {len(exemplos)} agendamento(s) inserido(s).")


def criar_horarios(ids: dict[str, int]) -> None:
    print("\n[3/3] Criando horários de exemplo...")
    total = supabase.table("horarios").select("*", count="exact").limit(1).execute().count
    if total:
        print(f"  Já existem {total} horário(s); nenhum dado de exemplo foi inserido.")
        return

    coord_id = ids["coord@teste.com"]
    exemplos = [
        {"coordinator_id": coord_id, "dia_semana": 1, "hora_inicio": "08:00", "duracao_min": 60, "hora_fim": "09:00", "tipo": "Atendimento"},
        {"coordinator_id": coord_id, "dia_semana": 3, "hora_inicio": "14:00", "duracao_min": 60, "hora_fim": "15:00", "tipo": "Atendimento"},
        {"coordinator_id": coord_id, "dia_semana": 5, "hora_inicio": "09:00", "duracao_min": 45, "hora_fim": "09:45", "tipo": "Orientação"},
    ]
    supabase.table("horarios").insert(exemplos).execute()
    print(f"  {len(exemplos)} horário(s) inserido(s).")


def main() -> None:
    print("=" * 60)
    print("  SEED DE DESENVOLVIMENTO — Sistema de Agendamento")
    print("=" * 60)
    try:
        ids = criar_usuarios()
        criar_agendamentos(ids)
        criar_horarios(ids)
    except Exception as erro:
        print(f"\nERRO: {erro}")
        print(
            "\nVerifique se o schema foi criado (supabase/001_schema.sql) e se o .env "
            "do backend está correto."
        )
        raise SystemExit(1)

    print("\nConcluído.")
    print("Contas de teste (senha: Teste12345):")
    for usuario in USUARIOS:
        print(f"  - {usuario['email']} ({usuario['perfil']})")


if __name__ == "__main__":
    main()
