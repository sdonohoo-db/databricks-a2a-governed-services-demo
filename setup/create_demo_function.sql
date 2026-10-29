CREATE OR REPLACE FUNCTION main.default.a2a_demo_shipping_quote(
  origin STRING COMMENT 'Origin city or distribution center',
  destination STRING COMMENT 'Destination city or distribution center',
  weight_kg DOUBLE COMMENT 'Shipment weight in kilograms'
)
RETURNS STRING
LANGUAGE SQL
COMMENT 'Governed demo function used by the Databricks A2A enterprise services agent.'
RETURN CONCAT(
  'Estimated governed quote from ',
  origin,
  ' to ',
  destination,
  ': $',
  CAST(ROUND(12.0 + GREATEST(weight_kg, 0.0) * 1.85, 2) AS STRING),
  ' USD'
);
