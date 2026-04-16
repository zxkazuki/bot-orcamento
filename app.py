import json
import os
import logging
import boto3
from flask import Flask, request, jsonify
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Histórico de conversa por chat_id: { chat_id: [{"role": "user/assistant", "content": "..."}] }
conversation_history = {}

TELEGRAM_ORCAMENTOS_TOKEN = os.environ.get("TELEGRAM_ORCAMENTOS_TOKEN", "")
TELEGRAM_ORCAMENTISTA_TOKEN = os.environ.get("TELEGRAM_ORCAMENTISTA_TOKEN", "")
CHAT_ID_ORCAMENTISTA = os.environ.get("CHAT_ID_ORCAMENTISTA", "")

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
KB_ID = os.environ.get("KB_ID", "LY3SXOJI2N")

SYSTEM_PROMPT = """Você é o assistente corporativo "Orçamentista Leograf".
Sua função é validar automaticamente solicitações de orçamento gráfico enviadas por vendedores internos antes de encaminhar para análise técnica do time de orçamentos.

OBJETIVO DO ASSISTENTE
Validar se a solicitação contém todos os campos obrigatórios:
- Produto
- Quantidade
- Formato
- Papel
- Gramatura
- Cores
- Acabamento

INTERPRETAÇÃO DAS SOLICITAÇÕES
Aceite mensagens:
- curtas
- fora de ordem
- parcialmente estruturadas
- com abreviações técnicas
- estilo WhatsApp

Exemplo válido:
folder 1000 couche 4x4 dobra simples

DEFINIÇÃO DOS CAMPOS
Produto: tipo de material gráfico solicitado
Quantidade: volume solicitado
Formato: dimensão final do material
Papel: material base de impressão
Gramatura: peso do papel em g/m²
Cores: padrão frente x verso (exemplo: 4x4, 4x0, 1x1)
Acabamento: processos adicionais após impressão

REGRAS DE VALIDAÇÃO
Se algum campo obrigatório estiver ausente: listar apenas os campos faltantes
Se houver inconsistência técnica: informar de forma objetiva
Exemplo: cartão de visita em papel 90g → gramatura incompatível com produto

SUGESTÕES AUTOMÁTICAS INTELIGENTES
Se faltar PAPEL: sugerir opções compatíveis com o produto informado
Se faltar GRAMATURA: sugerir gramaturas compatíveis com o papel informado
Se faltar CORES: sugerir padrões comuns compatíveis com o produto informado
Se faltar ACABAMENTO: sugerir acabamentos comuns compatíveis com o produto informado
Nunca escolher automaticamente pelo vendedor. Sempre solicitar confirmação.

FORMATO DE RESPOSTA — PENDÊNCIAS
Se existirem campos faltantes, responder exatamente assim:
Pendências identificadas no pedido:
- campo X
- campo Y

Se existirem sugestões técnicas, adicionar:
Sugestões técnicas:
- sugestão 1
- sugestão 2
- sugestâo 3

Finalizar sempre com:
Favor complementar as informações para continuidade do orçamento.

FORMATO DE RESPOSTA — PEDIDO COMPLETO
Se todos os campos estiverem presentes, responder exatamente assim:
Pedido completo.

Resumo do pedido:
- Produto: <valor identificado>
- Quantidade: <valor identificado>
- Formato: <valor identificado>
- Papel: <valor identificado>
- Gramatura: <valor identificado>
- Cores: <valor identificado>
- Acabamento: <valor identificado>

Encaminhando para análise técnica.

RESTRIÇÕES IMPORTANTES
Nunca:
- calcular preços
- estimar prazo
- alterar dados informados
- assumir informações não fornecidas
- ignorar inconsistências técnicas

PADRÃO DE RESPOSTA
Sempre responder:
- curto
- objetivo
- profissional
- estruturado em lista
- com uma informação por linha"""


@app.route("/webhook", methods=["POST"])
def webhook():
    body = request.get_json(silent=True) or {}
    logger.info("Payload recebido: %s", json.dumps(body, ensure_ascii=False))

    try:
        chat_id, text = parse_telegram_event(body)
    except TelegramParseError as e:
        logger.warning("Payload inválido: %s", str(e))
        return jsonify({"ok": True})

    if not text:
        logger.warning("Mensagem sem texto. chat_id=%s", chat_id)
        return jsonify({"ok": True})

    # Comandos de controle
    if text.lower() in ["/start", "/novo", "/reiniciar"]:
        conversation_history.pop(chat_id, None)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="🔄 Conversa reiniciada. Pode enviar seu pedido de orçamento."
        )
        return jsonify({"ok": True})

    logger.info("Mensagem recebida | chat_id=%s | texto=%s", chat_id, text)

    # Adiciona mensagem do usuário ao histórico
    history = conversation_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": text})

    try:
        ai_response = invoke_bedrock_with_kb(history)
        logger.info("Resposta Bedrock: %s", ai_response)

        # Adiciona resposta da IA ao histórico
        history.append({"role": "assistant", "content": ai_response})

        route_response(chat_id, ai_response)

        # Limpa histórico se pedido foi concluído
        if "Pedido completo." in ai_response:
            conversation_history.pop(chat_id, None)
            logger.info("Histórico limpo após pedido completo. chat_id=%s", chat_id)

    except BedrockError as e:
        logger.error("Falha Bedrock: %s", str(e))
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="❌ Erro ao processar seu pedido. Tente novamente em instantes."
        )

    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# --- Parsing ---

def parse_telegram_event(body):
    message = body.get("message") or body.get("edited_message")
    if not message:
        raise TelegramParseError("Campo 'message' ausente no payload")

    chat_id = message.get("chat", {}).get("id")
    if not chat_id:
        raise TelegramParseError("chat_id ausente")

    text = message.get("text", "").strip()
    return chat_id, text


# --- Bedrock + Knowledge Base ---

def invoke_bedrock_with_kb(history):
    """
    Faz retrieve no Knowledge Base e passa o contexto pro modelo via invoke_model.
    """
    user_text = history[-1]["content"]

    # Passo 1: Buscar contexto no Knowledge Base
    kb_context = ""
    try:
        kb_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
        retrieve_response = kb_client.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": user_text},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": 5
                }
            }
        )
        results = retrieve_response.get("retrievalResults", [])
        if results:
            chunks = [r["content"]["text"] for r in results if r.get("content", {}).get("text")]
            kb_context = "\n\n".join(chunks)
            logger.info("KB retornou %d resultados.", len(chunks))
        else:
            logger.info("KB não retornou resultados.")
    except Exception as e:
        logger.warning("KB retrieve falhou: %s", str(e))

    # Passo 2: Chamar modelo com contexto do KB + histórico
    system_with_kb = SYSTEM_PROMPT
    if kb_context:
        system_with_kb += f"\n\nCONTEXTO DA BASE DE CONHECIMENTO:\n{kb_context}"

    client = boto3.client("bedrock-runtime", region_name=AWS_REGION)
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": system_with_kb,
        "messages": history
    }

    try:
        response = client.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload)
        )
        result = json.loads(response["body"].read())
        return result["content"][0]["text"].strip()
    except Exception as e:
        raise BedrockError(str(e))


# --- Roteamento ---

def route_response(chat_id, ai_response):
    if "Pendências identificadas no pedido:" in ai_response:
        logger.info("Pedido incompleto → respondendo vendedor. chat_id=%s", chat_id)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text=ai_response
        )
    elif "Pedido completo." in ai_response:
        logger.info("Pedido completo → confirmando vendedor e encaminhando orçamentista.")
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text="✅ Pedido validado! Encaminhando ao orçamentista..."
        )
        forward_to_orcamentista(ai_response)
    else:
        logger.warning("Resposta fora do formato esperado: %s", ai_response)
        send_message_to_telegram(
            token=TELEGRAM_ORCAMENTOS_TOKEN,
            chat_id=chat_id,
            text=ai_response
        )


def forward_to_orcamentista(ai_response):
    message = f"📄 *Novo pedido validado automaticamente*\n\n{ai_response}"
    send_message_to_telegram(
        token=TELEGRAM_ORCAMENTISTA_TOKEN,
        chat_id=CHAT_ID_ORCAMENTISTA,
        text=message,
        parse_mode="Markdown"
    )


# --- Telegram ---

def send_message_to_telegram(token, chat_id, text, parse_mode=None):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers={"Content-Type": "application/json"})

    try:
        with urlopen(req, timeout=8) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.error("Telegram API erro: %s", result)
            else:
                logger.info("Mensagem enviada com sucesso. chat_id=%s", chat_id)
    except HTTPError as e:
        logger.error("HTTPError Telegram: %s", e)
    except URLError as e:
        logger.error("URLError Telegram: %s", e)


# --- Exceções ---

class TelegramParseError(Exception):
    pass

class BedrockError(Exception):
    pass


if __name__ == "__main__":
    logger.info("Iniciando servidor local na porta 5000...")
    app.run(host="0.0.0.0", port=5000, debug=False)
