"""Shared plumbing for the HS (Health & Safety) issues dashboard.

Everything that turns a raw issues-export CSV into the JSON shape the
dashboard and the PDF report both consume lives here. main.py, export.py
and report.py all reach into this module; it imports nothing of theirs.
"""

import io
import os
from typing import Dict, List, Optional

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------
# Canonical buckets
# ---------------------------------------------------------------------

CANONICAL_CATEGORIES = ["PVC", "Warehouse", "Yard", "Aluminium", "Office"]
OTHER_CATEGORY = "Other"

STATUS_VALUES = {"open", "resolved", "closed", "in progress", "investigating", "new", "reopened"}
RESOLVED_VALUES = {"resolved", "closed", "complete", "completed"}

MAX_ASSIGNEES = 12
UNASSIGNED = "Unassigned"
OTHER_ASSIGNEES = "Other"


# ---------------------------------------------------------------------
# Column detection — export headers vary run to run, so we match on
# header text first and fall back to sniffing the values themselves.
# ---------------------------------------------------------------------

def _detect_status_col(df: pd.DataFrame) -> Optional[str]:
    blank = [c for c in df.columns if c.strip() == ""]
    if blank:
        return blank[0]
    best, best_score = None, 0.0
    for c in df.columns:
        vals = df[c].astype(str).str.strip().str.lower()
        vals = vals[vals != ""]
        if vals.empty:
            continue
        score = vals.isin(STATUS_VALUES).mean()
        if score > best_score:
            best, best_score = c, score
    return best if best_score > 0.5 else None


def _bucket_category(raw: str) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return OTHER_CATEGORY
    for cat in CANONICAL_CATEGORIES:
        key = cat.lower()
        if key in s or s in key:
            return cat
    if "alu" in s:
        return "Aluminium"
    return OTHER_CATEGORY


def _detect_category_col(df: pd.DataFrame) -> Optional[str]:
    candidates = [c for c in df.columns if c.strip().lower() in ("location", "category")]
    candidates.sort(key=lambda c: 0 if c.strip().lower() == "location" else 1)
    best, best_score = None, 0.0
    for c in candidates:
        score = df[c].astype(str).map(lambda v: _bucket_category(v) != OTHER_CATEGORY).mean()
        if score > best_score:
            best, best_score = c, score
    return best or (candidates[0] if candidates else None)


def _detect_assignee_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        lc = c.strip().lower()
        if lc == "assignee" or ("assign" in lc and "created" not in lc):
            return c
    return None


def _detect_date_col(df: pd.DataFrame) -> Optional[str]:
    for name in ("created", "occurred at", "occurred"):
        for c in df.columns:
            if c.strip().lower() == name:
                return c
    return None


def _detect_site_col(df: pd.DataFrame) -> Optional[str]:
    for c in df.columns:
        if c.strip().lower() == "site":
            return c
    return None


def _bucket_status(raw: str) -> str:
    s = (raw or "").strip().lower()
    return "Resolved" if s in RESOLVED_VALUES else "Open"


# ---------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------

def parse_issues_csv(raw: bytes) -> Dict:
    """Parse an issues-export CSV into the aggregates the dashboard/PDF need.

    Raises ValueError with a user-facing message on anything that stops us
    from producing a sensible dashboard (empty file, no date column, etc).
    """
    if not raw or not raw.strip():
        raise ValueError("That file is empty.")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")

    try:
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    except Exception as e:
        raise ValueError(f"Could not read that as a CSV: {e}")

    df = df.dropna(axis=0, how="all")
    df = df[df.apply(lambda r: any(str(v).strip() for v in r), axis=1)]
    if df.empty:
        raise ValueError("The CSV has no data rows.")

    date_col = _detect_date_col(df)
    status_col = _detect_status_col(df)
    category_col = _detect_category_col(df)
    assignee_col = _detect_assignee_col(df)
    site_col = _detect_site_col(df)

    if not date_col:
        raise ValueError("Could not find a 'Created' date column in this CSV.")
    if not status_col:
        raise ValueError("Could not find a status (Open/Resolved) column in this CSV.")

    dates = pd.to_datetime(df[date_col].str.strip(), dayfirst=True, errors="coerce")
    keep = dates.notna()
    df, dates = df[keep].copy(), dates[keep]
    if df.empty:
        raise ValueError("No rows had a parseable Created date.")

    df["_month"] = dates.dt.to_period("M")
    df["_status"] = df[status_col].map(_bucket_status)
    df["_category"] = df[category_col].map(_bucket_category) if category_col else OTHER_CATEGORY
    df["_assignee"] = (
        df[assignee_col].map(lambda v: v.strip() or UNASSIGNED) if assignee_col else UNASSIGNED
    )

    months = sorted(df["_month"].unique())
    by_month = [
        {"month": str(m), "label": m.strftime("%b %Y"), "count": int((df["_month"] == m).sum())}
        for m in months
    ]

    cats_present = [c for c in CANONICAL_CATEGORIES if (df["_category"] == c).any()]
    cats_present = cats_present or list(CANONICAL_CATEGORIES)
    if (df["_category"] == OTHER_CATEGORY).any():
        cats_present.append(OTHER_CATEGORY)

    cat_series = {
        cat: [int(((df["_month"] == m) & (df["_category"] == cat)).sum()) for m in months]
        for cat in cats_present
    }
    category_by_month = {
        "months": [m.strftime("%b %Y") for m in months],
        "categories": cats_present,
        "series": cat_series,
    }

    counts = df.groupby("_assignee").size().sort_values(ascending=False)
    top = list(counts.index[:MAX_ASSIGNEES])
    if len(counts) > MAX_ASSIGNEES:
        df["_assignee_bucket"] = df["_assignee"].where(df["_assignee"].isin(top), OTHER_ASSIGNEES)
    else:
        df["_assignee_bucket"] = df["_assignee"]

    bucket_counts = df.groupby("_assignee_bucket").size().sort_values(ascending=False)
    assignees = list(bucket_counts.index)
    open_counts = [int(((df["_assignee_bucket"] == a) & (df["_status"] == "Open")).sum()) for a in assignees]
    resolved_counts = [int(((df["_assignee_bucket"] == a) & (df["_status"] == "Resolved")).sum()) for a in assignees]
    status_by_assignee = {"assignees": assignees, "open": open_counts, "resolved": resolved_counts}

    summary = {
        "total": int(len(df)),
        "open": int((df["_status"] == "Open").sum()),
        "resolved": int((df["_status"] == "Resolved").sum()),
        "date_from": dates.min().strftime("%d %b %Y"),
        "date_to": dates.max().strftime("%d %b %Y"),
        "sites": sorted(df[site_col].astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist())
        if site_col else [],
    }

    return {
        "summary": summary,
        "by_month": by_month,
        "category_by_month": category_by_month,
        "status_by_assignee": status_by_assignee,
    }
