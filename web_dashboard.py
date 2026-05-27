from aiohttp import web
import database as db
import asyncio
import os
from payments import is_valid_webhook_signature
from mercadopago import SDK
from config import MP_TOKEN, MP_WEBHOOK_SECRET
import core

sdk = SDK(MP_TOKEN)

routes = web.RouteTableDef()

@routes.get('/health')
async def health(request):
    return web.Response(text="OK — NEXZY STORE")

@routes.get('/dashboard')
async def dashboard(request):
    vendas = await db.get_vendas_periodo(30)
    dias = {}
    for v in vendas:
        dia = v["criado_em"].strftime("%Y-%m-%d")
        dias[dia] = dias.get(dia, 0) + v["valor"]
    labels = list(dias.keys())
    valores = list(dias.values())
    html = f"""
    <html>
    <head><title>Nexzy Store - Dashboard</title><script src="https://cdn.jsdelivr.net/npm/chart.js"></script></head>
    <body>
    <h2>📊 Vendas dos últimos 30 dias</h2>
    <canvas id="vendasChart" width="800" height="400"></canvas>
    <script>
    const ctx = document.getElementById('vendasChart').getContext('2d');
    new Chart(ctx, {{
        type: 'line',
        data: {{
            labels: {labels},
            datasets: [{{
                label: 'Faturamento (R$)',
                data: {valores},
                borderColor: 'black',
                backgroundColor: 'rgba(0,0,0,0.1)',
                tension: 0.1
            }}]
        }}
    }});
    </script>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

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
                    guild = core._bot.get_guild(pedido['guild_id'])
                    user = await core._bot.fetch_user(pedido['user_id'])
                    produto = {'id': pedido['produto_id'], 'nome': pedido['produto_nome'], 'preco': pedido['produto_preco'], 'emoji': '🛒'}
                    await core.entregar_produto(user, produto, pedido_id, guild)
    return web.Response(status=200)

async def start_web_server():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Dashboard em http://0.0.0.0:{port}/dashboard")
