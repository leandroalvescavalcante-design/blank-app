"""Ponto de entrada Streamlit. Páginas em app/telas.py.

Rodar: streamlit run streamlit_app.py
"""
import streamlit as st

from app import telas

st.set_page_config(page_title="Gestão Industrial — Entradas", layout="wide")

with st.sidebar:
    st.text_input("Usuário", key="usuario", help="Protótipo sem login: o nome informado vai para o bruto.")
    st.caption("Protótipo — onda 1, frente 1 (estoque, lote, acuracidade). Banco local DuckDB.")

st.navigation([
    st.Page(telas.pagina_upload, title="Carga de arquivos", url_path="carga"),
    st.Page(telas.pagina_contagem, title="Contagem cega", url_path="contagem"),
    st.Page(telas.pagina_investigacao, title="Investigação de divergência", url_path="investigacao"),
    st.Page(telas.pagina_cargas, title="Cargas e integridade", url_path="cargas"),
    st.Page(telas.pagina_layouts, title="Layouts de entrada", url_path="layouts"),
]).run()
