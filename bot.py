import discord
from discord.ext import commands
import asyncio
import database as db
from config import DISCORD_TOKEN
from views import LojaButtons
import admin_commands
import web_dashboard
import core
from crypto import verificar_7zip, instalar_7zip

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

core.set_bot(bot)

@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}")
    await db.init_db()
    if not verificar_7zip():
        print("⚠️ 7-Zip não encontrado. Instalando...")
        instalar_7zip()
    await admin_commands.setup(bot)
    asyncio.create_task(web_dashboard.start_web_server())
    for guild in bot.guilds:
        cfg = await db.get_guild_config(guild.id)
        if cfg["canal_loja"]:
            await core.atualizar_loja(guild.id)
        if cfg["canal_vendas"]:
            await core.atualizar_vendas(guild.id)
    print("✅ Pronto!")

@bot.command(name="loja")
async def cmd_loja(ctx):
    from core import montar_embed_loja
    await ctx.send(embed=await montar_embed_loja(ctx.guild.id), view=LojaButtons())
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="vendas")
async def cmd_vendas(ctx):
    cfg = await db.get_guild_config(ctx.guild.id)
    if not any(r.id == cfg["cargo_dono"] for r in ctx.author.roles):
        return
    from core import montar_embed_vendas
    await ctx.send(embed=await montar_embed_vendas(ctx.guild.id))
    try:
        await ctx.message.delete()
    except:
        pass

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
