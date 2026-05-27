from aiohttp import web
import database as db
import asyncio
import os

routes = web.RouteTableDef()

@routes.get('/health')
async def health(request):
    return web.Response(text="OK — NEXZY STORE")

@routes.get('/dashboard')
async def dashboard(request):
    # Gráfico simples com Chart.js
    vendas = await db.get_vendas_periodo(30)
    # Agrupa por dia
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

async def start_web_server():
    app = web.Application()
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"✅ Dashboard em http://0.0.0.0:{port}/dashboard")
