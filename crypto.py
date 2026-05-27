import secrets
import shutil
import subprocess
import tempfile
import asyncio
import os
import concurrent.futures
from typing import Tuple

def gerar_senha_segura() -> str:
    return secrets.token_urlsafe(32)

def verificar_7zip() -> bool:
    return shutil.which("7z") is not None

def instalar_7zip() -> bool:
    try:
        subprocess.run(["apt-get", "update"], capture_output=True, timeout=60)
        result = subprocess.run(["apt-get", "install", "-y", "p7zip-full"], capture_output=True, timeout=120)
        return result.returncode == 0
    except Exception:
        return False

def _criar_7z_sync(dados: bytes, nome_original: str, senha: str) -> bytes:
    tmp = tempfile.mkdtemp(prefix="nexzy_")
    try:
        caminho_original = os.path.join(tmp, nome_original)
        with open(caminho_original, "wb") as f:
            f.write(dados)
        caminho_saida = os.path.join(tmp, "entrega.7z")
        subprocess.run(
            ["7z", "a", f"-p{senha}", "-mhe=on", "-mx=0", caminho_saida, caminho_original],
            check=True, capture_output=True, timeout=120
        )
        with open(caminho_saida, "rb") as f:
            return f.read()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

async def criar_7z_criptografado(dados: bytes, nome_original: str, senha: str) -> bytes:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _criar_7z_sync, dados, nome_original, senha)

def validar_arquivo_seguro(dados: bytes, nome: str) -> Tuple[bool, str]:
    extensoes_permitidas = ('.txt', '.pdf', '.png', '.jpg', '.jpeg', '.zip', '.rar', '.7z', '.mp4')
    if not any(nome.lower().endswith(ext) for ext in extensoes_permitidas):
        return False, f"Extensão não permitida. Use: {', '.join(extensoes_permitidas)}"
    if nome.lower().endswith('.pdf') and not dados.startswith(b'%PDF'):
        return False, "Arquivo PDF inválido"
    if nome.lower().endswith('.zip') and not dados.startswith(b'PK'):
        return False, "Arquivo ZIP inválido"
    return True, ""
