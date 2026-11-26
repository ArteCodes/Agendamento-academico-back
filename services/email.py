"""E-mails transacionais disparados pelas mudanças de status do agendamento.

O envio é opcional e controlado por variáveis de ambiente (veja `.env.example`).
Assim como as notificações do sino, o e-mail é um efeito colateral: qualquer
falha é registrada em log e nunca derruba a operação principal.

Cada tentativa de envio é registrada em `public.notificacoes_email`
(supabase/006_notificacoes_email.sql), permitindo auditoria e reenvio futuro.
"""

from __future__ import annotations

import html
import os
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from app.database import supabase

# Carrega o mesmo .env usado por app.database (idempotente).
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(ENV_PATH)

# Somente estes status geram e-mail para o aluno.
STATUS_COM_EMAIL = ("Confirmado", "Cancelado", "Redirecionado")

_TIPO_POR_STATUS = {
    "Confirmado": "confirmado",
    "Cancelado": "cancelado",
    "Redirecionado": "redirecionado",
}

_CORES_STATUS = {
    "Confirmado": "#0f7b3f",
    "Cancelado": "#b42318",
    "Redirecionado": "#b54708",
}

_aviso_configuracao_emitido = False


# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
def _bool_env(nome: str, padrao: bool = False) -> bool:
    valor = os.getenv(nome)
    if valor is None or not valor.strip():
        return padrao
    return valor.strip().lower() in ("1", "true", "sim", "yes", "on")


def _configuracao() -> dict:
    try:
        porta = int(os.getenv("SMTP_PORT", "587"))
    except (TypeError, ValueError):
        porta = 587

    return {
        "habilitado": _bool_env("EMAIL_ENABLED", False),
        "host": (os.getenv("SMTP_HOST") or "").strip(),
        "porta": porta,
        "usuario": (os.getenv("SMTP_USER") or "").strip(),
        "senha": os.getenv("SMTP_PASSWORD") or "",
        "remetente": (os.getenv("SMTP_FROM") or "").strip(),
        "remetente_nome": (os.getenv("SMTP_FROM_NOME") or "Coordenação SER").strip(),
        "starttls": _bool_env("SMTP_STARTTLS", True),
        "ssl": _bool_env("SMTP_SSL", False),
        "url_app": (os.getenv("APP_FRONTEND_URL") or "http://localhost:5173").rstrip("/"),
    }


def email_configurado() -> bool:
    """Retorna True apenas quando o envio está habilitado e minimamente configurado."""
    cfg = _configuracao()
    return bool(cfg["habilitado"] and cfg["host"] and cfg["remetente"])


def resumo_configuracao() -> str:
    """Resumo seguro (sem senha) para scripts e diagnóstico."""
    cfg = _configuracao()
    linhas = [
        f"EMAIL_ENABLED={cfg['habilitado']}",
        f"SMTP_HOST={cfg['host'] or '(não configurado)'}",
        f"SMTP_PORT={cfg['porta']}",
        f"SMTP_SSL={cfg['ssl']}",
        f"SMTP_STARTTLS={cfg['starttls']}",
        f"SMTP_USER={cfg['usuario'] or '(sem autenticação)'}",
        f"SMTP_FROM={cfg['remetente'] or '(não configurado)'}",
        f"APP_FRONTEND_URL={cfg['url_app']}",
    ]
    return "\n".join(linhas)


def _avisar_desativado() -> None:
    global _aviso_configuracao_emitido
    if _aviso_configuracao_emitido:
        return
    _aviso_configuracao_emitido = True
    print(
        "[email] Envio desativado. Defina EMAIL_ENABLED=true, SMTP_HOST e "
        "SMTP_FROM em app/.env para habilitar."
    )


# ---------------------------------------------------------------------------
# Envio
# ---------------------------------------------------------------------------
def _enviar_mensagem(mensagem: EmailMessage, cfg: dict) -> None:
    if cfg["ssl"]:
        conexao = smtplib.SMTP_SSL(cfg["host"], cfg["porta"], timeout=10)
    else:
        conexao = smtplib.SMTP(cfg["host"], cfg["porta"], timeout=10)

    try:
        if not cfg["ssl"] and cfg["starttls"]:
            conexao.ehlo()
            conexao.starttls()
            conexao.ehlo()
        if cfg["usuario"] and cfg["senha"]:
            conexao.login(cfg["usuario"], cfg["senha"])
        conexao.send_message(mensagem)
    finally:
        try:
            conexao.quit()
        except Exception:  # noqa: BLE001 - encerramento best-effort
            pass


def _montar_mensagem(
    cfg: dict,
    destinatario: str,
    assunto: str,
    texto: str,
    html_corpo: str,
) -> EmailMessage:
    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = formataddr((cfg["remetente_nome"], cfg["remetente"]))
    mensagem["To"] = destinatario
    mensagem.set_content(texto)
    mensagem.add_alternative(html_corpo, subtype="html")
    return mensagem


# ---------------------------------------------------------------------------
# Log de envios (public.notificacoes_email)
# ---------------------------------------------------------------------------
def _registrar_envio(
    *,
    agendamento: dict,
    aluno: Optional[dict],
    destinatario: str,
    status_anterior: Optional[str],
    status_novo: str,
    assunto: str,
) -> Optional[int]:
    payload = {
        "agendamento_id": agendamento.get("id"),
        "usuario_id": (aluno or {}).get("id"),
        "destinatario": destinatario,
        "tipo": _TIPO_POR_STATUS.get(status_novo),
        "status_anterior": status_anterior,
        "status_novo": status_novo,
        "assunto": assunto,
        "status_envio": "pendente",
        "tentativas": 0,
    }
    try:
        resultado = supabase.table("notificacoes_email").insert(payload).execute()
        dados = resultado.data or []
        return dados[0].get("id") if dados else None
    except Exception as exc:  # noqa: BLE001 - log não pode quebrar o envio
        print(f"[email] Falha ao registrar envio no banco: {exc}")
        return None


def _finalizar_envio(
    registro_id: Optional[int],
    status_envio: str,
    *,
    erro: Optional[str] = None,
    tentativas: int = 1,
) -> None:
    if registro_id is None:
        return

    dados = {
        "status_envio": status_envio,
        "erro": (erro or "")[:1000] or None,
        "tentativas": tentativas,
    }
    if status_envio == "enviado":
        dados["enviado_em"] = datetime.now().astimezone().isoformat()

    try:
        supabase.table("notificacoes_email").update(dados).eq("id", registro_id).execute()
    except Exception as exc:  # noqa: BLE001 - apenas log
        print(f"[email] Falha ao atualizar o log de envio #{registro_id}: {exc}")


# ---------------------------------------------------------------------------
# Conteúdo
# ---------------------------------------------------------------------------
def _formatar_data(valor) -> str:
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    texto = str(valor or "").strip()
    partes = texto.split("-")
    if len(partes) == 3:
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    return texto or "não informado"


def _nome_aluno(agendamento: dict, aluno: Optional[dict]) -> str:
    return (
        (aluno or {}).get("nome")
        or agendamento.get("aluno")
        or agendamento.get("alunoEmail")
        or "aluno"
    ).strip()


def _detalhes(
    agendamento: dict,
    ator: Optional[dict],
    aluno: Optional[dict],
    observacao: Optional[str],
) -> list[tuple[str, str]]:
    """Pares rótulo/valor exibidos no e-mail (texto puro, sem escape)."""
    itens = [
        ("Aluno", _nome_aluno(agendamento, aluno)),
        ("Atendimento", str(agendamento.get("nome") or "Atendimento").strip()),
        ("Data", _formatar_data(agendamento.get("data"))),
        ("Horário", str(agendamento.get("horario") or "não informado")),
        ("Local", str(agendamento.get("local") or "não informado")),
    ]
    if ator:
        nome_ator = (ator.get("nome") or ator.get("email") or "").strip()
        if nome_ator:
            itens.append(("Alterado por", nome_ator))
    if observacao and observacao.strip():
        itens.append(("Justificativa", observacao.strip()))
    return itens


def _corpo_texto(
    *,
    agendamento: dict,
    status_anterior: Optional[str],
    status_novo: str,
    ator: Optional[dict],
    aluno: Optional[dict],
    observacao: Optional[str],
    url_app: str,
) -> str:
    nome = _nome_aluno(agendamento, aluno)
    linhas = [
        f"Olá, {nome}!",
        "",
        f"O status do seu agendamento #{agendamento.get('id')} foi atualizado.",
        "",
        f"Status anterior: {status_anterior or 'não informado'}",
        f"Novo status: {status_novo}",
        "",
    ]
    for rotulo, valor in _detalhes(agendamento, ator, aluno, observacao):
        linhas.append(f"{rotulo}: {valor}")
    linhas.extend(
        [
            "",
            f"Acompanhe o agendamento em: {url_app}/agendamentos/{agendamento.get('id')}",
            "",
            "Esta é uma mensagem automática do Sistema de Agendamento e Triagem "
            "da Coordenação SER/UNINASSAU.",
        ]
    )
    return "\n".join(linhas)


def _linha_html(rotulo: str, valor: str) -> str:
    return (
        "<tr>"
        '<td style="padding:6px 0;color:#667085;font-size:13px;width:130px;'
        'vertical-align:top;">'
        f"{html.escape(rotulo)}"
        "</td>"
        '<td style="padding:6px 0;color:#101828;font-size:14px;">'
        f"{html.escape(valor)}"
        "</td>"
        "</tr>"
    )


def _corpo_html(
    *,
    agendamento: dict,
    status_anterior: Optional[str],
    status_novo: str,
    ator: Optional[dict],
    aluno: Optional[dict],
    observacao: Optional[str],
    url_app: str,
) -> str:
    nome = html.escape(_nome_aluno(agendamento, aluno))
    cor = _CORES_STATUS.get(status_novo, "#475467")
    linhas = "".join(
        _linha_html(rotulo, valor)
        for rotulo, valor in _detalhes(agendamento, ator, aluno, observacao)
    )
    status_anterior_html = html.escape(status_anterior or "não informado")
    status_novo_html = html.escape(status_novo)
    link = f"{url_app}/agendamentos/{agendamento.get('id')}"

    return f"""\
<!DOCTYPE html>
<html lang="pt-BR">
  <body style="margin:0;padding:0;background:#f2f4f7;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f2f4f7;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                 style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;
                        font-family:Arial,Helvetica,sans-serif;">
            <tr>
              <td style="background:#0b3b66;padding:20px 24px;color:#ffffff;">
                <div style="font-size:13px;letter-spacing:0.08em;text-transform:uppercase;opacity:0.85;">
                  Coordenação SER · UNINASSAU
                </div>
                <div style="font-size:20px;font-weight:bold;margin-top:4px;">
                  Atualização do seu agendamento
                </div>
              </td>
            </tr>
            <tr>
              <td style="padding:24px;">
                <p style="margin:0 0 16px;font-size:15px;color:#101828;">Olá, {nome}!</p>
                <p style="margin:0 0 16px;font-size:15px;color:#101828;">
                  O status do seu agendamento <strong>#{agendamento.get('id')}</strong> foi atualizado.
                </p>
                <p style="margin:0 0 20px;font-size:14px;color:#475467;">
                  Status anterior: <strong>{status_anterior_html}</strong><br />
                  Novo status:
                  <span style="display:inline-block;margin-top:6px;padding:4px 10px;border-radius:999px;
                               background:{cor};color:#ffffff;font-size:13px;font-weight:bold;">
                    {status_novo_html}
                  </span>
                </p>
                <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                       style="border-top:1px solid #eaecf0;border-bottom:1px solid #eaecf0;">
                  {linhas}
                </table>
                <p style="margin:24px 0 0;text-align:center;">
                  <a href="{html.escape(link, quote=True)}"
                     style="display:inline-block;background:#0b3b66;color:#ffffff;text-decoration:none;
                            font-size:14px;font-weight:bold;padding:12px 24px;border-radius:8px;">
                    Ver agendamento
                  </a>
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 24px 24px;font-size:12px;color:#98a2b3;text-align:center;">
                Esta é uma mensagem automática do Sistema de Agendamento e Triagem
                da Coordenação SER/UNINASSAU.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def enviar_email_status(
    *,
    agendamento: dict,
    status_novo: str,
    destinatario: str,
    ator: Optional[dict] = None,
    aluno: Optional[dict] = None,
    status_anterior: Optional[str] = None,
    observacao: Optional[str] = None,
) -> bool:
    """Envia o e-mail de mudança de status. Nunca levanta exceção."""
    if status_novo not in STATUS_COM_EMAIL:
        return False

    destinatario = (destinatario or "").strip().lower()
    if not destinatario or "@" not in destinatario:
        return False

    if not email_configurado():
        _avisar_desativado()
        return False

    cfg = _configuracao()
    assunto = f"Agendamento #{agendamento.get('id')}: status atualizado para {status_novo}"

    registro_id = _registrar_envio(
        agendamento=agendamento,
        aluno=aluno,
        destinatario=destinatario,
        status_anterior=status_anterior,
        status_novo=status_novo,
        assunto=assunto,
    )

    try:
        texto = _corpo_texto(
            agendamento=agendamento,
            status_anterior=status_anterior,
            status_novo=status_novo,
            ator=ator,
            aluno=aluno,
            observacao=observacao,
            url_app=cfg["url_app"],
        )
        html_corpo = _corpo_html(
            agendamento=agendamento,
            status_anterior=status_anterior,
            status_novo=status_novo,
            ator=ator,
            aluno=aluno,
            observacao=observacao,
            url_app=cfg["url_app"],
        )
        mensagem = _montar_mensagem(cfg, destinatario, assunto, texto, html_corpo)
        _enviar_mensagem(mensagem, cfg)
    except Exception as exc:  # noqa: BLE001 - e-mail não pode derrubar a operação
        print(f"[email] Falha ao enviar para {destinatario}: {exc}")
        _finalizar_envio(registro_id, "falha", erro=str(exc))
        return False

    _finalizar_envio(registro_id, "enviado")
    print(
        f"[email] Status '{status_novo}' do agendamento #{agendamento.get('id')} "
        f"enviado para {destinatario}."
    )
    return True


def enviar_email_teste(destinatario: str, nome: Optional[str] = None) -> bool:
    """Envia uma mensagem simples para validar a configuração SMTP."""
    destinatario = (destinatario or "").strip().lower()
    if not destinatario or "@" not in destinatario:
        print("[email] Informe um destinatário válido (ex.: aluno@teste.com).")
        return False

    if not email_configurado():
        print(resumo_configuracao())
        _avisar_desativado()
        return False

    cfg = _configuracao()
    saudacao = f"Olá, {nome}!" if nome else "Olá!"
    texto = "\n".join(
        [
            saudacao,
            "",
            "Este é um e-mail de teste do Sistema de Agendamento e Triagem.",
            "Se você recebeu esta mensagem, a configuração SMTP está funcionando.",
            "",
            f"Servidor: {cfg['host']}:{cfg['porta']}",
            "",
            "Coordenação SER/UNINASSAU.",
        ]
    )
    html_corpo = f"""\
<!DOCTYPE html>
<html lang="pt-BR">
  <body style="margin:0;padding:0;background:#f2f4f7;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
           style="background:#f2f4f7;padding:24px 12px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0"
                 style="max-width:560px;background:#ffffff;border-radius:12px;
                        font-family:Arial,Helvetica,sans-serif;">
            <tr>
              <td style="background:#0b3b66;padding:20px 24px;color:#ffffff;
                         font-size:20px;font-weight:bold;">
                Teste de e-mail
              </td>
            </tr>
            <tr>
              <td style="padding:24px;font-size:15px;color:#101828;">
                <p style="margin:0 0 16px;">{html.escape(saudacao)}</p>
                <p style="margin:0 0 16px;">
                  Este é um e-mail de teste do Sistema de Agendamento e Triagem.
                  Se você recebeu esta mensagem, a configuração SMTP está funcionando.
                </p>
                <p style="margin:0;color:#475467;font-size:14px;">
                  Servidor: {html.escape(cfg['host'])}:{cfg['porta']}
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

    try:
        mensagem = _montar_mensagem(
            cfg,
            destinatario,
            "Teste de e-mail - Sistema de Agendamento",
            texto,
            html_corpo,
        )
        _enviar_mensagem(mensagem, cfg)
    except Exception as exc:  # noqa: BLE001 - script de diagnóstico
        print(f"[email] Falha ao enviar o teste para {destinatario}: {exc}")
        return False

    print(f"[email] E-mail de teste enviado para {destinatario}.")
    return True
