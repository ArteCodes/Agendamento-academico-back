"""
Teste rápido de integração (backend FastAPI + Firebase + Supabase).

Uso, a partir da raiz do projeto, depois de aplicar supabase/001_schema.sql
e rodar o seed:

    app\\.venv\\\\Scripts\\\\python.exe app\\\\scripts\\\\smoke_test.py

Por padrão o teste é somente leitura: autentica os três usuários de
demonstração e consulta /auth/me, /agendamentos e /horarios.

Com --write, cria um agendamento como aluno, confirma como coordenador e
cancela o mesmo agendamento no final.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "app"
FRONT_DIR = ROOT / "Agendamento-cord-est-front"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(APP_DIR / ".env")
load_dotenv(FRONT_DIR / ".env")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SENHA = "Teste12345"
USUARIOS = ["aluno@teste.com", "coord@teste.com", "suporte@teste.com"]
API_KEY = os.getenv("VITE_FIREBASE_API_KEY")

client = TestClient(app)


def obter_token(email: str) -> str:
    if not API_KEY:
        raise SystemExit(
            "VITE_FIREBASE_API_KEY não encontrada. Preencha o .env do frontend."
        )
    resposta = httpx.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
        params={"key": API_KEY},
        json={"email": email, "password": SENHA, "returnSecureToken": True},
        timeout=30,
    )
    if resposta.status_code != 200:
        raise SystemExit(f"Falha ao autenticar {email}: {resposta.text}")
    return resposta.json()["idToken"]


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def testar_leituras() -> dict[str, dict]:
    print("\n[1/2] Autenticação e leituras por perfil")
    perfis: dict[str, dict] = {}
    for email in USUARIOS:
        token = obter_token(email)
        me = client.get("/api/auth/me", headers=headers(token))
        if me.status_code != 200:
            raise SystemExit(f"{email}: /auth/me retornou {me.status_code} — {me.text}")
        dados = me.json()
        perfis[email] = dados
        agendamentos = client.get("/api/agendamentos", headers=headers(token))
        if agendamentos.status_code != 200:
            raise SystemExit(
                f"{email}: /agendamentos retornou {agendamentos.status_code} — {agendamentos.text}"
            )
        print(
            f"  {email}: tipo={dados.get('tipo')} perfil={dados.get('perfil')} "
            f"agendamentos={len(agendamentos.json())}"
        )

        if dados.get("tipo") in ("coordenador", "suporte"):
            horarios = client.get("/api/horarios", headers=headers(token))
            if horarios.status_code != 200:
                raise SystemExit(
                    f"{email}: /horarios retornou {horarios.status_code} — {horarios.text}"
                )
            print(f"    /horarios -> {len(horarios.json())} registro(s)")
    return perfis


def testar_escrita(perfis: dict[str, dict]) -> None:
    print("\n[2/2] Criação, confirmação e cancelamento de agendamento")
    token_aluno = obter_token("aluno@teste.com")
    token_coord = obter_token("coord@teste.com")

    aluno = perfis["aluno@teste.com"]
    amanha = (date.today() + timedelta(days=1)).isoformat()
    payload = {
        "aluno": aluno["nome"],
        "alunoEmail": aluno["email"],
        "aluno_matricula": aluno.get("matricula"),
        "nome": "Teste automático",
        "data": amanha,
        "horario": "15:00",
        "descricao": "Criado por app/scripts/smoke_test.py",
    }
    criado = client.post("/api/agendamentos", headers=headers(token_aluno), json=payload)
    if criado.status_code != 201:
        raise SystemExit(f"Criar agendamento retornou {criado.status_code} — {criado.text}")
    agendamento = criado.json()
    print(f"  Aluno criou agendamento #{agendamento['id']} (status {agendamento['status']})")

    validado = client.patch(
        f"/api/agendamentos/{agendamento['id']}/validar",
        headers=headers(token_coord),
    )
    if validado.status_code != 200:
        raise SystemExit(f"Validar retornou {validado.status_code} — {validado.text}")
    print(f"  Coordenador confirmou: status {validado.json()['status']}")

    cancelado = client.patch(
        f"/api/agendamentos/{agendamento['id']}",
        headers=headers(token_aluno),
    )
    if cancelado.status_code != 200:
        raise SystemExit(f"Cancelar retornou {cancelado.status_code} — {cancelado.text}")
    print(f"  Aluno cancelou: status {cancelado.json()['status']}")


def main() -> None:
    print("=" * 60)
    print("  SMOKE TEST — Sistema de Agendamento")
    print("=" * 60)
    perfis = testar_leituras()
    if "--write" in sys.argv:
        testar_escrita(perfis)
    else:
        print("\n[2/2] Escrita ignorada (use --write para testar criação/validação/cancelamento).")
    print("\nOK: integração verificada.")


if __name__ == "__main__":
    main()
