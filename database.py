
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

# Carrega as variáveis do arquivo .env que está dentro de app/
ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(ENV_PATH)

# Credenciais do Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Verifica se as credenciais foram configuradas
if not SUPABASE_URL:
    raise ValueError(
        "Variável SUPABASE_URL não encontrada no .env. "
        "Configure a URL do projeto Supabase em app/.env (ex: https://seu-projeto.supabase.co)."
    )
if not SUPABASE_KEY:
    raise ValueError(
        "Variável SUPABASE_KEY não encontrada no .env. "
        "Configure a chave pública do Supabase em app/.env."
    )

# Cria a conexão com o Supabase
supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

def get_db():
    return supabase
