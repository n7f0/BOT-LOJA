import asyncpg
from config import DATABASE_URL

db_pool = None

async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    async with db_pool.acquire() as conn:
        # Tabela produtos
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
        
        # Tabela pedidos (com guild_id)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id            TEXT PRIMARY KEY,
                user_id       BIGINT NOT NULL,
                produto_id    TEXT NOT NULL,
                produto_nome  TEXT NOT NULL,
                produto_preco REAL NOT NULL,
                guild_id      BIGINT,
                status        TEXT DEFAULT 'pendente',
                criado_em     TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Verifica se a coluna guild_id existe; se não, adiciona (para tabelas antigas)
        await conn.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='pedidos' AND column_name='guild_id') THEN
                    ALTER TABLE pedidos ADD COLUMN guild_id BIGINT;
                END IF;
            END
            $$;
        """)
        
        # Tabela vendas (resumo)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vendas (
                id         SERIAL PRIMARY KEY,
                total      REAL DEFAULT 0,
                quantidade INTEGER DEFAULT 0
            )
        """)
        await conn.execute("INSERT INTO vendas (id,total,quantidade) VALUES (1,0,0) ON CONFLICT (id) DO NOTHING")
        
        # Tabela vendas_realizadas (detalhe)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS vendas_realizadas (
                id           SERIAL PRIMARY KEY,
                pedido_id    TEXT NOT NULL,
                user_id      BIGINT NOT NULL,
                produto_nome TEXT NOT NULL,
                valor        REAL NOT NULL,
                criado_em    TIMESTAMP DEFAULT NOW()
            )
        """)
        
        # Tabela pagamentos
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pagamentos (
                payment_id   BIGINT PRIMARY KEY,
                pedido_id    TEXT NOT NULL,
                status       TEXT DEFAULT 'pendente'
            )
        """)
        
        # Tabela cupons
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cupons (
                codigo      TEXT PRIMARY KEY,
                tipo        TEXT CHECK (tipo IN ('percentual','fixo')),
                valor       REAL NOT NULL,
                validade    TIMESTAMP,
                usos_maximo INTEGER DEFAULT 1,
                usos_atual  INTEGER DEFAULT 0
            )
        """)
        
        # Tabela guild_config
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id     BIGINT PRIMARY KEY,
                cargo_dono   BIGINT,
                canal_loja   BIGINT,
                canal_vendas BIGINT,
                canal_log_vendas BIGINT,
                canal_log_admin BIGINT
            )
        """)
        
        # Configuração padrão (fallback)
        from config import DEFAULT_CARGO_DONO, DEFAULT_CANAL_LOJA, DEFAULT_CANAL_VENDAS, DEFAULT_CANAL_LOG_VENDAS, DEFAULT_CANAL_LOG_ADMIN
        if DEFAULT_CARGO_DONO:
            await conn.execute("""
                INSERT INTO guild_config (guild_id, cargo_dono, canal_loja, canal_vendas, canal_log_vendas, canal_log_admin)
                VALUES (0, $1, $2, $3, $4, $5)
                ON CONFLICT (guild_id) DO NOTHING
            """, DEFAULT_CARGO_DONO, DEFAULT_CANAL_LOJA, DEFAULT_CANAL_VENDAS, DEFAULT_CANAL_LOG_VENDAS, DEFAULT_CANAL_LOG_ADMIN)
    return True

# ---- PRODUTOS ----
async def get_produtos(guild_id: int = None):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, nome, preco, emoji, descricao, arquivo_nome FROM produtos")
        return {r["id"]: dict(r) for r in rows}

async def get_produto_completo(pid: str):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM produtos WHERE id=$1", pid)

async def add_produto(pid, nome, preco, emoji, descricao=""):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO produtos (id,nome,preco,emoji,descricao) VALUES ($1,$2,$3,$4,$5)", pid, nome, preco, emoji, descricao)

async def edit_produto(pid, nome, preco, emoji, descricao):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE produtos SET nome=$2, preco=$3, emoji=$4, descricao=$5 WHERE id=$1", pid, nome, preco, emoji, descricao)

async def salvar_arquivo_produto(pid, nome_arquivo, dados: bytes):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE produtos SET arquivo_nome=$2, arquivo_data=$3 WHERE id=$1", pid, nome_arquivo, dados)

async def remover_arquivo_produto(pid):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE produtos SET arquivo_nome=NULL, arquivo_data=NULL WHERE id=$1", pid)

async def remove_produto(pid):
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM produtos WHERE id=$1", pid)

# ---- PEDIDOS ----
async def add_pedido(pid, user_id, produto_id, nome, preco, guild_id):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO pedidos (id, user_id, produto_id, produto_nome, produto_preco, guild_id) VALUES ($1,$2,$3,$4,$5,$6)", pid, user_id, produto_id, nome, preco, guild_id)

async def update_pedido(pid, status):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE pedidos SET status=$1 WHERE id=$2", status, pid)

async def get_pedido(pid: str):
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM pedidos WHERE id=$1", pid)

# ---- PAGAMENTOS ----
async def salvar_pagamento(payment_id: int, pedido_id: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO pagamentos (payment_id, pedido_id) VALUES ($1,$2) ON CONFLICT (payment_id) DO UPDATE SET pedido_id=$2", payment_id, pedido_id)

async def atualizar_status_pagamento(payment_id: int, status: str):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE pagamentos SET status=$1 WHERE payment_id=$2", status, payment_id)

async def obter_pedido_por_payment(payment_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT pedido_id FROM pagamentos WHERE payment_id=$1", payment_id)
        return row["pedido_id"] if row else None

# ---- VENDAS ----
async def get_vendas():
    async with db_pool.acquire() as conn:
        r = await conn.fetchrow("SELECT total, quantidade FROM vendas WHERE id=1")
        return r["total"], r["quantidade"]

async def add_venda(valor):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE vendas SET total=total+$1, quantidade=quantidade+1 WHERE id=1", valor)

async def registrar_venda_realizada(pedido_id, user_id, produto_nome, valor):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO vendas_realizadas (pedido_id, user_id, produto_nome, valor) VALUES ($1,$2,$3,$4)", pedido_id, user_id, produto_nome, valor)

async def get_vendas_periodo(dias: int = 30):
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT criado_em, valor FROM vendas_realizadas WHERE criado_em > NOW() - $1 * INTERVAL '1 day'",
            dias
        )
        return rows

# ---- CUPONS ----
async def validar_cupom(codigo: str):
    async with db_pool.acquire() as conn:
        cupom = await conn.fetchrow("SELECT * FROM cupons WHERE codigo=$1 AND (validade IS NULL OR validade > NOW()) AND usos_atual < usos_maximo", codigo)
        return dict(cupom) if cupom else None

async def aplicar_cupom(codigo: str):
    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE cupons SET usos_atual = usos_atual + 1 WHERE codigo=$1", codigo)

async def criar_cupom(codigo, tipo, valor, validade=None, usos_maximo=1):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT INTO cupons (codigo, tipo, valor, validade, usos_maximo) VALUES ($1,$2,$3,$4,$5)", codigo, tipo, valor, validade, usos_maximo)

# ---- CONFIGURAÇÕES GUILD ----
async def get_guild_config(guild_id: int):
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM guild_config WHERE guild_id=$1", guild_id)
        if not row:
            from config import DEFAULT_CARGO_DONO, DEFAULT_CANAL_LOJA, DEFAULT_CANAL_VENDAS, DEFAULT_CANAL_LOG_VENDAS, DEFAULT_CANAL_LOG_ADMIN
            return {
                "cargo_dono": DEFAULT_CARGO_DONO,
                "canal_loja": DEFAULT_CANAL_LOJA,
                "canal_vendas": DEFAULT_CANAL_VENDAS,
                "canal_log_vendas": DEFAULT_CANAL_LOG_VENDAS,
                "canal_log_admin": DEFAULT_CANAL_LOG_ADMIN
            }
        return dict(row)

async def set_guild_config(guild_id: int, **kwargs):
    async with db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO guild_config (guild_id, cargo_dono, canal_loja, canal_vendas, canal_log_vendas, canal_log_admin)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (guild_id) DO UPDATE SET
                cargo_dono = EXCLUDED.cargo_dono,
                canal_loja = EXCLUDED.canal_loja,
                canal_vendas = EXCLUDED.canal_vendas,
                canal_log_vendas = EXCLUDED.canal_log_vendas,
                canal_log_admin = EXCLUDED.canal_log_admin
        """, guild_id, kwargs.get("cargo_dono"), kwargs.get("canal_loja"), kwargs.get("canal_vendas"), kwargs.get("canal_log_vendas"), kwargs.get("canal_log_admin"))

# ---- LIMPEZA ----
async def limpar_banco_completo():
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM vendas_realizadas")
        await conn.execute("DELETE FROM pedidos")
        await conn.execute("DELETE FROM produtos")
        await conn.execute("DELETE FROM pagamentos")
        await conn.execute("DELETE FROM cupons")
        await conn.execute("UPDATE vendas SET total=0, quantidade=0 WHERE id=1")
