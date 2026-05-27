# patch.py – igual ao original, apenas para compatibilidade
import sys
from types import ModuleType

class AudioopModule(ModuleType):
    def __getattr__(self, name):
        return lambda *args: bytes(0) if 'lin' in name else 0
sys.modules['audioop'] = AudioopModule()
