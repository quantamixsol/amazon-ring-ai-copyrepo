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
        "DISCLAIMER: All generated copy should be reviewed and approved by one of our in-house copywriters and, where applicable, legal counsel before publication or use. "
        "This content is provided as a starting point and may require modifications to ensure accuracy, compliance with relevant regulations, and alignment with our brand voice."
    )