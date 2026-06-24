-- Cleans and renames raw OSHA data
WITH source AS (
    SELECT * FROM {{ source('raw', 'osha_incidents') }}
),

cleaned AS (
    SELECT
        -- Identity
        {{ dbt_utils.generate_surrogate_key(['establishment_id', 'survey_year']) }} AS incident_id,
        establishment_id,
        establishment_name,
        survey_year,

        -- Location
        UPPER(TRIM(city))           AS city,
        UPPER(TRIM(state))          AS state,
        NULLIF(TRIM(CAST(zip_code AS VARCHAR)), '')  AS zip_code,

        -- Industry
        CAST(naics_code AS VARCHAR)     AS naics_code,
        TRIM(industry_description)      AS naics_description,

        -- Workforce
        NULLIF(annual_average_employees, 0) AS avg_employees,
        NULLIF(total_hours_worked, 0)       AS total_hours_worked,

        -- Injury counts
        COALESCE(total_deaths, 0)                 AS total_deaths,
        COALESCE(total_dafw_cases, 0)             AS total_dafw_cases,
        COALESCE(total_djtr_cases, 0)             AS total_djtr_cases,
        COALESCE(total_other_cases, 0)            AS total_other_cases,
        COALESCE(total_injuries, 0)               AS total_injuries,
        COALESCE(total_skin_disorders, 0)         AS total_skin_disorders,
        COALESCE(total_respiratory_conditions, 0) AS total_respiratory_conditions,
        COALESCE(total_poisonings, 0)             AS total_poisonings,

        -- Computed: Total Recordable Incident Rate
        -- TRIR = (total_recordable_cases * 200,000) / total_hours_worked
        CASE
            WHEN total_hours_worked > 0
            THEN ROUND(
                CAST(
                    (dbt
                        (
                            COALESCE(total_dafw_cases, 0)
                            + COALESCE(total_djtr_cases, 0)
                            + COALESCE(total_other_cases, 0)
                        ) * 200000.0
                    ) / total_hours_worked
                AS NUMERIC),
                2
            )
            ELSE NULL
        END AS trir

    FROM source
    WHERE establishment_name IS NOT NULL
      AND establishment_name != ''
)

SELECT * FROM cleaned
