"""Acesso ao app do celular: matrícula + PIN.

- PIN guardado só como hash scrypt com sal (nunca em texto), em dados/movel/acessos.json.
- Sessão = token assinado (HMAC-SHA256) com validade de 7 dias, para permitir uso offline;
  o servidor confere a assinatura a cada envio.
- 5 tentativas erradas bloqueiam a matrícula por 5 minutos.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from app.movel import caminhos

VALIDADE_S = 7 * 24 * 3600
MAX_FALHAS, BLOQUEIO_S = 5, 300
_falhas: dict[str, list[float]] = {}


def _hash(pin: str, sal: bytes) -> str:
    return hashlib.scrypt(pin.encode(), salt=sal, n=2 ** 14, r=8, p=1).hex()


def _ler() -> dict:
    p = caminhos.acessos()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def definir_pin(matricula: str, pin: str) -> None:
    matricula = matricula.strip()
    if not matricula:
        raise ValueError("matrícula vazia")
    if not (pin.isdigit() and 4 <= len(pin) <= 8):
        raise ValueError("PIN deve ter de 4 a 8 dígitos")
    if len(set(pin)) == 1 or pin in "0123456789" or pin in "9876543210":
        raise ValueError("PIN fraco (repetido ou sequência)")
    dados = _ler()
    sal = secrets.token_bytes(16)
    dados[matricula] = {"sal": sal.hex(), "hash": _hash(pin, sal), "criado": int(time.time())}
    tmp = caminhos.acessos().with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, indent=1), encoding="utf-8")
    os.replace(tmp, caminhos.acessos())


def remover(matricula: str) -> bool:
    dados = _ler()
    if dados.pop(matricula, None) is None:
        return False
    caminhos.acessos().write_text(json.dumps(dados, indent=1), encoding="utf-8")
    return True


def _segredo() -> bytes:
    p = caminhos.segredo()
    if not p.exists():
        p.write_bytes(secrets.token_bytes(32))
    return p.read_bytes()


def bloqueada(matricula: str, agora: float | None = None) -> bool:
    agora = agora or time.time()
    recentes = [t for t in _falhas.get(matricula, []) if agora - t < BLOQUEIO_S]
    _falhas[matricula] = recentes
    return len(recentes) >= MAX_FALHAS


def entrar(matricula: str, pin: str) -> str | None:
    """Token de sessão, ou None se matrícula/PIN errados ou bloqueada."""
    matricula = (matricula or "").strip()
    if bloqueada(matricula):
        return None
    reg = _ler().get(matricula)
    ok = reg is not None and hmac.compare_digest(_hash(pin or "", bytes.fromhex(reg["sal"])), reg["hash"])
    if not ok:
        _falhas.setdefault(matricula, []).append(time.time())
        return None
    _falhas.pop(matricula, None)
    return emitir_token(matricula)


def emitir_token(matricula: str, validade_s: int = VALIDADE_S) -> str:
    corpo = base64.urlsafe_b64encode(json.dumps({"m": matricula, "exp": int(time.time()) + validade_s}).encode()).decode()
    sig = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    return f"{corpo}.{sig}"


def validar_token(token: str | None) -> str | None:
    """Matrícula do token, ou None se inválido, adulterado, expirado ou com acesso revogado."""
    if not token or token.count(".") != 1:
        return None
    corpo, sig = token.split(".")
    esperado = hmac.new(_segredo(), corpo.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, esperado):
        return None
    try:
        dados = json.loads(base64.urlsafe_b64decode(corpo.encode()))
    except ValueError:
        return None
    if dados.get("exp", 0) < time.time() or dados.get("m") not in _ler():
        return None
    return dados["m"]
