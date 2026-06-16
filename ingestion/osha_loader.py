import os
from io import StringIO

import pandas as pd
import requests
from dotenv import load_dotenv
from loguru import logger
from sqlalchemy import create_engine, text

load_dotenv()

# Years of data to pull
YEARS = [2019, 2020, 2021, 2022, 2023]

# OSHA direct download URLs (CSV format)
OSHA_URLS = {
    year: f"https://www.osha.gov/sites/default/files/ITA_data_{year}.csv"
    for year in YEARS
}


def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('POSTGRES_USER')}:"
        f"{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:"
        f"{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
    )
    return create_engine(url)


def download_osha_data(year: int) -> pd.DataFrame:
    logger.info(f"Downloading OSHA data for {year}")
    url = OSHA_URLS[year]
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    df = pd.read_csv(StringIO(response.text), low_memory=False)
    df["survey_year"] = year
    logger.info(f"Downloaded {len(df):,} rows for {year}")
    return df


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    # Standardize column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

    # Numeric columns — coerce errors to NaN
    numeric_cols = [
        "annual_average_employees",
        "total_hours_worked",
        "total_deaths",
        "total_dafw_cases",
        "total_djtr_cases",
        "total_other_cases",
        "total_injuries",
        "total_skin_disorders",
        "total_respiratory_conditions",
        "total_poisonings",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop rows with no establishment name
    df = df.dropna(subset=["establishment_name"])

    # Strip whitespace from string columns
    str_cols = ["establishment_name", "city", "state", "naics_description"]
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()

    return df


def load_to_postgres(df: pd.DataFrame, engine) -> None:
    # Create schema if not exists
    with engine.connect() as conn:
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS raw"))
        conn.commit()

    # Idempotent: delete rows for this year before re-inserting
    year = int(df["survey_year"].iloc[0])
    try:
        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM raw.osha_incidents WHERE survey_year = :year"),
                {"year": year},
            )
            conn.commit()
    except Exception:
        # Table doesn't exist yet — that's fine, to_sql will create it
        pass

    df.to_sql(
        name="osha_incidents",
        schema="raw",
        con=engine,
        if_exists="append",
        index=False,
        method="multi",
        chunksize=1000,
    )
    logger.info(f"Loaded {len(df):,} rows into raw.osha_incidents for year {year}")


def run_ingestion():
    engine = get_engine()
    all_years = []

    for year in YEARS:
        try:
            df = download_osha_data(year)
            df = clean_dataframe(df)
            all_years.append(df)
        except Exception as e:
            logger.error(f"Failed to download {year}: {e}")

    if all_years:
        combined = pd.concat(all_years, ignore_index=True)
        # Load year-by-year to leverage idempotent delete
        for year_val in combined["survey_year"].unique():
            year_df = combined[combined["survey_year"] == year_val].copy()
            load_to_postgres(year_df, engine)
        logger.success(f"Ingestion complete. Total rows: {len(combined):,}")
    else:
        logger.error("No data downloaded — check network and OSHA URLs.")


if __name__ == "__main__":
    run_ingestion()
