#!/usr/bin/env bash
# Abre a Ferramenta de Gestão Industrial no navegador (http://localhost:8501).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ]; then
    echo "A ferramenta ainda não foi instalada. Rode: bash instalador/instalar_mac_linux.sh"
    exit 1
fi
# servidor do app do celular (Wi-Fi da empresa); encerra junto com a ferramenta
.venv/bin/python -m app.movel.servidor &
CELULAR=$!
trap 'kill $CELULAR 2>/dev/null || true' EXIT
echo "Abrindo a ferramenta no navegador. Para encerrar, aperte Ctrl+C neste Terminal."
.venv/bin/python -m streamlit run streamlit_app.py --server.headless false
