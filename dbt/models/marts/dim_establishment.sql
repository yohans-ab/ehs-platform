WITH staging AS (
    SELECT DISTINCT
        establishment_id,
        establishment_name,
        city,
        state,
        zip_code,
        naics_code,
        naics_description
    FROM {{ ref('stg_osha_incidents') }}
)

SELECT * FROM staging
