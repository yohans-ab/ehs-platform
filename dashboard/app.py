import os

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

st.set_page_config(
    page_title="EHS&S Incident Intelligence",
    page_icon="🦺",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

@st.cache_resource
def get_engine():
    return create_engine(
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
    )


@st.cache_data(ttl=3600)
def load_data() -> pd.DataFrame:
    query = """
        SELECT
            f.*,
            e.establishment_name,
            e.naics_description,
            e.city          AS est_city,
            e.state         AS est_state,
            t.period_label,
            c.severity,
            c.root_cause_category,
            c.prevention_action_1,
            c.prevention_action_2,
            c.prevention_action_3,
            c.confidence_score
        FROM analytics_marts.fct_incidents f
        JOIN analytics_marts.dim_establishment e USING (establishment_id)
        JOIN analytics_marts.dim_time          t USING (survey_year)
        LEFT JOIN analytics_marts.llm_classifications c USING (incident_id)
    """
    return pd.read_sql(query, get_engine())


# ---------------------------------------------------------------------------
# Load + filter
# ---------------------------------------------------------------------------

try:
    df = load_data()
except Exception as e:
    st.error(f"Could not connect to database: {e}")
    st.info("Make sure Postgres is running and your .env is configured.")
    st.stop()

# ── Header ──────────────────────────────────────────────────────────────────
st.title("🦺 EHS&S Incident Intelligence Platform")
st.caption("Powered by OSHA public data · dbt · GPT-4o-mini · Soda")

# ── Sidebar Filters ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    years = st.multiselect(
        "Year",
        sorted(df["survey_year"].unique()),
        default=sorted(df["survey_year"].unique()),
    )
    states = st.multiselect("State", sorted(df["est_state"].dropna().unique()))
    severity_filter = st.multiselect(
        "Severity (LLM)", ["low", "medium", "high", "critical"]
    )
    naics_filter = st.multiselect(
        "Industry (NAICS description)",
        sorted(df["naics_description"].dropna().unique()),
    )

filtered = df[df["survey_year"].isin(years)]
if states:
    filtered = filtered[filtered["est_state"].isin(states)]
if severity_filter:
    filtered = filtered[filtered["severity"].isin(severity_filter)]
if naics_filter:
    filtered = filtered[filtered["naics_description"].isin(naics_filter)]

# ── KPI Row ──────────────────────────────────────────────────────────────────
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Establishments", f"{filtered['establishment_id'].nunique():,}")
col2.metric("Total Deaths", f"{int(filtered['total_deaths'].sum()):,}")
col3.metric("Recordable Cases", f"{int(filtered['total_recordable_cases'].sum()):,}")
col4.metric("Avg TRIR", f"{filtered['trir'].mean():.2f}")
classified_pct = filtered["severity"].notna().mean()
col5.metric("LLM Classified", f"{classified_pct:.0%}")

st.divider()

# ── TRIR Trend ───────────────────────────────────────────────────────────────
st.subheader("📈 TRIR Trend by Year")
trir_trend = (
    filtered.groupby(["survey_year", "period_label"])["trir"]
    .mean()
    .reset_index()
    .rename(columns={"trir": "avg_trir"})
)
fig_trend = px.line(
    trir_trend,
    x="survey_year",
    y="avg_trir",
    markers=True,
    color="period_label",
    labels={"survey_year": "Year", "avg_trir": "Average TRIR", "period_label": "Period"},
    color_discrete_map={
        "Pre-COVID": "#2563EB",
        "COVID-19 Year": "#DC2626",
        "Post-COVID": "#16A34A",
    },
)
st.plotly_chart(fig_trend, use_container_width=True)

st.divider()

# ── LLM Analysis ─────────────────────────────────────────────────────────────
classified = filtered.dropna(subset=["root_cause_category"])

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🔍 Root Cause Categories (LLM)")
    if not classified.empty:
        root_counts = classified["root_cause_category"].value_counts().reset_index()
        root_counts.columns = ["category", "count"]
        fig_root = px.bar(
            root_counts,
            x="count",
            y="category",
            orientation="h",
            color="count",
            color_continuous_scale="Reds",
            labels={"count": "Incidents", "category": "Root Cause"},
        )
        fig_root.update_layout(showlegend=False, coloraxis_showscale=False)
        st.plotly_chart(fig_root, use_container_width=True)
    else:
        st.info("Run `python llm/classifier.py` to populate classification data.")

with col_right:
    st.subheader("⚠️ Severity Distribution (LLM)")
    if not classified.empty:
        sev_counts = classified["severity"].value_counts().reset_index()
        sev_counts.columns = ["severity", "count"]
        fig_sev = px.pie(
            sev_counts,
            names="severity",
            values="count",
            color="severity",
            color_discrete_map={
                "low": "#22C55E",
                "medium": "#EAB308",
                "high": "#F97316",
                "critical": "#EF4444",
            },
        )
        st.plotly_chart(fig_sev, use_container_width=True)

st.divider()

# ── Top States by TRIR ────────────────────────────────────────────────────────
st.subheader("🗺️ Top 15 States by Average TRIR")
state_trir = (
    filtered.groupby("est_state")["trir"]
    .mean()
    .reset_index()
    .rename(columns={"trir": "avg_trir", "est_state": "state"})
    .sort_values("avg_trir", ascending=False)
    .head(15)
)
fig_states = px.bar(
    state_trir,
    x="state",
    y="avg_trir",
    color="avg_trir",
    color_continuous_scale="OrRd",
    labels={"state": "State", "avg_trir": "Average TRIR"},
)
fig_states.update_layout(coloraxis_showscale=False)
st.plotly_chart(fig_states, use_container_width=True)

st.divider()

# ── Incident Table with Prevention Actions ────────────────────────────────────
st.subheader("📋 Top Incidents with LLM Prevention Actions")
table_cols = [
    "establishment_name",
    "est_state",
    "survey_year",
    "total_deaths",
    "total_recordable_cases",
    "trir",
    "severity",
    "root_cause_category",
    "prevention_action_1",
    "prevention_action_2",
    "prevention_action_3",
    "confidence_score",
]
available = [c for c in table_cols if c in filtered.columns]
top = (
    filtered[available]
    .dropna(subset=["severity"])
    .sort_values(["total_deaths", "trir"], ascending=False)
    .head(50)
)

if top.empty:
    st.info("No classified incidents to display. Run the LLM classifier first.")
else:
    st.dataframe(top, use_container_width=True, hide_index=True)

# ── Footer ────────────────────────────────────────────────────────────────────
st.caption(
    "Data: OSHA ITA public dataset (2019–2023) · "
    "Transformations: dbt · Quality: soda.io · LLM: GPT-4o-mini via instructor"
)
