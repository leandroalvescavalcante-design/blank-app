"""Pastas da versão celular, ao lado do banco (respeita GESTAO_DB, então testes ficam isolados)."""
from pathlib import Path

from app.config import caminho_banco

WEB = Path(__file__).resolve().parent / "web"


def raiz() -> Path:
    p = caminho_banco().parent / "movel"
    p.mkdir(parents=True, exist_ok=True)
    return p


def fila() -> Path:
    p = raiz() / "fila"
    p.mkdir(exist_ok=True)
    return p


def resultados() -> Path:
    p = raiz() / "resultados"
    p.mkdir(exist_ok=True)
    return p


def tls() -> Path:
    p = raiz() / "tls"
    p.mkdir(exist_ok=True)
    return p


def referencias() -> Path:
    return raiz() / "referencias.json"


def acessos() -> Path:
    return raiz() / "acessos.json"


def segredo() -> Path:
    return raiz() / "segredo.key"
