"""
Popula os metadados fictícios do novo fluxo de agendamento.

Uso (a partir da raiz do projeto):
    app\\.venv\\Scripts\\python.exe app\\scripts\\seed_fluxo.py

Pré-requisitos:
- app/.env preenchido com SUPABASE_URL e SUPABASE_KEY
- supabase/001_schema.sql e supabase/002_fluxo_agendamento.sql aplicados
- usuários de demonstração criados (app/scripts/seed_dev.py)

O script NÃO cria usuários. Ele apenas cadastra, de forma idempotente:
- cargo e foto fictícia dos coordenadores existentes;
- curso, período e turma dos alunos existentes.

As fotos apontam para placeholders locais em
Agendamento-cord-est-front/public/coordenadores/ e podem ser trocadas depois.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(APP_DIR / ".env")

from app.database import supabase  # noqa: E402

CARGOS = {
    "coord@teste.com": "Coordenador dos cursos de TI",
}

FOTOS = {
    "coord@teste.com": "/coordenadores/coord-1.svg",
}

ALUNOS = {
    "aluno@teste.com": {
        "curso": "Análise e Desenvolvimento de Sistemas",
        "periodo": "3º período",
        "turma": "ADS-3A",
    },
}


def buscar_usuario(email: str) -> dict | None:
    resultado = (
        supabase
        .table("usuarios")
        .select("id,nome,email,tipo,perfil")
        .eq("email", email.lower())
        .limit(1)
        .execute()
    )
    dados = resultado.data or []
    return dados[0] if dados else None


def upsert_por_usuario(tabela: str, usuario_id: int, dados: dict) -> str:
    existente = (
        supabase
        .table(tabela)
        .select("id")
        .eq("usuario_id", usuario_id)
        .limit(1)
        .execute()
    )
    if existente.data:
        supabase.table(tabela).update(dados).eq("usuario_id", usuario_id).execute()
        return "atualizado"
    supabase.table(tabela).insert({"usuario_id": usuario_id, **dados}).execute()
    return "criado"


def semear_coordenadores() -> None:
    print("\n[1/2] Cargo e foto dos coordenadores")
    for email, cargo in CARGOS.items():
        usuario = buscar_usuario(email)
        if not usuario:
            print(f"  AVISO: usuário {email} não encontrado; ignorado.")
            continue

        estado_cargo = upsert_por_usuario("cargos", usuario["id"], {"cargo": cargo})
        print(f"  {email}: cargo {estado_cargo} ({cargo})")

        if email in FOTOS:
            estado_foto = upsert_por_usuario(
                "fotos_coordenadores", usuario["id"], {"url": FOTOS[email]}
            )
            print(f"  {email}: foto {estado_foto} ({FOTOS[email]})")


def semear_alunos() -> None:
    print("\n[2/2] Curso, período e turma dos alunos")
    for email, dados in ALUNOS.items():
        usuario = buscar_usuario(email)
        if not usuario:
            print(f"  AVISO: usuário {email} não encontrado; ignorado.")
            continue

        estado = upsert_por_usuario("alunos", usuario["id"], dados)
        print(f"  {email}: dados académicos {estado} ({dados['curso']})")


def main() -> None:
    print("=" * 60)
    print("  SEED DO FLUXO DE AGENDAMENTO — dados fictícios")
    print("=" * 60)
    try:
        semear_coordenadores()
        semear_alunos()
    except Exception as erro:  # noqa: BLE001 - script de apoio
        print(f"\nERRO: {erro}")
        print(
            "\nVerifique se supabase/002_fluxo_agendamento.sql foi aplicado e se "
            "o .env do backend está correto."
        )
        raise SystemExit(1)

    print("\nConcluído.")


if __name__ == "__main__":
    main()
