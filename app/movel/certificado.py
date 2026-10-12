"""Certificados HTTPS da rede local.

O Chrome do Android só libera modo offline (service worker), instalação como app e câmera em
conexão segura. Na rede da planta não há domínio público, então a ferramenta cria:
- uma autoridade certificadora própria (CA, 10 anos), instalada UMA vez em cada celular;
- um certificado do servidor assinado por ela, com os IPs e o nome do computador.
Se o IP do computador mudar, gere de novo só o do servidor; os celulares continuam confiando na CA.
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import socket

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from app.movel import caminhos


def ips_locais() -> list[str]:
    ips = {"127.0.0.1"}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # não envia nada: só descobre a interface de saída
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ips)


def _salvar_chave(chave, caminho):
    caminho.write_bytes(chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))


def garantir_ca():
    d = caminhos.tls()
    if (d / "ca.crt").exists() and (d / "ca.key").exists():
        return (x509.load_pem_x509_certificate((d / "ca.crt").read_bytes()),
                serialization.load_pem_private_key((d / "ca.key").read_bytes(), None))
    chave = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Gestao Industrial - CA local"),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Ferramenta de Gestao Industrial")])
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(chave.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(agora - dt.timedelta(days=1))
            .not_valid_after(agora + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(chave, hashes.SHA256()))
    _salvar_chave(chave, d / "ca.key")
    (d / "ca.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert, chave


def gerar_servidor(ips: list[str] | None = None) -> list[str]:
    """(Re)gera o certificado do servidor para os IPs dados (padrão: os deste computador)."""
    ca_cert, ca_chave = garantir_ca()
    ips = ips or ips_locais()
    host = socket.gethostname()
    chave = ec.generate_private_key(ec.SECP256R1())
    agora = dt.datetime.now(dt.timezone.utc)
    nomes = [x509.DNSName("localhost"), x509.DNSName(host)] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)]))
            .issuer_name(ca_cert.subject).public_key(chave.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(agora - dt.timedelta(days=1))
            .not_valid_after(agora + dt.timedelta(days=825))   # limite aceito pelos navegadores
            .add_extension(x509.SubjectAlternativeName(nomes), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(ca_chave, hashes.SHA256()))
    d = caminhos.tls()
    _salvar_chave(chave, d / "servidor.key")
    (d / "servidor.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "servidor.ips").write_text("\n".join(ips), encoding="utf-8")
    return ips


def garantir_servidor() -> list[str]:
    """Gera o certificado do servidor se faltar ou se os IPs do computador mudaram."""
    d = caminhos.tls()
    atuais = ips_locais()
    if (d / "servidor.crt").exists() and (d / "servidor.ips").exists():
        gravados = (d / "servidor.ips").read_text(encoding="utf-8").split()
        if set(atuais) <= set(gravados):
            return gravados
    return gerar_servidor(atuais)
