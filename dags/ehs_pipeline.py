from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator

default_args = {
    "owner": "ehs-team",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}

with DAG(
    dag_id="ehs_incident_pipeline",
    description="End-to-end EHS&S incident data pipeline",
    default_args=default_args,
    start_date=datetime(2024, 1, 1),
    schedule_interval="0 6 * * 1",  # Every Monday at 6 AM
    catchup=False,
    tags=["ehs", "osha", "production"],
) as dag:

    # Task 1: Ingest raw OSHA data
    ingest_task = PythonOperator(
        task_id="ingest_osha_data",
        python_callable=lambda: _ingest(),
        doc="Download OSHA injury/illness CSVs and load into raw.osha_incidents",
    )

    # Task 2: Run dbt transformations
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="cd /opt/airflow/dbt && dbt run --profiles-dir .",
        doc="Build all staging and mart models",
    )

    # Task 3: Run dbt tests
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command="cd /opt/airflow/dbt && dbt test --profiles-dir .",
        doc="Run all model tests — fails DAG if any test fails",
    )

    # Task 4: Soda data quality checks
    soda_check = BashOperator(
        task_id="soda_quality_check",
        bash_command=(
            "soda scan "
            "-d ehs_db "
            "-c /opt/airflow/quality/soda_config.yml "
            "/opt/airflow/quality/checks.yml"
        ),
        doc="Run data quality checks — blocks LLM step if data is bad",
    )

    # Task 5: LLM classification
    llm_task = PythonOperator(
        task_id="llm_classify_incidents",
        python_callable=lambda: _run_llm_classification(),
        doc="Classify incidents using GPT-4o-mini and store structured output",
    )

    # DAG dependency chain
    ingest_task >> dbt_run >> dbt_test >> soda_check >> llm_task


def _ingest():
    import sys

    sys.path.insert(0, "/opt/airflow")
    from ingestion.osha_loader import run_ingestion

    run_ingestion()


def _run_llm_classification():
    import sys

    sys.path.insert(0, "/opt/airflow")
    from llm.classifier import run_classification

    run_classification()
