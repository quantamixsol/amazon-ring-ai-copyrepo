import streamlit as st
from app.services.validation import total_chars_for_result


def render_preview(first_sheet_name: str, first_df, file_loaded: bool, preview_visible: bool):
    if preview_visible and first_df is not None:
        st.markdown("### 👀 Preview (First Sheet Only)")
        preview_rows = st.slider("Rows to show", 5, 500, 50, 5, key="preview_rows_first")
        st.write(f"**{first_sheet_name}** — {first_df.shape[0]} rows × {first_df.shape[1]} columns")
        st.dataframe(first_df.head(preview_rows) if first_df.shape[0] > preview_rows else first_df, use_container_width=True)
    elif not file_loaded:
        st.info("Use the **sidebar** to upload/select a file and click **Show** to preview.")
    else:
        st.info("Preview is hidden. Click **Show** in the sidebar to display the Excel preview.")


def render_results(variant_label: str, selected_variant: str, results: list[dict], expected_fields: list[str]):
    for i, result in enumerate(results, 1):
        if 'error' in result:
            st.error(f"{variant_label} — Variation {i}: {result['error']}")
            if 'raw' in result:
                with st.expander(f"{variant_label} — Raw {i}"):
                    st.code(result['raw'])
            continue

        char_count = total_chars_for_result(result, expected_fields)

        if selected_variant == "ring":
            with st.expander(f"{variant_label} — 📝 Variation {i}", expanded=(i == 1)):
                st.text_area("Title", result.get("Content_Title", ""), key=f"{selected_variant}_title_{i}")
                st.text_area("Body", result.get("Content_Body", ""), key=f"{selected_variant}_body_{i}")
                st.text_input("Headlines (pipe-separated)", result.get("Headline_Variants", ""), key=f"{selected_variant}_head_{i}")
                cA, cB = st.columns(2)
                with cA:
                    st.text_input("Primary Keywords", result.get("Keywords_Primary", ""), key=f"{selected_variant}_kw1_{i}")
                with cB:
                    st.text_input("Secondary Keywords", result.get("Keywords_Secondary", ""), key=f"{selected_variant}_kw2_{i}")
                st.text_area("Description", result.get("Description", ""), key=f"{selected_variant}_desc_{i}")
                st.text(f"Total charaters count : {char_count}")

        elif selected_variant == "social":
            with st.expander(f"{variant_label} — 📣 Variation {i}", expanded=(i == 1)):
                st.text_area("Hashtags", result.get("Hashtags", ""), key=f"{selected_variant}_hashtags_{i}")
                st.text_area("Engagement Hook", result.get("Engagement_Hook", ""), key=f"{selected_variant}_hook_{i}")
                st.text_area("Clear Value Proposition", result.get("Value_Prop", ""), key=f"{selected_variant}_vp_{i}")
                st.text_area("Address Missed Deliveries & Absence Concerns", result.get("Address_Concerns", ""), key=f"{selected_variant}_concerns_{i}")
                st.text_area("Content", result.get("Content", ""), key=f"{selected_variant}_content_{i}")
                st.text(f"Total charaters count : {char_count}")

        elif selected_variant == "email":
            with st.expander(f"{variant_label} — ✉️ Variation {i}", expanded=(i == 1)):
                st.text_input("Subject Line", result.get("Subject_Line", ""), key=f"{selected_variant}_subj_{i}")
                st.text_input("Greeting", result.get("Greeting", ""), key=f"{selected_variant}_greet_{i}")
                st.text_area("Main Content (100-150 words)", result.get("Main_Content", ""), key=f"{selected_variant}_main_{i}")
                st.text_input("Reference", result.get("Reference", ""), key=f"{selected_variant}_ref_{i}")
                st.text(f"Total charaters count : {char_count}")

        elif selected_variant == "audience":
            with st.expander(f"{variant_label} — 🧩 Variation {i}", expanded=(i == 1)):
                st.text_area("Emphasise easy installation & self-setup", result.get("Easy_Installation_Self_Setup", ""), key=f"{selected_variant}_install_{i}")
                st.text_area("Highlight technical features & control", result.get("Technical_Features_and_Control", ""), key=f"{selected_variant}_features_{i}")
                st.text_area("Include technical specifications", result.get("Technical_Specifications", ""), key=f"{selected_variant}_specs_{i}")
                st.text_area("Maintain security benefits messaging", result.get("Security_Benefits_Messaging", ""), key=f"{selected_variant}_security_{i}")
                st.text(f"Total charaters count : {char_count}")