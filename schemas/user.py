import re
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import Optional, Literal


class UserResponse(BaseModel):
    id: int
    nome: str
    email: EmailStr
    perfil: str  # 'Aluno', 'Apoio' ou 'Coordenador'
    tipo: Optional[str] = None  # 'aluno', 'coordenador' ou 'suporte'
    matricula: Optional[str] = None
    cpf: Optional[str] = None
    telefone: Optional[str] = None
    carga_horaria_semanal: Optional[int] = None

    class Config:
        from_attributes = True


def _somente_digitos(valor: Optional[str]) -> Optional[str]:
    """Remove máscara, retornando apenas dígitos (ou None)."""
    if not valor:
        return None
    return re.sub(r"\D", "", valor)


def _cpf_valido(digitos: str) -> bool:
    """Valida os dois dígitos verificadores do CPF."""
    if len(digitos) != 11 or digitos == digitos[0] * 11:
        return False
    soma = sum(int(digitos[i]) * (10 - i) for i in range(9))
    resto = soma % 11
    d1 = 0 if resto < 2 else 11 - resto
    if int(digitos[9]) != d1:
        return False
    soma = sum(int(digitos[i]) * (11 - i) for i in range(10))
    resto = soma % 11
    d2 = 0 if resto < 2 else 11 - resto
    return int(digitos[10]) == d2


class UserRegisterRequest(BaseModel):
    nome: str = Field(min_length=2, description="Nome completo do usuário")
    email: EmailStr
    senha: str = Field(min_length=8, description="Senha forte: letras e números")
    telefone: str
    tipo: Literal["aluno", "nao_aluno", "coordenador", "suporte"] = Field(
        default="aluno", description="Tipo padrão: aluno"
    )
    cpf: Optional[str] = None
    matricula: Optional[str] = None
    carga_horaria_semanal: Optional[int] = Field(
        default=None, description="Carga horária semanal (usada para coordenadores)"
    )

    @field_validator("senha")
    @classmethod
    def senha_forte(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v) or not re.search(r"[0-9]", v):
            raise ValueError("A senha deve conter pelo menos uma letra e um número.")
        return v

    @field_validator("cpf")
    @classmethod
    def cpf_valido_campo(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        digitos = _somente_digitos(v)
        if not digitos or len(digitos) != 11 or not _cpf_valido(digitos):
            raise ValueError("CPF inválido.")
        return v

    @model_validator(mode="after")
    def regras_por_tipo(self) -> "UserRegisterRequest":
        if not self.cpf:
            raise ValueError("O CPF é obrigatório.")
        digitos_cpf = _somente_digitos(self.cpf)
        if not digitos_cpf or len(digitos_cpf) != 11 or not _cpf_valido(digitos_cpf):
            raise ValueError("CPF inválido.")
        if self.tipo == "aluno":
            if not self.matricula:
                raise ValueError("A matrícula é obrigatória para alunos.")
        elif self.tipo in ("nao_aluno", "suporte"):
            # Não aluno / suporte não envia matrícula
            self.matricula = None
        elif self.tipo == "coordenador":
            # Coordenador não envia matrícula
            self.matricula = None
        return self


class UserRegisterResponse(BaseModel):
    uid: str
    mensagem: str
    perfil: str


class IdentifierResolveRequest(BaseModel):
    identificador: str = Field(description="E-mail, CPF ou Matrícula")


class IdentifierResolveResponse(BaseModel):
    email: Optional[str] = None
    encontrado: bool = False