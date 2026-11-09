# Sistema de Agendamento e Triagem — API Backend

API RESTful construída com **FastAPI** (Python) que integra **Supabase** (banco) e **Firebase** (autenticação).

---

## 📋 Pré-requisitos

- [x] Python 3.10 ou superior
- [ ] Git
- [ ] Docker (opcional, para Supabase local)

## 🛠️ Configuração do Ambiente

### 1. Clonar e entrar no diretório
```bash
git clone <url-do-repositorio>
cd app
```

### 2. Criar e ativar o ambiente virtual
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate
```

### 3. Instalar dependências
```bash
pip install -r requirements.txt
```
> ⚠️ O arquivo `requirements.txt` ainda não existe. Crie ou ajuste conforme o ambiente.
> Para instalar as principais dependências manualmente, use:
> ```bash
> pip install fastapi uvicorn python-dotenv supabase firebase-admin pydantic sqlalchemy
> ```

### 4. Configurar variáveis de ambiente
```bash
cp .env.example .env
# Edite .env com as credenciais do seu Supabase e Firebase
```

### 5. Iniciar o servidor
```bash
uvicorn main:app --reload --port 8000
```

## 🧪 Testar a API

### Verificar se o banco está conectado
```bash
curl http://localhost:8000/teste-banco
```

### Documentação da API (Swagger)
Abra no navegador:
```
http://localhost:8000/docs
```

## 📁 Estrutura do Projeto
```
app/
├── main.py             # Entry point FastAPI
├── database.py         # Conexão com Supabase
├── core/
│   └── firebase-credentials.json   # CRÍTICO — nunca subir ao GitHub
├── dependencies/
│   └── auth.py         # Middleware de autenticação
├── routers/
│   ├── auth.py         # Rotas de autenticação
│   └── teste_banco.py  # Teste de conexão com Supabase
├── schemas/
│   └── user.py         # Pydantic models
└── .env.example        # Modelo de variáveis de ambiente
```

## 🚀 Comandos Úteis
```bash
# Rodar com debug
uvicorn main:app --reload

# Rodar em produção (sem reload)
uvicorn main:app --host 0.0.0.0 --port 8000

# Verificar rotas
uvicorn main:app --reload --log-level info
```

---

## ⚠️ Avisos de Segurança
- ✅ **Nunca** suba o `.env` ao GitHub
- ✅ **Nunca** suba o `firebase-credentials.json`
- ✅ Use `.env.example` como referência para outros desenvolvedores
- ✅ Executar `git log --all -p -- .env firebase-credentials.json` para verificar vazamentos

