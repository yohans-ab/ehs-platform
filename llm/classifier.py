import os
from typing import Literal

import anthropic
import instructor
import pandas as pd
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

load_dotenv()


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

class IncidentClassification(BaseModel):
    severity: Literal["low", "medium", "high", "critical"] = Field(
        description=(
            "Overall severity: "
            "low (minor/no recordable injuries), "
            "medium (recordable, no DAFW), "
            "high (days away from work), "
            "critical (one or more fatalities)"
        )
    )
    root_cause_category: Literal[
        "slip_trip_fall",
        "struck_by_object",
        "ergonomic",
        "chemical_exposure",
        "equipment_failure",
        "human_error",
        "environmental",
        "other",
    ] = Field(description="Primary root cause category based on injury type mix")
    prevention_actions: list[str] = Field(
        description="Exactly 3 specific, actionable prevention recommendations",
        min_length=3,
        max_length=3,
    )
    confidence_score: float = Field(
        description="Model confidence in classification, 0.0–1.0",
        ge=0.0,
        le=1.0,
    )


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_prompt(row: dict) -> str:
    return f"""You are an EHS specialist analyzing a workplace incident record.

Establishment: {row.get('establishment_name', 'Unknown')}
Industry: {row.get('naics_description', 'Unknown')} (NAICS: {row.get('naics_code', 'N/A')})
Location: {row.get('city', '')}, {row.get('state', '')}
Year: {row.get('survey_year', 'Unknown')}

Incident counts:
- Deaths: {row.get('total_deaths', 0)}
- Days Away From Work cases: {row.get('total_dafw_cases', 0)}
- Job Transfer/Restriction cases: {row.get('total_djtr_cases', 0)}
- Other recordable cases: {row.get('total_other_cases', 0)}
- Injuries: {row.get('total_injuries', 0)}
- Skin disorders: {row.get('total_skin_disorders', 0)}
- Respiratory conditions: {row.get('total_respiratory_conditions', 0)}
- Poisonings: {row.get('total_poisonings', 0)}
- TRIR (Total Recordable Incident Rate): {row.get('trir', 'N/A')}

Classify the severity, identify the most likely root cause, and provide 3 specific prevention actions for this establishment."""


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def classify_incident(client, row: dict) -> dict:
    result: IncidentClassification = client.chat.completions.create(
        model="gpt-4o-mini",
        response_model=IncidentClassification,
        messages=[{"role": "user", "content": build_prompt(row)}],
        temperature=0.2,
    )
    return {
        "incident_id": row["incident_id"],
        "severity": result.severity,
        "root_cause_category": result.root_cause_category,
        "prevention_action_1": result.prevention_actions[0],
        "prevention_action_2": result.prevention_actions[1],
        "prevention_action_3": result.prevention_actions[2],
        "confidence_score": result.confidence_score,
    }


def get_engine():
    return create_engine(
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
    )


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def run_classification(limit: int = 500):
    """
    Classify unprocessed incidents using GPT-4o-mini.
    Defaults to 500 rows to keep API costs predictable.
    Increase limit (or set to None) for full runs.
    """
    engine = get_engine()
    client = instructor.from_openai(openai.OpenAI(api_key=os.getenv("CLAUDE_API_KEY ")))

    # Ensure classification table exists
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE SCHEMA IF NOT EXISTS analytics_marts;
            CREATE TABLE IF NOT EXISTS analytics_marts.llm_classifications (
                incident_id           VARCHAR PRIMARY KEY,
                severity              VARCHAR,
                root_cause_category   VARCHAR,
                prevention_action_1   TEXT,
                prevention_action_2   TEXT,
                prevention_action_3   TEXT,
                confidence_score      FLOAT,
                classified_at         TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.commit()

    # Fetch unclassified incidents, prioritise most severe
    query = """
        SELECT
            f.*,
            e.establishment_name,
            e.naics_description
        FROM analytics_marts.fct_incidents f
        JOIN analytics_marts.dim_establishment e USING (establishment_id)
        WHERE f.incident_id NOT IN (
            SELECT incident_id FROM analytics_marts.llm_classifications
        )
        AND f.trir IS NOT NULL
        ORDER BY f.total_deaths DESC, f.trir DESC
        LIMIT :limit
    """
    df = pd.read_sql(text(query), engine, params={"limit": limit})
    logger.info(f"Classifying {len(df)} incidents")

    results = []
    for _, row in df.iterrows():
        try:
            classification = classify_incident(client, row.to_dict())
            results.append(classification)
        except Exception as e:
            logger.warning(f"Failed to classify {row['incident_id']}: {e}")

    if results:
        results_df = pd.DataFrame(results)
        results_df.to_sql(
            "llm_classifications",
            schema="analytics_marts",
            con=engine,
            if_exists="append",
            index=False,
            method="multi",
        )
        logger.success(f"Classified and stored {len(results)} incidents")
    else:
        logger.warning("No incidents classified — check data availability.")


if __name__ == "__main__":
    run_classification()
