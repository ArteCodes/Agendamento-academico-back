from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, teste_banco, agendamentos, horarios

app = FastAPI(
    title="Sistema de Agendamento e Triagem",
    description="API do Sistema da Coordenação",
    version="1.0.0"
)

# Configuração de CORS para permitir requisições do Vue.js
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Inclui as rotas com prefixo /api
app.include_router(auth.router, prefix="/api")
app.include_router(teste_banco.router, prefix="/api")
app.include_router(agendamentos.router, prefix="/api")
app.include_router(horarios.router, prefix="/api")

@app.get("/")
def read_root():
    return {"message": "API do Sistema de Agendamento está ativa e a funcionar!"}