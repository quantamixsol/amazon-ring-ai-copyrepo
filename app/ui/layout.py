import os
import streamlit as st
from app.io.files import get_logo_path


def setup_page():
    icon = get_logo_path() or ""
    st.set_page_config(page_title="Ring CopyForge", page_icon=icon, layout="wide")
    if icon:
        st.image(icon, width=200)
    st.title("Ring CopyForge")
    st.caption(
        "Upload your Excel in the sidebar, pick a Product Unique Identifier (optionally via Advanced), choose a prompt mode, tweak the authoring context, select provider/model, and then generate."
    )


def footer_disclaimer():
    st.markdown("---")
    st.warning(
        "DISCLAIMER: All generated copy should be reviewed and approved by one of our in-house copywriters and, where applicable, legal counsel before publication or use. "
        "This content is provided as a starting point and may require modifications to ensure accuracy, compliance with relevant regulations, and alignment with our brand voice."
    )