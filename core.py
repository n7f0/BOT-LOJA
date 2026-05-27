import discord
import asyncio
import io
from utils import criar_embed, formatar_preco, sanitizar_nome_canal, log_venda, log_admin
from crypto import gerar_senha_segura, criar_7z_criptografado
import database as db

_bot = None

def set_bot(bot):
    global _bot
    _bot = bot

async def entregar_produto(user, produto: dict, pedido_id: str, guild, dados_arquivo_override=None, nome_arquivo_override=None):
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

    embed = discord.Embed(title="🖤 NEXZY STORE — COMPRA APROVADA", description=f"> Olá, **{user.display_name}**! Seu pagamento foi confirmado.\n> ⚠️ **Este canal será excluído em 5 minutos!**", color=0x2b2b2b)
    embed.add_field(name="**━━━━━━━━━━━━━━━━━━━━**", value="\u200b", inline=False)
    embed.add_field(name="**📦 Produto**", value=f"{produto['emoji']} {produto['nome']}", inline=True)
    embed.add_field(name="**💳 Valor Pago**", value=f"`{formatar_preco(produto['preco'])}`", inline=True)

    if tem_arquivo:
        embed.add_field(name="**🔐 Senha do Arquivo `.7z`**", value=f"```\n{senha_arquivo}\n```", inline=False)
        embed.add_field(name="**📂 Como extrair**", value="**1.** Baixe o arquivo\n**2.** 7-Zip → Extrair aqui\n**3.** Insira a senha\n\n⚠️ **KEY ÚNICA**", inline=False)
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

    async def remover():
        await asyncio.sleep(300)
        try:
            await canal_temp.delete()
        except:
            pass
    asyncio.create_task(remover())

    if not pedido_id.startswith("TESTE-"):
        await db.registrar_venda_realizada(pedido_id, user.id, produto["nome"], produto["preco"])
        await log_venda(_bot, pedido_id, user, produto["nome"], produto["preco"], senha_arquivo, guild_id=guild.id)
    else:
        await log_admin(_bot, "Teste de Entrega", user, f"Pedido `{pedido_id}`", guild_id=guild.id)

async def atualizar_loja(guild_id: int):
    cfg = await db.get_guild_config(guild_id)
    canal = _bot.get_channel(cfg["canal_loja"])
    if not canal:
        return
    embed = await montar_embed_loja(guild_id)
    async for msg in canal.history(limit=10):
        if msg.author == _bot.user:
            try:
                await msg.delete()
            except:
                pass
    await canal.send(embed=embed, view=await get_loja_buttons())

async def atualizar_vendas(guild_id: int):
    cfg = await db.get_guild_config(guild_id)
    canal = _bot.get_channel(cfg["canal_vendas"])
    if not canal:
        return
    embed = await montar_embed_vendas(guild_id)
    async for msg in canal.history(limit=10):
        if msg.author == _bot.user:
            try:
                await msg.delete()
            except:
                pass
    await canal.send(embed=embed)

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

async def montar_embed_vendas(guild_id: int):
    total, qtd = await db.get_vendas()
    embed = criar_embed(titulo="📊 ESTATÍSTICAS — NEXZY STORE", cor=0x4a4a4a)
    embed.add_field(name="📦 Vendas", value=f"**{qtd}** pedidos", inline=True)
    embed.add_field(name="💰 Faturamento", value=f"**{formatar_preco(total)}**", inline=True)
    embed.add_field(name="📈 Ticket Médio", value=formatar_preco(total/qtd) if qtd else "R$ 0,00", inline=True)
    return embed

async def get_loja_buttons():
    from views import LojaButtons
    return LojaButtons()
