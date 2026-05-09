# bot.py - NEXZY STORE - VERSÃO COM ARQUIVO CRIPTOGRAFADO POR COMPRA
import discord
from discord.ext import commands
from discord import Embed, Color
import aiohttp
import mercadopago
import uuid
import asyncio
import os
import asyncpg
import secrets
import random
import string
import subprocess
import tempfile
import shutil
import io
from datetime import datetime, timedelta
from aiohttp import web

# ================= CONFIG =================
CARGO_DONO      = int(os.getenv("CARGO_DONO", "0"))
CANAL_LOJA      = int(os.getenv("CANAL_LOJA", "0"))
CANAL_VENDAS    = int(os.getenv("CANAL_VENDAS", "0"))
DISCORD_TOKEN   = os.getenv("LOJA_DISCORD_TOKEN")
MP_TOKEN        = os.getenv("MERCADO_PAGO_TOKEN")
DATABASE_URL    = os.getenv("DATABASE_URL")
WEBHOOK_LOG_URL = "https://discord.com/api/webhooks/1494018278593663218/thPR-PptRQNKQKvY0Jw9aFVFf7lkxhPp00Bb7Dn2_Ee7nfwFIP2ZOmr7NO6ApAH-H7ts"

for var, nome in [(DISCORD_TOKEN,"LOJA_DISCORD_TOKEN"),(MP_TOKEN,"MERCADO_PAGO_TOKEN"),(DATABASE_URL,"DATABASE_URL")]:
    if not var:
        print(f"❌ {nome} não configurado!")
        exit(1)

if "railwaypostgresql://" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("railwaypostgresql://", "postgresql://")

sdk     = mercadopago.SDK(MP_TOKEN)
intents = discord.Intents.all()
bot     = commands.Bot(command_prefix="!", intents=intents)

db                = None
pedidos_pendentes = {}

# ================= HELPERS =================
def gerar_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

def gerar_key():
    """NEXZY-XXXX-XXXX-XXXX-XXXX  (AES-256 key visual)"""
    p = [''.join(random.choices(string.ascii_uppercase + string.digits, k=4)) for _ in range(4)]
    return f"NEXZY-{'-'.join(p)}"

def formatar_preco(v):
    return f"R$ {float(v):.2f}".replace(".", ",")

def verificar_7zip():
    return shutil.which("7z") is not None

# ================= BANCO =================
async def init_db():
    global db
    try:
        db = await asyncpg.create_pool(DATABASE_URL)
        async with db.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS produtos (
                    id           TEXT PRIMARY KEY,
                    nome         TEXT NOT NULL,
                    preco        REAL NOT NULL,
                    emoji        TEXT DEFAULT '🛒',
                    descricao    TEXT DEFAULT '',
                    arquivo_nome TEXT DEFAULT NULL,
                    arquivo_data BYTEA DEFAULT NULL
                )
            """)
            for col, tipo in [
                ("descricao","TEXT DEFAULT ''"),
                ("arquivo_nome","TEXT DEFAULT NULL"),
                ("arquivo_data","BYTEA DEFAULT NULL")
            ]:
                try:
                    await conn.execute(f"ALTER TABLE produtos ADD COLUMN IF NOT EXISTS {col} {tipo}")
                except Exception:
                    pass

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS pedidos (
                    id            TEXT PRIMARY KEY,
                    user_id       BIGINT NOT NULL,
                    produto_id    TEXT NOT NULL,
                    produto_nome  TEXT NOT NULL,
                    produto_preco REAL NOT NULL,
                    status        TEXT DEFAULT 'pendente',
                    criado_em     TIMESTAMP DEFAULT NOW()
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS vendas (
                    id         SERIAL PRIMARY KEY,
                    total      REAL DEFAULT 0,
                    quantidade INTEGER DEFAULT 0
                )
            """)
            await conn.execute("INSERT INTO vendas (id,total,quantidade) VALUES (1,0,0) ON CONFLICT (id) DO NOTHING")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS keys_entregues (
                    id           SERIAL PRIMARY KEY,
                    pedido_id    TEXT NOT NULL,
                    user_id      BIGINT NOT NULL,
                    produto_nome TEXT NOT NULL,
                    key_valor    TEXT NOT NULL UNIQUE,
                    criado_em    TIMESTAMP DEFAULT NOW()
                )
            """)
            if not await conn.fetch("SELECT id FROM produtos LIMIT 1"):
                await conn.execute("INSERT INTO produtos (id,nome,preco,emoji,descricao) VALUES ('prod1','VIP Bronze',19.90,'🥉','Acesso VIP Bronze')")
                await conn.execute("INSERT INTO produtos (id,nome,preco,emoji,descricao) VALUES ('prod2','VIP Prata',39.90,'🥈','Acesso VIP Prata')")
                await conn.execute("INSERT INTO produtos (id,nome,preco,emoji,descricao) VALUES ('prod3','VIP Ouro',69.90,'🥇','Acesso VIP Ouro')")
        print("✅ Banco conectado!")
        return True
    except Exception as e:
        print(f"❌ Erro banco: {e}")
        return False

async def get_produtos():
    async with db.acquire() as conn:
        rows = await conn.fetch("SELECT id,nome,preco,emoji,descricao,arquivo_nome FROM produtos")
        return {r["id"]: dict(r) for r in rows}

async def get_produto_completo(pid):
    async with db.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM produtos WHERE id=$1", pid)

async def add_produto(pid, nome, preco, emoji, descricao=""):
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO produtos (id,nome,preco,emoji,descricao) VALUES ($1,$2,$3,$4,$5)",
            pid, nome, preco, emoji, descricao
        )

async def edit_produto(pid, nome, preco, emoji, descricao):
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE produtos SET nome=$2,preco=$3,emoji=$4,descricao=$5 WHERE id=$1",
            pid, nome, preco, emoji, descricao
        )

async def salvar_arquivo_produto(pid, nome_arquivo, dados: bytes):
    async with db.acquire() as conn:
        await conn.execute(
            "UPDATE produtos SET arquivo_nome=$2, arquivo_data=$3 WHERE id=$1",
            pid, nome_arquivo, dados
        )

async def remover_arquivo_produto(pid):
    async with db.acquire() as conn:
        await conn.execute("UPDATE produtos SET arquivo_nome=NULL, arquivo_data=NULL WHERE id=$1", pid)

async def remove_produto(pid):
    async with db.acquire() as conn:
        await conn.execute("DELETE FROM produtos WHERE id=$1", pid)

async def add_pedido(pid, user_id, produto_id, nome, preco):
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO pedidos (id,user_id,produto_id,produto_nome,produto_preco) VALUES ($1,$2,$3,$4,$5)",
            pid, user_id, produto_id, nome, preco
        )

async def update_pedido(pid, status):
    async with db.acquire() as conn:
        await conn.execute("UPDATE pedidos SET status=$1 WHERE id=$2", status, pid)

async def get_vendas():
    async with db.acquire() as conn:
        r = await conn.fetchrow("SELECT total,quantidade FROM vendas WHERE id=1")
        return r["total"], r["quantidade"]

async def add_venda(valor):
    async with db.acquire() as conn:
        await conn.execute("UPDATE vendas SET total=total+$1, quantidade=quantidade+1 WHERE id=1", valor)

async def salvar_key(pedido_id, user_id, produto_nome, key_valor):
    async with db.acquire() as conn:
        await conn.execute(
            "INSERT INTO keys_entregues (pedido_id,user_id,produto_nome,key_valor) VALUES ($1,$2,$3,$4)",
            pedido_id, user_id, produto_nome, key_valor
        )

# ================= WEBHOOK LOG =================
async def log_webhook(titulo, descricao, cor=0x00ff99, campos=None):
    try:
        embed = {
            "title": titulo,
            "description": descricao,
            "color": cor,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "NEXZY STORE • Sistema de Logs"},
            "fields": campos or []
        }
        async with aiohttp.ClientSession() as s:
            await s.post(WEBHOOK_LOG_URL, json={"embeds": [embed]})
    except Exception as e:
        print(f"Erro webhook log: {e}")

# ================= CRIPTOGRAFIA 7ZIP =================
def _criar_7z_sync(dados: bytes, nome_original: str, senha: str) -> bytes:
    """
    Executa em thread separada (não bloqueia o event loop).
    Cria arquivo .7z com AES-256 e criptografia de nomes internos.
    O diretório temp é destruído logo após — nada fica em disco.
    """
    tmp = tempfile.mkdtemp(prefix="nexzy_")
    try:
        caminho_original = os.path.join(tmp, nome_original)
        with open(caminho_original, "wb") as f:
            f.write(dados)

        caminho_saida = os.path.join(tmp, "entrega.7z")

        # -p<senha>  = senha AES-256
        # -mhe=on    = criptografa também lista de arquivos internos
        # -mx=0      = sem compressão (só cifra, mais rápido)
        resultado = subprocess.run(
            ["7z", "a", f"-p{senha}", "-mhe=on", "-mx=0", caminho_saida, caminho_original],
            capture_output=True, text=True, timeout=120
        )
        if resultado.returncode != 0:
            raise RuntimeError(f"7zip error: {resultado.stderr.strip()}")

        with open(caminho_saida, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

async def criar_7z_criptografado(dados: bytes, nome_original: str, senha: str) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _criar_7z_sync, dados, nome_original, senha)

# ================= ENTREGA =================
async def entregar_produto(user: discord.User, produto: dict, pedido_id: str):
    key = gerar_key()
    await salvar_key(pedido_id, user.id, produto["nome"], key)

    prod_completo = await get_produto_completo(produto["id"])
    tem_arquivo   = prod_completo and prod_completo["arquivo_data"]

    embed = Embed(
        title="✅  COMPRA APROVADA — NEXZY STORE",
        description=f"Obrigado pela compra, **{user.display_name}**! Seu acesso está pronto abaixo.",
        color=Color.green()
    )
    embed.add_field(name="📦 Produto",        value=produto["nome"],               inline=True)
    embed.add_field(name="💰 Valor Pago",      value=formatar_preco(produto["preco"]), inline=True)
    embed.add_field(name="\u200b",             value="\u200b",                      inline=True)
    embed.add_field(name="🔑 Key de Ativação", value=f"```\n{key}\n```",            inline=False)

    arquivo_discord = None

    if tem_arquivo:
        try:
            # Senha = key sem hifens (32 chars hex-like, derivado da própria key)
            senha_arquivo = key.replace("-", "")

            embed.add_field(
                name="🔐 Senha do Arquivo (.7z)",
                value=f"```\n{senha_arquivo}\n```",
                inline=False
            )
            embed.add_field(
                name="📂 Como extrair",
                value="**1.** Baixe o arquivo `.7z` anexado\n"
                      "**2.** Instale o **7-Zip** (gratuito em 7-zip.org)\n"
                      "**3.** Clique com botão direito → *7-Zip → Extrair aqui*\n"
                      "**4.** Digite a senha acima quando solicitado\n"
                      "⚠️ Este arquivo foi gerado **exclusivamente** para esta compra.",
                inline=False
            )

            dados_cifrados = await criar_7z_criptografado(
                bytes(prod_completo["arquivo_data"]),
                prod_completo["arquivo_nome"],
                senha_arquivo
            )

            nome_saida      = f"nexzy_{produto['id']}_{pedido_id[:8]}.7z"
            arquivo_discord = discord.File(fp=io.BytesIO(dados_cifrados), filename=nome_saida)

        except Exception as e:
            print(f"Erro criptografia: {e}")
            embed.add_field(name="⚠️ Arquivo", value="Erro ao gerar. Entre em contato com o suporte.", inline=False)
    else:
        embed.add_field(
            name="📋 Próximos passos",
            value="Use sua key no painel de ativação ou abra um ticket.",
            inline=False
        )

    embed.set_footer(text="NEXZY STORE — Obrigado pela preferência! 💚")
    embed.timestamp = datetime.utcnow()

    try:
        if arquivo_discord:
            await user.send(embed=embed, file=arquivo_discord)
        else:
            await user.send(embed=embed)
    except discord.Forbidden:
        print(f"❌ DM bloqueada: {user}")

    await log_webhook(
        "💸 Nova Venda!",
        "Compra aprovada e produto entregue.",
        cor=0x2ecc71,
        campos=[
            {"name": "👤 Comprador", "value": f"<@{user.id}> ({user.name})", "inline": True},
            {"name": "📦 Produto",   "value": produto["nome"],               "inline": True},
            {"name": "💰 Valor",     "value": formatar_preco(produto["preco"]), "inline": True},
            {"name": "🔑 Key",       "value": f"`{key}`",                    "inline": False},
            {"name": "📂 Arquivo",   "value": "✅ Enviado" if tem_arquivo else "❌ Sem arquivo", "inline": True},
        ]
    )

# ================= MODALS =================
class ProdutoModal(discord.ui.Modal, title="✨ Adicionar Produto"):
    nome_input      = discord.ui.TextInput(label="📦 Nome",      placeholder="Ex: VIP Premium", required=True)
    preco_input     = discord.ui.TextInput(label="💰 Preço",     placeholder="49.90",           required=True)
    emoji_input     = discord.ui.TextInput(label="😀 Emoji",     placeholder="👑",              required=False, default="🛒")
    descricao_input = discord.ui.TextInput(label="📝 Descrição", placeholder="Breve descrição", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            pid       = gerar_id()
            nome      = self.nome_input.value
            preco     = float(self.preco_input.value.replace(",", "."))
            emoji     = self.emoji_input.value or "🛒"
            descricao = self.descricao_input.value or ""

            produtos = await get_produtos()
            while pid in produtos:
                pid = gerar_id()

            await add_produto(pid, nome, preco, emoji, descricao)

            embed = Embed(title="✅ Produto Adicionado!", color=Color.green())
            embed.add_field(name="🆔 ID",    value=f"`{pid}`",           inline=True)
            embed.add_field(name="📦 Nome",  value=nome,                 inline=True)
            embed.add_field(name="💰 Preço", value=formatar_preco(preco), inline=True)
            embed.add_field(
                name="📂 Vincular arquivo",
                value=f"Envie: `!upload {pid}` com o arquivo `.rar` ou `.zip` anexado.",
                inline=False
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            await atualizar_loja()
            await log_webhook("📦 Produto Adicionado", f"**{nome}** • {formatar_preco(preco)}", cor=0x00ff99,
                              campos=[{"name": "Admin", "value": f"<@{interaction.user.id}>", "inline": True}])
        except Exception as e:
            await interaction.followup.send(f"❌ Erro: {e}", ephemeral=True)


class EditarProdutoModal(discord.ui.Modal, title="✏️ Editar Produto"):
    def __init__(self, produto):
        super().__init__()
        self.produto_id      = produto["id"]
        self.nome_input      = discord.ui.TextInput(label="📦 Nome",      default=produto["nome"],              required=True)
        self.preco_input     = discord.ui.TextInput(label="💰 Preço",     default=str(produto["preco"]),        required=True)
        self.emoji_input     = discord.ui.TextInput(label="😀 Emoji",     default=produto["emoji"],             required=False)
        self.descricao_input = discord.ui.TextInput(label="📝 Descrição", default=produto.get("descricao",""), required=False)
        for item in [self.nome_input, self.preco_input, self.emoji_input, self.descricao_input]:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            nome      = self.nome_input.value
            preco     = float(self.preco_input.value.replace(",", "."))
            emoji     = self.emoji_input.value or "🛒"
            descricao = self.descricao_input.value or ""
            await edit_produto(self.produto_id, nome, preco, emoji, descricao)
            await interaction.followup.send("✅ Produto editado com sucesso!", ephemeral=True)
            await atualizar_loja()
            await log_webhook("✏️ Produto Editado", f"**{nome}**", cor=0x3498db,
                              campos=[{"name": "Admin", "value": f"<@{interaction.user.id}>", "inline": True}])
        except Exception as e:
            await interaction.followup.send(f"❌ Erro: {e}", ephemeral=True)

# ================= SELECTS =================
class RemoverSelect(discord.ui.Select):
    def __init__(self, produtos):
        options = [
            discord.SelectOption(label=f"{p['nome']} ({pid})", value=pid, emoji=p['emoji'])
            for pid, p in produtos.items()
        ]
        super().__init__(placeholder="🗑️ Selecione o produto para remover", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        produtos = await get_produtos()
        produto  = produtos.get(self.values[0])
        nome     = produto["nome"] if produto else self.values[0]
        await remove_produto(self.values[0])
        await interaction.followup.send(f"✅ **{nome}** removido!", ephemeral=True)
        await atualizar_loja()
        await log_webhook("🗑️ Produto Removido", f"**{nome}**", cor=0xe74c3c,
                          campos=[{"name": "Admin", "value": f"<@{interaction.user.id}>", "inline": True}])


class EditarSelect(discord.ui.Select):
    def __init__(self, produtos):
        options = [
            discord.SelectOption(label=f"{p['nome']} — {formatar_preco(p['preco'])}", value=pid, emoji=p['emoji'])
            for pid, p in produtos.items()
        ]
        super().__init__(placeholder="✏️ Selecione o produto para editar", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        produtos = await get_produtos()
        produto  = produtos.get(self.values[0])
        if not produto:
            return await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
        await interaction.response.send_modal(EditarProdutoModal(produto))


class ProdutoSelect(discord.ui.Select):
    def __init__(self, produtos):
        options = [
            discord.SelectOption(label=f"{p['nome']} — {formatar_preco(p['preco'])}", value=pid, emoji=p['emoji'])
            for pid, p in produtos.items()
        ]
        super().__init__(placeholder="🛒 Escolha um produto", options=options[:25])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await iniciar_pagamento(interaction, self.values[0])

# ================= VIEWS =================
class LojaButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💰 Comprar", style=discord.ButtonStyle.success, emoji="🛒")
    async def comprar(self, interaction: discord.Interaction, button: discord.ui.Button):
        produtos = await get_produtos()
        if not produtos:
            return await interaction.response.send_message("❌ Nenhum produto disponível.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(ProdutoSelect(produtos))
        await interaction.response.send_message("📦 **Selecione o produto desejado:**", view=view, ephemeral=True)

    @discord.ui.button(label="👑 Admin", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not any(r.id == CARGO_DONO for r in interaction.user.roles):
            return await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        embed = Embed(title="⚙️ Painel Admin — NEXZY STORE", color=Color.dark_red())
        embed.add_field(name="➕ Adicionar",         value="Cadastra produto",                   inline=True)
        embed.add_field(name="✏️ Editar",            value="Altera nome/preço/emoji",            inline=True)
        embed.add_field(name="🗑️ Remover",           value="Remove produto",                     inline=True)
        embed.add_field(name="🧪 Teste de Entrega",  value="Simula compra (DM)",                 inline=True)
        embed.add_field(name="📊 Estatísticas",      value="Ver faturamento",                    inline=True)
        embed.add_field(name="📂 Upload",            value="`!upload <id>` com arquivo anexado", inline=True)
        embed.set_footer(text="NEXZY STORE — Painel Admin")
        await interaction.response.send_message(embed=embed, view=AdminView(), ephemeral=True)


class AdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.button(label="➕ Adicionar", style=discord.ButtonStyle.success)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProdutoModal())

    @discord.ui.button(label="✏️ Editar", style=discord.ButtonStyle.primary)
    async def editar(self, interaction: discord.Interaction, button: discord.ui.Button):
        produtos = await get_produtos()
        if not produtos:
            return await interaction.response.send_message("❌ Nenhum produto cadastrado.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(EditarSelect(produtos))
        await interaction.response.send_message("✏️ Selecione o produto:", view=view, ephemeral=True)

    @discord.ui.button(label="🗑️ Remover", style=discord.ButtonStyle.danger)
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        produtos = await get_produtos()
        if not produtos:
            return await interaction.response.send_message("❌ Nenhum produto cadastrado.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(RemoverSelect(produtos))
        await interaction.response.send_message("🗑️ Selecione o produto:", view=view, ephemeral=True)

    @discord.ui.button(label="🧪 Teste de Entrega", style=discord.ButtonStyle.secondary)
    async def teste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        produtos = await get_produtos()
        if not produtos:
            return await interaction.followup.send("❌ Nenhum produto.", ephemeral=True)
        produto   = dict(list(produtos.values())[0])
        pedido_id = f"TESTE-{str(uuid.uuid4())[:8]}"
        await interaction.followup.send("⏳ Gerando entrega de teste... (pode levar alguns segundos se houver arquivo)", ephemeral=True)
        await entregar_produto(interaction.user, produto, pedido_id)
        await interaction.edit_original_response(content="✅ Entrega de teste enviada para sua DM!")

    @discord.ui.button(label="📊 Estatísticas", style=discord.ButtonStyle.secondary)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=await montar_embed_vendas(), ephemeral=True)

# ================= PAGAMENTO =================
async def iniciar_pagamento(interaction: discord.Interaction, produto_id: str):
    produtos = await get_produtos()
    produto  = produtos.get(produto_id)
    if not produto:
        return await interaction.followup.send("❌ Produto não encontrado.", ephemeral=True)
    try:
        payment_data = {
            "transaction_amount": float(produto["preco"]),
            "description":        f"{produto['nome']} - Nexzy Store",
            "payment_method_id":  "pix",
            "payer": {
                "email":      f"nexzy_{interaction.user.id}@nexzystore.com.br",
                "first_name": (interaction.user.name or "Cliente")[:50],
                "identification": {"type": "CPF", "number": "00000000000"}
            },
            "statement_descriptor": "NEXZY STORE"
        }
        payment   = sdk.payment().create(payment_data)
        resp      = payment["response"]
        pedido_id = str(uuid.uuid4())

        await add_pedido(pedido_id, interaction.user.id, produto_id, produto["nome"], produto["preco"])

        pix    = resp["point_of_interaction"]["transaction_data"]["qr_code"]
        pay_id = resp["id"]
        pedidos_pendentes[pay_id] = pedido_id

        embed = Embed(
            title="💳  PAGAMENTO VIA PIX",
            description=f"**{produto['emoji']} {produto['nome']}**\n💰 **{formatar_preco(produto['preco'])}**",
            color=0x00b300
        )
        embed.add_field(name="🏢 Destinatário", value="**NEXZY STORE**", inline=True)
        embed.add_field(name="⏰ Validade",      value="**30 minutos**",  inline=True)
        embed.add_field(name="📋 Código PIX — Copia e Cola", value=f"```\n{pix[:300]}\n```", inline=False)
        embed.add_field(
            name="📱 Como Pagar",
            value="**1.** Copie o código\n**2.** Abra seu banco\n**3.** PIX → Copia e Cola\n**4.** Cole e confirme\n**5.** Clique em ✅ **JÁ PAGUEI**",
            inline=False
        )
        embed.set_footer(text="NEXZY STORE — Pagamento seguro via PIX")
        embed.timestamp = datetime.utcnow()

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="✅ JÁ PAGUEI", style=discord.ButtonStyle.success, custom_id=f"check_{pay_id}"))
        view.add_item(discord.ui.Button(label="❌ CANCELAR",  style=discord.ButtonStyle.danger,  custom_id=f"cancel_{pay_id}"))

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        asyncio.create_task(verificar_pagamento(pay_id, pedido_id, interaction.user, produto))

        await log_webhook("🕐 Pedido Iniciado", f"**{produto['nome']}** • {formatar_preco(produto['preco'])}", cor=0xf1c40f,
                          campos=[{"name": "👤 Usuário", "value": f"<@{interaction.user.id}>", "inline": True}])
    except Exception as e:
        print(f"Erro PIX: {e}")
        await interaction.followup.send(f"❌ Erro ao gerar PIX: {str(e)[:200]}", ephemeral=True)


async def verificar_pagamento(payment_id, pedido_id, user, produto):
    for _ in range(30):
        await asyncio.sleep(10)
        try:
            info = sdk.payment().get(payment_id)
            if info["response"].get("status") == "approved":
                await update_pedido(pedido_id, "aprovado")
                await add_venda(produto["preco"])
                await entregar_produto(user, dict(produto), pedido_id)
                await atualizar_vendas()
                return
        except Exception as e:
            print(f"Verificação: {e}")
    await update_pedido(pedido_id, "expirado")

# ================= EMBEDS =================
async def montar_embed_loja():
    produtos = await get_produtos()
    embed = Embed(
        title="🛒  N E X Z Y  S T O R E",
        description=(
            "╔══════════════════════════╗\n"
            "💎 **Compre via PIX e receba na hora!**\n"
            "🔐 Arquivo criptografado exclusivo por compra\n"
            "🔑 Key única gerada automaticamente\n"
            "╚══════════════════════════╝"
        ),
        color=0x00ff99
    )
    for p in produtos.values():
        desc    = p.get("descricao") or ""
        arquivo = "📂 Arquivo incluído" if p.get("arquivo_nome") else "🔑 Key de ativação"
        embed.add_field(
            name=f"{p['emoji']}  {p['nome']}",
            value=f"**{formatar_preco(p['preco'])}**\n{arquivo}" + (f"\n> {desc}" if desc else ""),
            inline=True
        )
    embed.set_footer(text="NEXZY STORE • Clique em 💰 COMPRAR")
    embed.timestamp = datetime.utcnow()
    return embed


async def montar_embed_vendas():
    total, qtd = await get_vendas()
    embed = Embed(title="📊  ESTATÍSTICAS — NEXZY STORE", color=0xf1c40f)
    embed.add_field(name="📦 Vendas",       value=f"**{qtd}** pedidos",                        inline=True)
    embed.add_field(name="💰 Faturamento",  value=f"**{formatar_preco(total)}**",               inline=True)
    embed.add_field(name="📈 Ticket Médio", value=formatar_preco(total/qtd) if qtd else "R$ 0,00", inline=True)
    embed.set_footer(text="NEXZY STORE")
    embed.timestamp = datetime.utcnow()
    return embed


async def atualizar_loja():
    canal = bot.get_channel(CANAL_LOJA)
    if canal:
        async for msg in canal.history(limit=10):
            if msg.author == bot.user:
                try: await msg.delete()
                except Exception: pass
        await canal.send(embed=await montar_embed_loja(), view=LojaButtons())


async def atualizar_vendas():
    canal = bot.get_channel(CANAL_VENDAS)
    if canal:
        async for msg in canal.history(limit=10):
            if msg.author == bot.user:
                try: await msg.delete()
                except Exception: pass
        await canal.send(embed=await montar_embed_vendas())

# ================= WEBHOOK MERCADO PAGO =================
async def webhook_mp(request):
    try:
        data   = await request.json()
        pay_id = data.get("data", {}).get("id") if data.get("type") == "payment" else None
        if pay_id and pay_id in pedidos_pendentes:
            info = sdk.payment().get(pay_id)
            if info["response"].get("status") == "approved":
                pedido_id = pedidos_pendentes[pay_id]
                async with db.acquire() as conn:
                    pedido = await conn.fetchrow("SELECT * FROM pedidos WHERE id=$1", pedido_id)
                    if pedido and pedido["status"] == "pendente":
                        user    = await bot.fetch_user(pedido["user_id"])
                        produtos= await get_produtos()
                        produto = produtos.get(pedido["produto_id"])
                        if produto:
                            await update_pedido(pedido_id, "aprovado")
                            await add_venda(produto["preco"])
                            await entregar_produto(user, dict(produto), pedido_id)
                            await atualizar_vendas()
    except Exception as e:
        print(f"Webhook MP: {e}")
    return web.Response(status=200)


async def start_server():
    app = web.Application()
    app.router.add_post("/webhook", webhook_mp)
    app.router.add_get("/health", lambda r: web.Response(text="OK — NEXZY STORE"))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "8080")))
    await site.start()
    print("✅ Servidor HTTP ativo")

# ================= COMANDOS =================
@bot.command(name="loja")
async def cmd_loja(ctx):
    await ctx.send(embed=await montar_embed_loja(), view=LojaButtons())
    try: await ctx.message.delete()
    except Exception: pass


@bot.command(name="vendas")
async def cmd_vendas(ctx):
    if not any(r.id == CARGO_DONO for r in ctx.author.roles):
        return
    await ctx.send(embed=await montar_embed_vendas())
    try: await ctx.message.delete()
    except Exception: pass


@bot.command(name="upload")
async def cmd_upload(ctx, produto_id: str = None):
    """
    !upload <produto_id>
    Envie este comando com o arquivo .rar/.zip/.7z ANEXADO na mesma mensagem.
    O arquivo é salvo no banco e entregue criptografado a cada compra.
    """
    if not any(r.id == CARGO_DONO for r in ctx.author.roles):
        return await ctx.reply("❌ Sem permissão.", delete_after=5)

    if not produto_id:
        return await ctx.reply(
            "❌ **Uso correto:**\n`!upload <produto_id>` com o arquivo anexado na mensagem.\n"
            "Exemplo: `!upload prod1` (e anexe o .rar)", delete_after=15
        )

    if not ctx.message.attachments:
        return await ctx.reply("❌ Nenhum arquivo anexado. Envie o comando **com** o arquivo.", delete_after=10)

    produtos = await get_produtos()
    if produto_id not in produtos:
        ids = ", ".join(f"`{pid}`" for pid in produtos)
        return await ctx.reply(f"❌ Produto `{produto_id}` não encontrado.\nIDs existentes: {ids}", delete_after=15)

    att     = ctx.message.attachments[0]
    size_mb = att.size / (1024 * 1024)

    if size_mb > 25:
        return await ctx.reply(
            f"❌ Arquivo muito grande: **{size_mb:.1f} MB**\n"
            f"Limite do Discord para bots: **25 MB**.", delete_after=15
        )

    msg = await ctx.reply(f"⏳ Salvando **{att.filename}** ({size_mb:.2f} MB) no banco...")
    try:
        dados = await att.read()
        await salvar_arquivo_produto(produto_id, att.filename, dados)
        await msg.edit(content=(
            f"✅ Arquivo **{att.filename}** ({size_mb:.2f} MB) salvo!\n"
            f"Produto: `{produto_id}` — **{produtos[produto_id]['nome']}**\n"
            f"Cada compra receberá o `.7z` criptografado com senha exclusiva."
        ))
        await atualizar_loja()
        await log_webhook("📂 Arquivo Vinculado", f"**{att.filename}** → produto `{produto_id}`", cor=0x9b59b6,
                          campos=[
                              {"name": "Admin",   "value": f"<@{ctx.author.id}>", "inline": True},
                              {"name": "Tamanho", "value": f"{size_mb:.2f} MB",   "inline": True}
                          ])
    except Exception as e:
        await msg.edit(content=f"❌ Erro ao salvar arquivo: {e}")


@bot.command(name="remover_arquivo")
async def cmd_remover_arquivo(ctx, produto_id: str = None):
    """Remove o arquivo vinculado a um produto"""
    if not any(r.id == CARGO_DONO for r in ctx.author.roles):
        return
    if not produto_id:
        return await ctx.reply("❌ Use: `!remover_arquivo <produto_id>`")
    await remover_arquivo_produto(produto_id)
    await ctx.reply(f"✅ Arquivo removido do produto `{produto_id}`.")
    await atualizar_loja()


@bot.command(name="check7z")
async def cmd_check7z(ctx):
    """Verifica se o 7-Zip está instalado no servidor"""
    if not any(r.id == CARGO_DONO for r in ctx.author.roles):
        return
    ok = verificar_7zip()
    if ok:
        result = subprocess.run(["7z", "i"], capture_output=True, text=True, timeout=5)
        versao = result.stdout.split("\n")[1] if result.stdout else "desconhecida"
        await ctx.reply(f"✅ **7-Zip instalado!**\n`{versao.strip()}`")
    else:
        await ctx.reply("❌ **7-Zip NÃO encontrado.**\nVerifique se o `Dockerfile` está correto e o deploy foi feito.")


@bot.command(name="produtos")
async def cmd_produtos(ctx):
    """Lista todos os produtos com seus IDs (apenas admin)"""
    if not any(r.id == CARGO_DONO for r in ctx.author.roles):
        return
    produtos = await get_produtos()
    if not produtos:
        return await ctx.reply("Nenhum produto cadastrado.")
    linhas = [f"{p['emoji']} `{pid}` — **{p['nome']}** — {formatar_preco(p['preco'])} {'📂' if p.get('arquivo_nome') else '🔑'}" for pid, p in produtos.items()]
    embed = Embed(title="📦 Produtos Cadastrados", description="\n".join(linhas), color=0x00ff99)
    embed.set_footer(text="📂 = tem arquivo  🔑 = só key")
    await ctx.reply(embed=embed)

# ================= EVENTOS =================
@bot.event
async def on_ready():
    print(f"✅ Bot online: {bot.user}")
    if not await init_db():
        return
    if not verificar_7zip():
        print("⚠️  7-Zip NÃO encontrado! Criptografia de arquivos desabilitada.")
    else:
        print("✅ 7-Zip disponível — criptografia ativa")
    asyncio.create_task(start_server())
    await atualizar_loja()
    await atualizar_vendas()
    await log_webhook("🟢 Bot Online", f"**NEXZY STORE** iniciou com sucesso!\nBot: `{bot.user}`", cor=0x2ecc71)
    print("✅ Pronto!")


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type != discord.InteractionType.component:
        return
    custom_id = interaction.data.get("custom_id", "")

    if custom_id.startswith("check_"):
        pay_id = int(custom_id.split("_")[1])
        await interaction.response.defer(ephemeral=True)
        try:
            info   = sdk.payment().get(pay_id)
            status = info["response"].get("status")
            msgs   = {
                "approved": "✅ **Pagamento aprovado!** Verifique sua DM — sua key e arquivo foram enviados.",
                "pending":  "⏳ Ainda **pendente**. Aguarde o banco processar e tente novamente.",
                "rejected": "❌ Pagamento **recusado**. Tente gerar um novo código."
            }
            await interaction.followup.send(msgs.get(status, f"ℹ️ Status: `{status}`"), ephemeral=True)
        except Exception:
            await interaction.followup.send("❌ Erro ao verificar. Tente novamente.", ephemeral=True)

    elif custom_id.startswith("cancel_"):
        await interaction.response.send_message("❌ Pedido cancelado. Você pode iniciar outro quando quiser.", ephemeral=True)

# ================= MAIN =================
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
