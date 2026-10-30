CREATE OR REPLACE FUNCTION {{FUNCTION_NAME}}(
  origin STRING COMMENT 'Origin city or distribution center',
  destination STRING COMMENT 'Destination city or distribution center',
  weight_kg DOUBLE COMMENT 'Shipment weight in kilograms'
)
RETURNS STRING
LANGUAGE SQL
COMMENT 'Demo function used by the Databricks A2A enterprise services agent.'
RETURN CONCAT(
  'Estimated quote from ',
  origin,
  ' to ',
  destination,
  ': $',
  CAST(ROUND(12.0 + GREATEST(weight_kg, 0.0) * 1.85, 2) AS STRING),
  ' USD'
);
