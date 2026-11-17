import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import auth as firebase_auth

from app.database import supabase
from app.dependencies.auth import verify_firebase_token
from app.schemas.user import (
    UserResponse,
    UserRegisterRequest,
    UserRegisterResponse,
    IdentifierResolveRequest,
    IdentifierResolveResponse,
)

router = APIRouter(prefix="/auth", tags=["Autenticação"])

# Converte o tipo enviado no cadastro para (perfil exibido, tipo interno).
# O frontend usa sempre o tipo interno em minúsculas: aluno, coordenador ou suporte.
PERFIL_POR_TIPO = {
    "aluno": ("Aluno", "aluno"),
    "coordenador": ("Coordenador", "coordenador"),
    "nao_aluno": ("Apoio", "suporte"),
    "suporte": ("Apoio", "suporte"),
}


def _somente_digitos(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    return re.sub(r"\D", "", valor)


def _normalizar_matricula(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    return re.sub(r"[^A-Za-z0-9]", "", valor).upper() or None


def _normalizar_tipo(perfil: Optional[str], tipo: Optional[str] = None) -> Optional[str]:
    """Aceita 'Apoio', 'nao_aluno', 'suporte' etc. e devolve o tipo interno."""
    bruto = (tipo or perfil or "").strip().lower()
    if bruto in ("apoio", "nao_aluno", "não aluno", "suporte"):
        return "suporte"
    if bruto in ("aluno", "coordenador"):
        return bruto
    return bruto or None


def _serializar_usuario(usuario: dict) -> dict:
    """Normaliza o registro vindo do Supabase para o formato esperado pelo frontend."""
    dados = dict(usuario)
    dados["tipo"] = _normalizar_tipo(dados.get("perfil"), dados.get("tipo"))
    return dados


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(token_data: dict = Depends(verify_firebase_token)):
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

    return _serializar_usuario(dados[0])


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Cadastro de usuário (aluno, coordenador ou suporte)",
)
def cadastrar_usuario(dados: UserRegisterRequest):
    """
    1. Valida os dados (Pydantic): aluno exige matrícula; todos exigem CPF válido.
    2. Cria o usuário no Firebase Auth.
    3. Insere o registro complementar na tabela `usuarios` do Supabase.
    """
    email = str(dados.email).strip().lower()

    existente = (
        supabase.table("usuarios").select("id").eq("email", email).limit(1).execute()
    )
    if existente.data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="E-mail já cadastrado.",
        )

    cpf_digits = _somente_digitos(dados.cpf)
    if cpf_digits:
        cpf_existente = (
            supabase.table("usuarios").select("id").eq("cpf", cpf_digits).limit(1).execute()
        )
        if cpf_existente.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="CPF já cadastrado.",
            )

    matricula = _normalizar_matricula(dados.matricula) if dados.tipo == "aluno" else None
    if matricula:
        mat_existente = (
            supabase.table("usuarios")
            .select("id")
            .eq("matricula", matricula)
            .limit(1)
            .execute()
        )
        if mat_existente.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Matrícula já cadastrada.",
            )

    try:
        firebase_user = firebase_auth.create_user(
            email=email,
            password=dados.senha,
            display_name=dados.nome,
        )
    except Exception as exc:
        mensagem = str(exc)
        if "EMAIL_EXISTS" in mensagem or "email-already-exists" in mensagem:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="E-mail já cadastrado.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao criar usuário no Firebase: {mensagem}",
        )

    perfil, tipo = PERFIL_POR_TIPO[dados.tipo]
    carga_horaria = dados.carga_horaria_semanal
    if tipo == "coordenador" and carga_horaria is None:
        carga_horaria = 20

    insert_data = {
        "nome": dados.nome.strip(),
        "email": email,
        "perfil": perfil,
        "tipo": tipo,
        "telefone": dados.telefone,
        "cpf": cpf_digits,
        "matricula": matricula,
        "carga_horaria_semanal": carga_horaria,
    }

    try:
        supabase.table("usuarios").insert(insert_data).execute()
    except Exception as exc:
        # Rollback: remove o usuário criado no Firebase se o banco falhar.
        try:
            firebase_auth.delete_user(firebase_user.uid)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Erro ao salvar no banco de dados: {str(exc)}",
        )

    return UserRegisterResponse(
        uid=firebase_user.uid,
        mensagem="Usuário cadastrado com sucesso.",
        perfil=perfil,
    )


@router.post(
    "/resolve-identifier",
    response_model=IdentifierResolveResponse,
    summary="Resolve CPF/Matrícula/E-mail para o e-mail cadastrado",
)
def resolver_identificador(dados: IdentifierResolveRequest):
    """
    Recebe um e-mail, CPF ou matrícula e retorna o e-mail correspondente
    cadastrado na tabela `usuarios`, permitindo o login via Firebase
    (signInWithEmailAndPassword).
    """
    valor = (dados.identificador or "").strip()
    if not valor:
        return IdentifierResolveResponse(email=None, encontrado=False)

    if "@" in valor:
        email = valor.lower()
        res = (
            supabase.table("usuarios")
            .select("email")
            .eq("email", email)
            .limit(1)
            .execute()
        )
        if res.data:
            return IdentifierResolveResponse(email=res.data[0]["email"], encontrado=True)
        return IdentifierResolveResponse(email=None, encontrado=False)

    cpf_digits = _somente_digitos(valor)
    if cpf_digits and len(cpf_digits) == 11:
        res = (
            supabase.table("usuarios")
            .select("email")
            .eq("cpf", cpf_digits)
            .limit(1)
            .execute()
        )
        if res.data:
            return IdentifierResolveResponse(email=res.data[0]["email"], encontrado=True)

    matricula = _normalizar_matricula(valor)
    if matricula:
        res = (
            supabase.table("usuarios")
            .select("email")
            .eq("matricula", matricula)
            .limit(1)
            .execute()
        )
        if res.data:
            return IdentifierResolveResponse(email=res.data[0]["email"], encontrado=True)

    return IdentifierResolveResponse(email=None, encontrado=False)
