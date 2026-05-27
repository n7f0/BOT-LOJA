import discord
from discord.ext import commands
import database as db
from crypto import validar_arquivo_seguro, verificar_7zip, instalar_7zip
from utils import log_admin, formatar_preco
from core import atualizar_loja, atualizar_vendas

class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_check(self, ctx):
        cfg = await db.get_guild_config(ctx.guild.id)
        if not any(r.id == cfg["cargo_dono"] for r in ctx.author.roles):
            raise commands.MissingPermissions(["cargo_dono"])
        return True

    @commands.command(name="upload")
    async def upload_arquivo(self, ctx, produto_id: str = None):
        if not produto_id:
            return await ctx.reply("❌ Uso: `!upload <produto_id>` com arquivo anexado.", delete_after=15)
        if not ctx.message.attachments:
            return await ctx.reply("❌ Nenhum arquivo anexado.", delete_after=10)
        produtos = await db.get_produtos()
        if produto_id not in produtos:
            return await ctx.reply(f"❌ Produto `{produto_id}` não encontrado.\nIDs: {', '.join(produtos.keys())}", delete_after=15)
        att = ctx.message.attachments[0]
        if att.size / 1024 / 1024 > 25:
            return await ctx.reply(f"❌ Arquivo muito grande: **{att.size/1024/1024:.1f} MB** (max 25MB)", delete_after=15)
        dados = await att.read()
        ok, motivo = validar_arquivo_seguro(dados, att.filename)
        if not ok:
            return await ctx.reply(f"❌ Arquivo rejeitado: {motivo}", delete_after=15)
        msg = await ctx.reply(f"⏳ Salvando **{att.filename}**...")
        try:
            await db.salvar_arquivo_produto(produto_id, att.filename, dados)
            await msg.edit(content=f"✅ Arquivo **{att.filename}** salvo!\nProduto: `{produto_id}` — **{produtos[produto_id]['nome']}**")
            await atualizar_loja(ctx.guild.id)
            await log_admin(self.bot, "Upload de Arquivo", ctx.author, f"**{att.filename}** • Produto `{produto_id}`", guild_id=ctx.guild.id)
        except Exception as e:
            await msg.edit(content=f"❌ Erro: {e}")

    @commands.command(name="remover_arquivo")
    async def remover_arquivo(self, ctx, produto_id: str = None):
        if not produto_id:
            return await ctx.reply("❌ Use: `!remover_arquivo <produto_id>`")
        await db.remover_arquivo_produto(produto_id)
        await ctx.reply(f"✅ Arquivo removido do produto `{produto_id}`.")
        await atualizar_loja(ctx.guild.id)
        await log_admin(self.bot, "Arquivo Removido", ctx.author, f"Produto `{produto_id}`", guild_id=ctx.guild.id)

    @commands.command(name="check7z")
    async def check7z(self, ctx):
        if verificar_7zip():
            import subprocess
            result = subprocess.run(["7z", "i"], capture_output=True, text=True, timeout=5)
            await ctx.reply(f"✅ **7-Zip instalado!**\n`{result.stdout.strip()}`")
        else:
            await ctx.reply("❌ **7-Zip NÃO encontrado.** Use `!instalar7z` para instalar.")

    @commands.command(name="instalar7z")
    async def instalar7z(self, ctx):
        msg = await ctx.reply("⏳ Instalando 7-Zip... (30s)")
        if instalar_7zip() and verificar_7zip():
            await msg.edit(content="✅ **7-Zip instalado com sucesso!**")
            await log_admin(self.bot, "7-Zip Instalado", ctx.author, "Instalação concluída", guild_id=ctx.guild.id)
        else:
            await msg.edit(content="❌ Falha na instalação.")

    @commands.command(name="criar_cupom")
    async def criar_cupom(self, ctx, codigo: str, tipo: str, valor: float, validade_dias: int = 30, usos_maximo: int = 1):
        if tipo not in ("percentual", "fixo"):
            return await ctx.reply("Tipo deve ser `percentual` ou `fixo`")
        from datetime import datetime, timedelta
        validade = datetime.utcnow() + timedelta(days=validade_dias)
        await db.criar_cupom(codigo.upper(), tipo, valor, validade, usos_maximo)
        await ctx.reply(f"✅ Cupom `{codigo.upper()}` criado: {tipo} {valor} - válido até {validade.date()}")
        await log_admin(self.bot, "Cupom Criado", ctx.author, f"{codigo} - {tipo} {valor}", guild_id=ctx.guild.id)

    @commands.command(name="relatorio")
    async def relatorio(self, ctx, dias: int = 30):
        vendas = await db.get_vendas_periodo(dias)
        total = sum(v["valor"] for v in vendas)
        qtd = len(vendas)
        embed = discord.Embed(title=f"📊 Relatório dos últimos {dias} dias", color=0x4a4a4a)
        embed.add_field(name="Vendas", value=qtd, inline=True)
        embed.add_field(name="Faturamento", value=formatar_preco(total), inline=True)
        embed.add_field(name="Ticket médio", value=formatar_preco(total/qtd if qtd else 0), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="setconfig")
    async def setconfig(self, ctx, tipo: str, canal: discord.TextChannel = None):
        if tipo == "cargo_dono":
            if not canal:
                return await ctx.reply("Menção um cargo: `!setconfig cargo_dono @Admin`")
            await db.set_guild_config(ctx.guild.id, cargo_dono=canal.id)
            await ctx.reply(f"✅ Cargo dono definido para {canal.mention}")
        elif tipo in ("loja", "vendas", "log_vendas", "log_admin"):
            if not canal:
                return await ctx.reply(f"Informe um canal: `!setconfig {tipo} #canal`")
            mapping = {"loja":"canal_loja", "vendas":"canal_vendas", "log_vendas":"canal_log_vendas", "log_admin":"canal_log_admin"}
            await db.set_guild_config(ctx.guild.id, **{mapping[tipo]: canal.id})
            await ctx.reply(f"✅ Canal {tipo} definido para {canal.mention}")
            if tipo == "loja":
                await atualizar_loja(ctx.guild.id)
        else:
            await ctx.reply("Tipos válidos: loja, vendas, log_vendas, log_admin, cargo_dono")

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
