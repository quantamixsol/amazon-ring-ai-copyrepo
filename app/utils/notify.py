import streamlit as st

def do_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
    else:
        st.session_state["_force_refresh"] = st.session_state.get("_force_refresh", 0) + 1


def notify(msg: str, icon: str | None = None):
    if hasattr(st, "toast"):
        st.toast(msg, icon=icon)
    else:
        st.info(msg)