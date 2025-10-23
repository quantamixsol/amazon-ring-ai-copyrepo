import os
import streamlit as st
from app.io.files import get_logo_path


def setup_page():
    icon = get_logo_path() or ""
    st.set_page_config(page_title="Ring CopyForge", page_icon=icon if icon else None, layout="wide")

    c1, c2 = st.columns([1, 6])
    with c1:
        if icon and os.path.exists(icon):
            st.image(icon, width=500)
    with c2:
        st.markdown('<h1 style="margin:0;">Ring CopyForge</h1>', unsafe_allow_html=True)


def footer_disclaimer():
    st.markdown("---")
    st.warning(
        "DISCLAIMER: AI can make mistakes. Please review the outputs generated and follow established content approval processes, including any necessary legal review requirements, when using copy generated from this tool."
    )