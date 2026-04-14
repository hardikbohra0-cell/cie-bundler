"""
CIE QP-Only Custom Bundler — Streamlit UI
Run: streamlit run app.py
"""

import streamlit as st
from backend import (
    SUBJECTS, SEASONS, PaperSelection, SortOrder,
    build_bundle,
)

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="CIE QP Bundler",
    page_icon="📄",
    layout="wide",
)

# ── Session state init ───────────────────────────────────────────────────────
if "cart" not in st.session_state:
    st.session_state.cart: list[PaperSelection] = []
if "dl_cache" not in st.session_state:
    st.session_state.dl_cache: dict = {}
if "sort_order" not in st.session_state:
    st.session_state.sort_order = SortOrder.YEAR

# ── Helpers ──────────────────────────────────────────────────────────────────
def add_to_cart(paper: PaperSelection):
    if paper not in st.session_state.cart:
        st.session_state.cart.append(paper)

def remove_from_cart(idx: int):
    st.session_state.cart.pop(idx)

# ── Header ───────────────────────────────────────────────────────────────────
st.title("📄 CIE QP Custom Bundler")
st.caption(
    "Build a print-ready PDF from selected Cambridge A-Level Question Papers. "
    "No marking schemes — QPs only."
)
st.divider()

# ── Two-column layout ─────────────────────────────────────────────────────────
col_browser, col_cart = st.columns([3, 2], gap="large")

# ════════════════════════════════════════════════════════════════════════════
# LEFT: Paper Browser
# ════════════════════════════════════════════════════════════════════════════
with col_browser:
    st.subheader("Paper Browser")

    subject_name = st.selectbox(
        "Subject",
        options=list(SUBJECTS.keys()),
    )

    c1, c2 = st.columns(2)
    with c1:
        season_label = st.selectbox(
            "Season",
            options=["All"] + list(SEASONS.keys()),
        )
    with c2:
        year_range = st.slider(
            "Year range",
            min_value=2015,
            max_value=2024,
            value=(2019, 2024),
        )

    # Component numbers vary by subject; expose a broad multiselect
    COMPONENTS = ["11","12","13","21","22","23","31","32","33","41","42","43"]
    components = st.multiselect(
        "Paper / Component",
        options=COMPONENTS,
        default=["12", "22", "32"],
    )

    st.markdown("---")

    # Build the browsable paper list
    seasons_to_show = (
        list(SEASONS.values())
        if season_label == "All"
        else [SEASONS[season_label]]
    )

    papers_available = [
        PaperSelection(
            subject_name=subject_name,
            year=yr,
            season=s,
            component=comp,
        )
        for yr in range(year_range[0], year_range[1] + 1)
        for s in seasons_to_show
        for comp in components
    ]

    if not papers_available:
        st.info("No papers match the current filters.")
    else:
        st.write(f"**{len(papers_available)} papers found** — click ➕ to add to bundle")

        for paper in papers_available:
            already_in_cart = paper in st.session_state.cart
            row_left, row_right = st.columns([4, 1])
            with row_left:
                st.text(str(paper))
            with row_right:
                if already_in_cart:
                    st.button(
                        "✓ Added",
                        key=f"btn_{paper.url}",
                        disabled=True,
                    )
                else:
                    if st.button("➕ Add", key=f"btn_{paper.url}"):
                        add_to_cart(paper)
                        st.rerun()

# ════════════════════════════════════════════════════════════════════════════
# RIGHT: Bundle Cart
# ════════════════════════════════════════════════════════════════════════════
with col_cart:
    cart_count = len(st.session_state.cart)
    st.subheader(f"Your Bundle  ({cart_count} paper{'s' if cart_count != 1 else ''})")

    # Sort order toggle
    sort_option = st.radio(
        "Sort order",
        options=["Year-wise", "Component-wise"],
        horizontal=True,
        help=(
            "Year-wise: group all 2023 papers together, then 2022, etc.\n"
            "Component-wise: group all Paper 12s together, then Paper 22, etc."
        ),
    )
    st.session_state.sort_order = (
        SortOrder.YEAR if sort_option == "Year-wise" else SortOrder.COMPONENT
    )

    st.markdown("---")

    if cart_count == 0:
        st.info("Your bundle is empty. Add papers from the browser on the left.")
    else:
        for i, paper in enumerate(st.session_state.cart):
            r1, r2 = st.columns([4, 1])
            with r1:
                st.text(str(paper))
            with r2:
                if st.button("✕", key=f"remove_{i}"):
                    remove_from_cart(i)
                    st.rerun()

        st.markdown("---")

        if st.button("🗑 Clear all", use_container_width=False):
            st.session_state.cart = []
            st.rerun()

        st.markdown(" ")

        # ── Generate PDF ──────────────────────────────────────────────────
        if st.button(
            "⬇ Generate & Download PDF",
            type="primary",
            use_container_width=True,
            disabled=(cart_count == 0),
        ):
            progress_bar = st.progress(0, text="Starting download...")

            def on_progress(i, total, label):
                pct = int((i / total) * 100)
                progress_bar.progress(pct, text=f"Fetching: {label}")

            with st.spinner("Building your bundle…"):
                try:
                    pdf_buf, warnings = build_bundle(
                        papers=st.session_state.cart,
                        sort_order=st.session_state.sort_order,
                        session_cache=st.session_state.dl_cache,
                        progress_callback=on_progress,
                    )
                    progress_bar.progress(100, text="Done!")

                    if warnings:
                        with st.expander(
                            f"⚠ {len(warnings)} file(s) missing — included as placeholder pages"
                        ):
                            for w in warnings:
                                st.write(f"• {w}")

                    subject_slug = st.session_state.cart[0].subject_name.replace(" ", "_")
                    st.download_button(
                        label="📥 Click here to download your PDF",
                        data=pdf_buf,
                        file_name=f"CIE_{subject_slug}_QP_Bundle.pdf",
                        mime="application/pdf",
                        use_container_width=True,
                    )

                except Exception as e:
                    st.error(f"Error generating PDF: {e}")
                    st.exception(e)
