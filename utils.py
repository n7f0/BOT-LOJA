import re
from datetime import datetime
import discord
from config import COR_PRINCIPAL, COR_SUCESSO, COR_ERRO, COR_PENDENTE, COR_DESTAQUE

def sanitizar_nome_canal(nome: str) -> str:
    safe = re.sub(r'[^a-z0-9-]', '-', nome.lower())
    safe = re.sub(r'-+', '-', safe).strip('-')
    return safe[:32]

def criar_embed(titulo="", descricao="", cor=COR_PRINCIPAL):
    embed = discord.Embed(title=titulo, description=descricao, color=cor)
    embed.set_footer(text="⚫ NEXZY STORE")
    embed.timestamp = datetime.utcnow()
    return embed

def parse_emoji(emoji_str: str):
    if not emoji_str:
        return None
    match = re.match(r'<(a?):(\w+):(\d+)>', emoji_str)
    if match:
        animated = match.group(1) == 'a'
        name = match.group(2)
        emoji_id = int(match.group(3))
        return discord.PartialEmoji(animated=animated, name=name, id=emoji_id)
    return emoji_str

def formatar_preco(v):
    return f"R$ {float(v):.2f}".replace(".", ",")

async def log_venda(bot, pedido_id, user, produto, valor, senha_arquivo=None, guild_id=None):
    from database import get_guild_config
    cfg = await get_guild_config(guild_id or 0)
    canal = bot.get_channel(cfg["canal_log_vendas"])
    if not canal:
        return
    embed = criar_embed(titulo="🖤 VENDA FINALIZADA", descricao="Nova compra aprovada!", cor=COR_SUCESSO)
    embed.add_field(name="🆔 Pedido", value=f"`{pedido_id}`", inline=True)
    embed.add_field(name="👤 Comprador", value=f"<@{user.id}> ({user.name})", inline=True)
    embed.add_field(name="📦 Produto", value=produto, inline=True)
    embed.add_field(name="💰 Valor", value=formatar_preco(valor), inline=True)
    embed.add_field(name="🔐 Senha", value=f"`{senha_arquivo}`" if senha_arquivo else "Sem arquivo", inline=False)
    await canal.send(embed=embed)

async def log_admin(bot, acao, admin, detalhes, cor=COR_DESTAQUE, guild_id=None):
    from database import get_guild_config
    cfg = await get_guild_config(guild_id or 0)
    canal = bot.get_channel(cfg["canal_log_admin"])
    if not canal:
        return
    embed = criar_embed(titulo=f"⚙️ ADMIN • {acao}", descricao=detalhes, cor=cor)
    embed.add_field(name="👑 Admin", value=f"<@{admin.id}> ({admin.name})", inline=True)
    await canal.send(embed=embed)
