"""Render compact cards from already-retrieved evidence facts."""

import streamlit as st

from ui.formatting import esc


def render_facts(facts):
    if not facts:
        return
    st.markdown(
        "<div class='evidence-facts'>"
        + "".join(
            f"<div class='evidence-fact'><div class='fact-resource'>{esc(f['resource'])}</div>"
            f"<strong>{esc(f['value'])}</strong><div>{esc(f['label'])}</div>"
            f"<span>{esc(f['context'])}</span></div>"
            for f in facts
        )
        + "</div>",
        unsafe_allow_html=True,
    )
