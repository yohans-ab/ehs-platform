WITH staging AS (
    SELECT * FROM {{ ref('stg_osha_incidents') }}
)

SELECT
    incident_id,
    establishment_id,
    survey_year,
    naics_code,
    state,
    city,

    -- Measures
    avg_employees,
    total_hours_worked,
    total_deaths,
    total_dafw_cases,
    total_djtr_cases,
    total_other_cases,
    total_injuries,
    total_skin_disorders,
    total_respiratory_conditions,
    total_poisonings,
    trir,

    -- Derived: total recordable cases
    (total_dafw_cases + total_djtr_cases + total_other_cases) AS total_recordable_cases

FROM staging
