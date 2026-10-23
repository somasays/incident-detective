"""Temporal SRE lab. Run with: uv run streamlit run app.py."""

import config  # noqa: F401 -- disable tracing before LangGraph imports

# isort: split
import streamlit as st

from ui.temporal_styles import CSS
from ui.temporal_workspace import temporal_workspace

st.set_page_config(
    page_title="Incident Detective · Temporal SRE lab",
    page_icon="◉",
    layout="wide",
    initial_sidebar_state="collapsed",
)
st.markdown(CSS, unsafe_allow_html=True)
temporal_workspace()
