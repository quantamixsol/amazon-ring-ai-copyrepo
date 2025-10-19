import os
import json
import pandas as pd
from io import BytesIO
from typing import Optional, Dict

from app.utils.strings import coerce_str


def load_excel_sheets(file_buffer: BytesIO, filename: str) -> dict:
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".xlsx", ".xlsm"]:
        return pd.read_excel(file_buffer, sheet_name=None, engine="openpyxl")
    elif ext == ".xls":
        try:
            return pd.read_excel(file_buffer, sheet_name=None, engine="xlrd")
        except Exception as e:
            raise RuntimeError("Reading .xls requires xlrd==1.2.0") from e
    else:
        raise RuntimeError(f"Unsupported file extension: {ext}")


def try_autodetect_long_text(df_dict: Dict[str, pd.DataFrame]):
    ring_brand_guidelines = ""
    approved_copy_template = ""
    prob_guideline_cols = {"brand_guidelines", "ring_brand_guidelines", "guidelines"}
    prob_template_cols = {"approved_copy_template", "copy_template", "template"}

    for sheet_name, df in df_dict.items():
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        for col in df.columns:
            lcol = str(col).strip().lower()
            if lcol in prob_guideline_cols:
                text = " ".join([coerce_str(v) for v in df[col].dropna().tolist()])
                if len(text) > len(ring_brand_guidelines):
                    ring_brand_guidelines = text
            if lcol in prob_template_cols:
                text = " ".join([coerce_str(v) for v in df[col].dropna().tolist()])
                if len(text) > len(approved_copy_template):
                    approved_copy_template = text

        if df.shape[0] <= 5 and df.shape[1] <= 5:
            concatenated = " ".join([coerce_str(v) for v in df.astype(str).values.flatten().tolist()])
            if "brand" in sheet_name.lower() and len(concatenated) > len(ring_brand_guidelines):
                ring_brand_guidelines = concatenated
            if ("template" in sheet_name.lower() or "approved" in sheet_name.lower()) and len(concatenated) > len(approved_copy_template):
                approved_copy_template = concatenated
    return ring_brand_guidelines, approved_copy_template


def row_to_content_data(row: pd.Series) -> dict:
    return row.to_dict()


def workbook_excerpt_for_llm(xls: dict, rows_per_sheet: int, char_limit: int) -> dict:
    if not isinstance(xls, dict) or not xls:
        return {"_workbook_excerpt": ""}
    summary = {}
    for sheet_name, df in xls.items():
        try:
            if isinstance(df, pd.DataFrame) and not df.empty:
                summary[sheet_name] = df.astype(str).head(rows_per_sheet).to_dict(orient="records")
        except Exception:
            continue
    text = json.dumps(summary, ensure_ascii=False)
    if len(text) > char_limit:
        text = text[:char_limit]
    return {"_workbook_excerpt": text}