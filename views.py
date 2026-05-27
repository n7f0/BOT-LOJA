import discord
import uuid
import database as db
from utils import parse_emoji, formatar_preco, criar_embed
from payments import criar_pagamento_pix, gerar_embed_pix
from crypto import gerar_senha_segura

def gerar_id():
    import random, string
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))

class ProdutoModal(discord.ui.Modal, title="✨ Adicionar Produto"):
    nome_input = discord.ui.TextInput(label="📦 Nome", placeholder="Ex: VIP Premium", required=True)
    preco_input = discord.ui.TextInput(label="💰 Preço", placeholder="49.90", required=True)
    emoji_input = discord.ui.TextInput(label="😀 Emoji", placeholder="👑 ou <a:exemplo:ID>", required=False, default="🛒")
    descricao_input = discord.ui.TextInput(label="📝 Descrição", placeholder="Breve descrição", required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            pid = gerar_id()
            nome = self.nome_input.value
            preco = float(self.preco_input.value.replace(",", "."))
            emoji = self.emoji_input.value or "🛒"
            descricao = self.descricao_input.value or ""
            produtos = await db.get_produtos()
            while pid in produtos:
                pid = gerar_id()
            await db.add_produto(pid, nome, preco, emoji, descricao)
            embed = criar_embed(titulo="✅ Produto Adicionado!", cor=0x2d2d2d)
            embed.add_field(name="🆔 ID", value=f"`{pid}`", inline=True)
            embed.add_field(name="📦 Nome", value=nome, inline=True)
            embed.add_field(name="💰 Preço", value=formatar_preco(preco), inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
            from core import atualizar_loja
            await atualizar_loja(interaction.guild.id)
            from utils import log_admin
            await log_admin(interaction.client, "Produto Adicionado", interaction.user, f"**{nome}** • {formatar_preco(preco)} • ID `{pid}`", guild_id=interaction.guild.id)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro: {e}", ephemeral=True)

class EditarProdutoModal(discord.ui.Modal, title="✏️ Editar Produto"):
    def __init__(self, produto):
        super().__init__()
        self.produto_id = produto["id"]
        self.nome_input = discord.ui.TextInput(label="📦 Nome", default=produto["nome"], required=True)
        self.preco_input = discord.ui.TextInput(label="💰 Preço", default=str(produto["preco"]), required=True)
        self.emoji_input = discord.ui.TextInput(label="😀 Emoji", default=produto["emoji"], required=False)
        self.descricao_input = discord.ui.TextInput(label="📝 Descrição", default=produto.get("descricao",""), required=False)
        for item in [self.nome_input, self.preco_input, self.emoji_input, self.descricao_input]:
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            nome = self.nome_input.value
            preco = float(self.preco_input.value.replace(",", "."))
            emoji = self.emoji_input.value or "🛒"
            descricao = self.descricao_input.value or ""
            await db.edit_produto(self.produto_id, nome, preco, emoji, descricao)
            await interaction.followup.send("✅ Produto editado!", ephemeral=True)
            from core import atualizar_loja
            await atualizar_loja(interaction.guild.id)
            from utils import log_admin
            await log_admin(interaction.client, "Produto Editado", interaction.user, f"**{nome}** • {formatar_preco(preco)} • ID `{self.produto_id}`", guild_id=interaction.guild.id)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro: {e}", ephemeral=True)

class RemoverSelect(discord.ui.Select):
    def __init__(self, produtos):
        options = []
        for pid, p in produtos.items():
            emoji = parse_emoji(p['emoji'])
            options.append(discord.SelectOption(label=f"{p['nome']} ({pid})", value=pid, emoji=emoji))
        super().__init__(placeholder="🗑️ Selecione o produto para remover", options=options[:25])
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        produtos = await db.get_produtos()
        produto = produtos.get(self.values[0])
        nome = produto["nome"] if produto else self.values[0]
        await db.remove_produto(self.values[0])
        await interaction.followup.send(f"✅ **{nome}** removido!", ephemeral=True)
        from core import atualizar_loja
        await atualizar_loja(interaction.guild.id)
        from utils import log_admin
        await log_admin(interaction.client, "Produto Removido", interaction.user, f"**{nome}** • ID `{self.values[0]}`", cor=0x8b0000, guild_id=interaction.guild.id)

class EditarSelect(discord.ui.Select):
    def __init__(self, produtos):
        options = []
        for pid, p in produtos.items():
            emoji = parse_emoji(p['emoji'])
            options.append(discord.SelectOption(label=f"{p['nome']} — {formatar_preco(p['preco'])}", value=pid, emoji=emoji))
        super().__init__(placeholder="✏️ Selecione o produto para editar", options=options[:25])
    async def callback(self, interaction: discord.Interaction):
        produtos = await db.get_produtos()
        produto = produtos.get(self.values[0])
        if not produto:
            return await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
        await interaction.response.send_modal(EditarProdutoModal(produto))

class CPFModal(discord.ui.Modal, title="🔐 Validação de CPF"):
    cpf_input = discord.ui.TextInput(label="CPF (apenas números)", placeholder="00000000000", required=True, max_length=11, min_length=11)
    def __init__(self, produto_id: str, produto: dict):
        super().__init__()
        self.produto_id = produto_id
        self.produto = produto
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cpf = self.cpf_input.value
        if not cpf.isdigit() or len(cpf) != 11:
            await interaction.followup.send("❌ CPF inválido. Envie 11 números.", ephemeral=True)
            return
        try:
            payment_resp = await criar_pagamento_pix(self.produto, interaction.user.id, interaction.user.name, cpf)
            payment_id = payment_resp["id"]
            pedido_id = str(uuid.uuid4())
            await db.add_pedido(pedido_id, interaction.user.id, self.produto_id, self.produto["nome"], self.produto["preco"], interaction.guild.id)
            await db.salvar_pagamento(payment_id, pedido_id)
            embed, qr_file = await gerar_embed_pix(self.produto, payment_resp, pedido_id)
            view = discord.ui.View(timeout=300)
            check_button = CheckPaymentButton(payment_id, pedido_id, self.produto, interaction.user, interaction.guild.id)
            view.add_item(check_button)
            view.add_item(discord.ui.Button(label="❌ CANCELAR", style=discord.ButtonStyle.danger, custom_id=f"cancel_{payment_id}"))
            if qr_file:
                await interaction.followup.send(embed=embed, file=qr_file, view=view, ephemeral=True)
            else:
                await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao gerar PIX: {e}", ephemeral=True)

class CheckPaymentButton(discord.ui.Button):
    def __init__(self, payment_id: int, pedido_id: str, produto: dict, user: discord.User, guild_id: int):
        super().__init__(label="✅ JÁ PAGUEI", style=discord.ButtonStyle.success, custom_id=f"check_{payment_id}")
        self.payment_id = payment_id
        self.pedido_id = pedido_id
        self.produto = produto
        self.user = user
        self.guild_id = guild_id
    async def callback(self, interaction: discord.Interaction):
        self.disabled = True
        await interaction.response.edit_message(view=self.view)
        await interaction.followup.send("⏳ Aguardando confirmação do banco...", ephemeral=True)
        from mercadopago import SDK
        from config import MP_TOKEN
        sdk = SDK(MP_TOKEN)
        try:
            info = sdk.payment().get(self.payment_id)
            status = info["response"].get("status")
            if status == "approved":
                await db.update_pedido(self.pedido_id, "aprovado")
                await db.add_venda(self.produto["preco"])
                from core import entregar_produto
                guild = interaction.client.get_guild(self.guild_id)
                if guild:
                    await entregar_produto(self.user, self.produto, self.pedido_id, guild)
                await interaction.followup.send("✅ Pagamento aprovado! Canal de entrega criado.", ephemeral=True)
            elif status == "pending":
                await interaction.followup.send("⏳ Pagamento ainda pendente. Aguarde alguns minutos.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Status: {status}. Se já pagou, aguarde a confirmação automática.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao verificar: {e}", ephemeral=True)

class ProdutoSelect(discord.ui.Select):
    def __init__(self, produtos):
        options = []
        for pid, p in produtos.items():
            emoji = parse_emoji(p['emoji'])
            options.append(discord.SelectOption(label=f"{p['nome']} — {formatar_preco(p['preco'])}", value=pid, emoji=emoji))
        super().__init__(placeholder="🛒 Escolha um produto", options=options[:25])
    async def callback(self, interaction: discord.Interaction):
        produto_id = self.values[0]
        produtos = await db.get_produtos()
        produto = produtos.get(produto_id)
        if not produto:
            return await interaction.response.send_message("❌ Produto não encontrado.", ephemeral=True)
        await interaction.response.send_modal(CPFModal(produto_id, produto))

class LojaButtons(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="💰 Comprar", style=discord.ButtonStyle.success, emoji="🛒")
    async def comprar(self, interaction: discord.Interaction, button: discord.ui.Button):
        produtos = await db.get_produtos()
        if not produtos:
            return await interaction.response.send_message("❌ Nenhum produto disponível.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(ProdutoSelect(produtos))
        await interaction.response.send_message("📦 **Selecione o produto:**", view=view, ephemeral=True)
    @discord.ui.button(label="👑 Admin", style=discord.ButtonStyle.danger, emoji="⚙️")
    async def admin(self, interaction: discord.Interaction, button: discord.ui.Button):
        from database import get_guild_config
        cfg = await get_guild_config(interaction.guild.id)
        if not any(r.id == cfg["cargo_dono"] for r in interaction.user.roles):
            return await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        embed = criar_embed(titulo="⚙️ Painel Admin", cor=0x8b0000)
        embed.add_field(name="➕ Adicionar", value="Cadastra produto", inline=True)
        embed.add_field(name="✏️ Editar", value="Altera produto", inline=True)
        embed.add_field(name="🗑️ Remover", value="Remove produto", inline=True)
        embed.add_field(name="📂 Ver Arquivos", value="Arquivos no banco", inline=True)
        embed.add_field(name="🧹 Limpar Banco", value="Limpa tudo", inline=True)
        embed.add_field(name="🧪 Teste de Entrega", value="Envia teste_nexzy.txt", inline=True)
        embed.add_field(name="📊 Estatísticas", value="Faturamento", inline=True)
        embed.add_field(name="🎟️ Cupons", value="Gerenciar cupons", inline=True)
        await interaction.response.send_message(embed=embed, view=AdminView(), ephemeral=True)

class AdminView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
    @discord.ui.button(label="➕ Adicionar", style=discord.ButtonStyle.success)
    async def add(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProdutoModal())
    @discord.ui.button(label="✏️ Editar", style=discord.ButtonStyle.primary)
    async def editar(self, interaction: discord.Interaction, button: discord.ui.Button):
        produtos = await db.get_produtos()
        if not produtos:
            return await interaction.response.send_message("❌ Nenhum produto.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(EditarSelect(produtos))
        await interaction.response.send_message("✏️ Selecione o produto:", view=view, ephemeral=True)
    @discord.ui.button(label="🗑️ Remover", style=discord.ButtonStyle.danger)
    async def remover(self, interaction: discord.Interaction, button: discord.ui.Button):
        produtos = await db.get_produtos()
        if not produtos:
            return await interaction.response.send_message("❌ Nenhum produto.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(RemoverSelect(produtos))
        await interaction.response.send_message("🗑️ Selecione o produto:", view=view, ephemeral=True)
    @discord.ui.button(label="📂 Ver Arquivos", style=discord.ButtonStyle.secondary)
    async def ver_arquivos(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        async with db.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, nome, arquivo_nome, LENGTH(arquivo_data) as tamanho_bytes FROM produtos WHERE arquivo_data IS NOT NULL")
        if not rows:
            embed = criar_embed(titulo="📂 Arquivos", descricao="*Nenhum.*", cor=0x4a4a4a)
            return await interaction.followup.send(embed=embed, ephemeral=True)
        embed = criar_embed(titulo="📂 Arquivos no Banco", descricao=f"{len(rows)} arquivo(s):", cor=0x4a4a4a)
        total = 0
        for row in rows:
            mb = row["tamanho_bytes"]/1024/1024
            total += row["tamanho_bytes"]
            embed.add_field(name=f"📦 {row['nome']} (`{row['id']}`)", value=f"📄 `{row['arquivo_nome']}`\n📏 {mb:.2f} MB", inline=False)
        embed.add_field(name="📊 Total", value=f"**{len(rows)}** arquivos • **{total/1024/1024:.2f} MB**", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
    @discord.ui.button(label="🧹 Limpar Banco", style=discord.ButtonStyle.danger)
    async def limpar_banco(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = criar_embed(titulo="⚠️ CONFIRMAÇÃO", descricao="**IRREVERSÍVEL!** Apagará tudo.", cor=0x8b0000)
        view = ConfirmacaoLimpezaView(interaction)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
    @discord.ui.button(label="🧪 Teste de Entrega", style=discord.ButtonStyle.secondary)
    async def teste(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from core import entregar_produto
        conteudo = b"Arquivo de teste da Nexzy Store.\nKey de uso unico - Canal expira em 5 minutos."
        produto_teste = {"id":"teste","nome":"Produto de Teste","preco":0.0,"emoji":"🧪"}
        pedido_id = f"TESTE-{uuid.uuid4().hex[:8]}"
        await interaction.followup.send("⏳ Criando canal de teste (5 min)...", ephemeral=True)
        await entregar_produto(interaction.user, produto_teste, pedido_id, interaction.guild, dados_arquivo_override=conteudo, nome_arquivo_override="teste_nexzy.txt")
        await interaction.edit_original_response(content="✅ Canal de teste criado! Expira em 5 minutos.")
    @discord.ui.button(label="📊 Estatísticas", style=discord.ButtonStyle.secondary)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        from core import montar_embed_vendas
        await interaction.followup.send(embed=await montar_embed_vendas(interaction.guild.id), ephemeral=True)
    @discord.ui.button(label="🎟️ Cupons", style=discord.ButtonStyle.secondary)
    async def cupons(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Use `!criar_cupom` para criar cupons.", ephemeral=True)

class ConfirmacaoLimpezaView(discord.ui.View):
    def __init__(self, interaction_original):
        super().__init__(timeout=60)
        self.interaction_original = interaction_original
    async def on_timeout(self):
        try:
            await self.interaction_original.edit_original_response(content="⏰ Tempo expirado.", embed=None, view=None)
        except:
            pass
    @discord.ui.button(label="✅ CONFIRMAR LIMPEZA", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirmar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_original.user.id:
            return await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await db.limpar_banco_completo()
        from core import atualizar_loja, atualizar_vendas
        await atualizar_loja(interaction.guild.id)
        await atualizar_vendas(interaction.guild.id)
        from utils import log_admin
        await log_admin(interaction.client, "🗑️ Banco Limpo", interaction.user, "Todos os dados foram zerados.", cor=0x8b0000, guild_id=interaction.guild.id)
        embed = criar_embed(titulo="✅ Banco de Dados Limpo", descricao="Tudo foi removido.", cor=0x2d2d2d)
        await self.interaction_original.edit_original_response(embed=embed, view=None)
        await interaction.followup.send("✅ Limpo!", ephemeral=True)
    @discord.ui.button(label="❌ CANCELAR", style=discord.ButtonStyle.secondary)
    async def cancelar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.interaction_original.user.id:
            return await interaction.response.send_message("❌ Sem permissão.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        embed = criar_embed(titulo="❌ Cancelado", descricao="Banco intacto.", cor=0x4a4a4a)
        await self.interaction_original.edit_original_response(embed=embed, view=None)
        await interaction.followup.send("✅ Cancelado.", ephemeral=True)
