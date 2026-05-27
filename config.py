import os

DISCORD_TOKEN = os.getenv("LOJA_DISCORD_TOKEN")
MP_TOKEN = os.getenv("MERCADO_PAGO_TOKEN")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "change_this_secret_in_production")
DATABASE_URL = os.getenv("DATABASE_URL")

DEFAULT_CARGO_DONO = int(os.getenv("CARGO_DONO", "0"))
DEFAULT_CANAL_LOJA = int(os.getenv("CANAL_LOJA", "0"))
DEFAULT_CANAL_VENDAS = int(os.getenv("CANAL_VENDAS", "0"))
DEFAULT_CANAL_LOG_VENDAS = int(os.getenv("CANAL_LOG_VENDAS", "0"))
DEFAULT_CANAL_LOG_ADMIN = int(os.getenv("CANAL_LOG_ADMIN", "0"))

COR_PRINCIPAL = 0x1a1a1a
COR_SUCESSO   = 0x2d2d2d
COR_ERRO      = 0x8b0000
COR_PENDENTE  = 0x3d3d3d
COR_DESTAQUE  = 0x4a4a4a

if not DISCORD_TOKEN or not MP_TOKEN or not DATABASE_URL:
    raise RuntimeError("❌ Faltam variáveis de ambiente")

if "railwaypostgresql://" in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace("railwaypostgresql://", "postgresql://")
