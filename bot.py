import discord
from discord.ext import commands
import asyncio
import sys
import signal
import database as db
from config import DISCORD_TOKEN
from utils import criar_embed, formatar_preco
from views import LojaButtons
import admin_commands
import web_dashboard
from crypto import verificar_7zip, instalar_7zip
from payments import is_valid_webhook_signature
from aiohttp import web

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# Variáveis globais para mensagens da loja/vendas (evita deletar)
loja_messages = {}
vendas_messages = {}

async def atualizar_loja_global(guild_id: int):
    cfg = await db.get_guild_config(guild_id)
    canal = bot.get_channel(cfg["canal_loja"])
    if not canal:
        return
    embed = await montar_embed_loja(guild_id)
    # Se já existe mensagem, edita
    if guild_id in loja_messages:
        try:
            msg = await canal.fetch_message(loja_messages[guild_id])
            await msg.edit(embed=embed, view=LojaButtons())
            return
        except:
            pass
    # Senão, envia nova
    msg = await canal.send(embed=embed, view=LojaButtons())
    loja_messages[guild_id] = msg.id

async def atualizar_vendas_global(guild_id: int):
    cfg = await db.get_guild_config(guild_id)
    canal = bot.get_channel(cfg["canal_vendas"])
    if not canal:
        return
    embed = await montar_embed_vendas_global(guild_id)
    if guild_id in vendas_messages:
        try:
            msg = await canal.fetch_message(vendas_messages[guild_id])
            await msg.edit(embed=embed)
            return
        except:
            pass
    msg = await canal.send(embed=embed)
    vendas_messages[guild_id] = msg.id

async def montar_embed_loja(guild_id: int):
    produtos = await db.get_produtos()
    embed = criar_embed(titulo="**🖤  N E X Z Y  S T O R E**",
                        descricao="╔══════════════════════════╗\n💎 **Compre via PIX e receba em canal exclusivo!**\n🔐 Arquivo criptografado + senha única\n⏰ Canal expira em **5 minutos**\n╚══════════════════════════╝",
                        cor=0x1a1a1a)
    for pid, p in produtos.items():
        desc = p.get("descricao") or ""
        arquivo = "📂 Arquivo incluído" if p.get("arquivo_nome") else "🔑 Acesso imediato"
        embed.add_field(name=f"{p['emoji']}  {p['nome']}",
                        value=f"**{formatar_preco(p['preco'])}**\n🆔 `{pid}`\n{arquivo}" + (f"\n> {desc}" if desc else ""),
                        inline=True)
    embed.set_footer(text="⚫ NEXZY STORE • Clique em 💰 COMPRAR")
    embed.timestamp = discord.utils.utcnow()
    return embed

async def montar_embed_vendas_global(guild_id: int):
    total, qtd = await db.get_vendas()
    embed = criar_embed(titulo="📊 ESTATÍSTICAS — NEXZY STORE", cor=0x4a4a4a)
    embed.add_field(name="📦 Vendas", value=f"**{qtd}** pedidos", inline=True)
    embed.add_field(name="💰 Faturamento", value=f"**{formatar_preco(total)}**", inline=True)
    embed.add_field(name="📈 Ticket Médio", value=formatar_preco(total/qtd) if qtd else "R$ 0,00", inline=True)
    return embed

async def entregar_produto_global(user, produto: dict, pedido_id: str, guild, dados_arquivo_override=None, nome_arquivo_override=None):
    from crypto import gerar_senha_segura, criar_7z_criptografado
    from utils import sanitizar_nome_canal, log_venda, log_admin
    import discord, io, asyncio
    senha_arquivo = None
    tem_arquivo = False
    dados_raw = None
    nome_original = None
    if dados_arquivo_override is not None:
        tem_arquivo = True
        senha_arquivo = gerar_senha_segura()
        dados_raw = dados_arquivo_override
        nome_original = nome_arquivo_override or "arquivo_nexzy"
    else:
        prod_completo = await db.get_produto_completo(produto["id"])
        if prod_completo and prod_completo["arquivo_data"]:
            tem_arquivo = True
            senha_arquivo = gerar_senha_segura()
            dados_raw = prod_completo["arquivo_data"]
            nome_original = prod_completo["arquivo_nome"] or f"produto_{produto['id']}"
    # Criar canal temporário
    cfg = await db.get_guild_config(guild.id)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
        user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
    }
    cargo_dono = guild.get_role(cfg["cargo_dono"])
    if cargo_dono:
        overwrites[cargo_dono] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
    nome_canal = f"🛒-compra-{sanitizar_nome_canal(user.name)}"
    canal_temp = await guild.create_text_channel(name=nome_canal, overwrites=overwrites, reason=f"Entrega {pedido_id}")
    # Embed
    embed = discord.Embed(title="🖤 NEXZY STORE — COMPRA APROVADA", description=f"> Olá, **{user.display_name}**! Seu pagamento foi confirmado.\n> ⚠️ **Este canal será excluído em 5 minutos!**", color=0x2b2b2b)
    embed.add_field(name="**━━━━━━━━━━━━━━━━━━━━**", value="\u200b", inline=False)
    embed.add_field(name="**📦 Produto**", value=f"{produto['emoji']} {produto['nome']}", inline=True)
    embed.add_field(name="**💳 Valor Pago**", value=f"`{formatar_preco(produto['preco'])}`", inline=True)
    if tem_arquivo:
        embed.add_field(name="**🔐 Senha do Arquivo `.7z`**", value=f"```\n{senha_arquivo}\n```", inline=False)
        embed.add_field(name="**📂 Como extrair**", value="**1.** Baixe o arquivo\n**2.** 7-Zip → Extrair aqui\n**3.** Insira a senha\n\n⚠️ **KEY ÚNICA**", inline=False)
        # Criptografa e envia
        dados_cifrados = await criar_7z_criptografado(dados_raw, nome_original, senha_arquivo)
        nome_saida = f"nexzy_{produto['id']}_{pedido_id[:8]}.7z"
        arquivo_discord = discord.File(io.BytesIO(dados_cifrados), filename=nome_saida)
        await canal_temp.send(embed=embed, file=arquivo_discord)
        # Backup DM
        try:
            await user.send(f"🔐 Backup da sua compra: a senha é `{senha_arquivo}`. Canal expira em 5 min: {canal_temp.mention}")
        except:
            pass
    else:
        await canal_temp.send(embed=embed)
    # Agendamento de exclusão
    async def remover():
        await asyncio.sleep(300)
        try:
            await canal_temp.delete()
        except:
            pass
    asyncio.create_task(remover())
    if not pedido_id.startswith("TESTE-"):
        await db.registrar_venda_realizada(pedido_id, user.id, produto["nome"], produto["preco"])
        await log_venda(bot, pedido_id, user, produto["nome"], produto["preco"], senha_arquivo, guild_id=guild.id)
    else:
        await log_admin(bot, "Teste de Entrega", user, f"Pedido `{pedido_id}`", guild_id=guild.id)

@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}")
    await db.init_db()
    if not verificar_7zip():
        print("⚠️ 7-Zip não encontrado. Instalando...")
        instalar_7zip()
    # Carrega comandos admin
    await admin_commands.setup(bot)
    # Inicia web dashboard
    asyncio.create_task(web_dashboard.start_web_server())
    # Para cada guild configurada, atualiza loja
    for guild in bot.guilds:
        cfg = await db.get_guild_config(guild.id)
        if cfg["canal_loja"]:
            await atualizar_loja_global(guild.id)
        if cfg["canal_vendas"]:
            await atualizar_vendas_global(guild.id)
    print("✅ Pronto!")

# Webhook do Mercado Pago
@bot.listen('on_request')
async def webhook_handler(request):
    # Isso é um placeholder – na prática, você deve usar aiohttp diretamente.
    # Vamos criar uma rota separada, mas como o bot já tem o web_dashboard, adicionamos lá.
    pass

# Adicionar rota webhook no web_dashboard (modificar web_dashboard.py)
# Adicione no web_dashboard.py:
"""
from payments import is_valid_webhook_signature
from mercadopago import SDK
from config import MP_TOKEN, MP_WEBHOOK_SECRET
import database as db
sdk = SDK(MP_TOKEN)

@routes.post('/webhook')
async def webhook_mp(request):
    body = await request.read()
    signature = request.headers.get('x-signature', '')
    if not is_valid_webhook_signature(body, signature, MP_WEBHOOK_SECRET):
        return web.Response(status=401)
    data = await request.json()
    if data.get('type') == 'payment':
        payment_id = data['data']['id']
        info = sdk.payment().get(payment_id)
        if info['response']['status'] == 'approved':
            pedido_id = await db.obter_pedido_por_payment(payment_id)
            if pedido_id:
                pedido = await db.get_pedido(pedido_id)
                if pedido and pedido['status'] == 'pendente':
                    await db.update_pedido(pedido_id, 'aprovado')
                    await db.add_venda(pedido['produto_preco'])
                    # Buscar guild e entregar
                    from bot import entregar_produto_global
                    guild = bot.get_guild(pedido['guild_id'])  # precisa adicionar guild_id na tabela pedidos
                    user = await bot.fetch_user(pedido['user_id'])
                    produto = {'id': pedido['produto_id'], 'nome': pedido['produto_nome'], 'preco': pedido['produto_preco'], 'emoji': '🛒'}
                    await entregar_produto_global(user, produto, pedido_id, guild)
    return web.Response(status=200)
"""

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
