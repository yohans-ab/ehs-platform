WITH years AS (
    SELECT DISTINCT survey_year FROM {{ ref('stg_osha_incidents') }}
)

SELECT
    survey_year,
    CASE
        WHEN survey_year = 2020 THEN 'COVID-19 Year'
        WHEN survey_year < 2020  THEN 'Pre-COVID'
        ELSE 'Post-COVID'
    END AS period_label
FROM years
ORDER BY survey_year
