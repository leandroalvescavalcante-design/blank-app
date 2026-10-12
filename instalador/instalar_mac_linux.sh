#!/usr/bin/env bash
# Instalador da Ferramenta de Gestão Industrial (Mac e Linux).
# Uso: abra o Terminal na pasta da ferramenta e rode:  bash instalador/instalar_mac_linux.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo
echo " Ferramenta de Gestão Industrial — instalação"
echo

PY=""
for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PY="$c"; break
    fi
done
if [ -z "$PY" ]; then
    echo " [1/3] Python 3.11 ou mais novo não encontrado."
    echo "       Mac:   instale em https://www.python.org/downloads/ (ou: brew install python@3.12)"
    echo "       Linux: sudo apt install python3.12 python3.12-venv   (Debian/Ubuntu)"
    echo "       Depois rode este instalador de novo."
    exit 1
fi
echo " [1/3] Python $("$PY" -c 'import platform; print(platform.python_version())') encontrado."

if [ ! -x .venv/bin/python ]; then
    echo " [2/3] Criando o ambiente da ferramenta..."
    "$PY" -m venv .venv
else
    echo " [2/3] Ambiente da ferramenta já existe."
fi

echo " [3/3] Instalando as bibliotecas (precisa de internet; pode levar alguns minutos)..."
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet

# evita a pergunta de e-mail do Streamlit na primeira abertura
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    mkdir -p "$HOME/.streamlit"
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi
chmod +x instalador/iniciar_mac_linux.sh

echo
read -r -p " Carregar o cenário de TREINAMENTO (dados fictícios) agora? [s/N] " resp || resp=""
if [ "${resp:-N}" = "s" ] || [ "${resp:-N}" = "S" ]; then
    echo " Carregando o cenário fictício (cerca de 1 minuto)..."
    .venv/bin/python -m app.admin carregar-simulacao --usuario instalador || echo " O cenário não carregou. A ferramenta funciona mesmo assim."
fi

echo
echo " Instalação concluída. Para abrir:  bash instalador/iniciar_mac_linux.sh"
