
from fastapi import APIRouter
from app.database import supabase

router = APIRouter()

@router.get("/teste-banco")
def testar_conexao():
    try:
        # Substitua "usuarios" pelo nome de uma tabela existente
        resultado = (
            supabase
            .table("usuarios")
            .select("*")
            .limit(1)
            .execute()
        )

        return {
            "conexao": "sucesso",
            "mensagem": "Backend conectado ao Supabase!",
            "dados": resultado.data
        }

    except Exception as erro:
        return {
            "conexao": "erro",
            "mensagem": str(erro)
        }
