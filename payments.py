import hmac
import hashlib
import base64
import io
import discord
from mercadopago import SDK
from config import MP_TOKEN, MP_WEBHOOK_SECRET

sdk = SDK(MP_TOKEN)

def is_valid_webhook_signature(body: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header:
        return False
    try:
        parts = dict(item.split('=') for item in signature_header.split(','))
        ts = parts['ts']
        v1 = parts['v1']
        expected = hmac.new(secret.encode(), f"{ts}:{body.decode()}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False

async def criar_pagamento_pix(produto: dict, user_id: int, user_name: str, cpf: str) -> dict:
    payment_data = {
        "transaction_amount": float(produto["preco"]),
        "description": f"{produto['nome']} - Nexzy Store",
        "payment_method_id": "pix",
        "payer": {
            "email": f"nexzy_{user_id}@nexzystore.com.br",
            "first_name": user_name[:50],
            "identification": {"type": "CPF", "number": cpf}
        },
        "statement_descriptor": "NEXZY STORE"
    }
    payment = sdk.payment().create(payment_data)
    resp = payment["response"]
    if "id" not in resp:
        raise Exception(f"Erro ao criar pagamento: {resp}")
    return resp

async def gerar_embed_pix(produto: dict, payment_response: dict, pedido_id: str, desconto_info: str = ""):
    from utils import formatar_preco
    pix_data = payment_response["point_of_interaction"]["transaction_data"]
    qr_code_base64 = pix_data.get("qr_code_base64")
    qr_code_text = pix_data["qr_code"]

    embed = discord.Embed(
        title="💳 PAGAMENTO VIA PIX",
        description=f"**{produto['emoji']} {produto['nome']}**\n💰 **{formatar_preco(produto['preco'])}**{desconto_info}",
        color=0x3d3d3d
    )
    embed.add_field(name="🏢 Destinatário", value="**NEXZY STORE**", inline=True)
    embed.add_field(name="⏰ Validade", value="**30 minutos**", inline=True)
    embed.add_field(name="🆔 Pedido", value=f"`{pedido_id}`", inline=False)

    if qr_code_base64:
        qr_bytes = base64.b64decode(qr_code_base64)
        qr_file = discord.File(io.BytesIO(qr_bytes), filename="qrcode.png")
        embed.set_image(url="attachment://qrcode.png")
        embed.add_field(name="📱 Código PIX", value=f"```\n{qr_code_text[:300]}\n```", inline=False)
        embed.add_field(name="📌 Instruções", value="1. Leia o QR Code ou copie o código\n2. Pague no app do seu banco\n3. Clique em **✅ JÁ PAGUEI**", inline=False)
        return embed, qr_file
    else:
        embed.add_field(name="📋 Código PIX", value=f"```\n{qr_code_text[:300]}\n```", inline=False)
        embed.add_field(name="📌 Instruções", value="Copie o código e pague no seu banco", inline=False)
        return embed, None
