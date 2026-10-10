-- TraceWeave migration 0002: validate RFC 3339 attribute offsets without a PostgreSQL timestamp cast.
-- Existing attribute strings and the immutable 0001 baseline remain unchanged.

CREATE OR REPLACE FUNCTION rg_valid_attribute(kind text, v jsonb) RETURNS boolean LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE val text; latitude numeric; longitude numeric; acc numeric; parsed date;
BEGIN
 IF v IS NULL THEN RETURN false; END IF;
 IF v = 'null'::jsonb THEN RETURN kind IN ('text','number','boolean','date','datetime','url','geo'); END IF;
 CASE kind
 WHEN 'text' THEN RETURN jsonb_typeof(v)='string' AND char_length(v#>>'{}')<=10000;
 WHEN 'number' THEN RETURN jsonb_typeof(v)='number' AND abs((v#>>'{}')::numeric)<=9007199254740991;
 WHEN 'boolean' THEN RETURN jsonb_typeof(v)='boolean';
 WHEN 'url' THEN RETURN jsonb_typeof(v)='string' AND char_length(v#>>'{}')<=4096 AND (v#>>'{}') ~ '^https?://[^[:space:]]+$';
 WHEN 'datetime' THEN
  IF jsonb_typeof(v)<>'string' THEN RETURN false; END IF;
  val=v#>>'{}';
  IF val !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt]([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]+)?([Zz]|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$' THEN RETURN false; END IF;
  -- The attribute stores a JSON string, not a PostgreSQL timestamptz. Validate
  -- its local Gregorian date independently: RFC 3339 permits offsets through
  -- 23:59, while PostgreSQL's timestamptz displacement stops at 15:59.
  parsed=substring(val FROM 1 FOR 10)::date;
  RETURN true;
 WHEN 'date' THEN
  IF jsonb_typeof(v)<>'object' OR NOT v ?& ARRAY['value','precision'] OR (v-ARRAY['value','precision'])<>'{}'::jsonb THEN RETURN false; END IF;
  IF jsonb_typeof(v->'value') IS DISTINCT FROM 'string' OR jsonb_typeof(v->'precision') IS DISTINCT FROM 'string' THEN RETURN false; END IF;
  val=v->>'value';
  CASE v->>'precision'
  WHEN 'year' THEN IF val !~ '^\d{4}$' OR val='0000' THEN RETURN false; END IF; parsed=(val||'-01-01')::date;
  WHEN 'month' THEN IF val !~ '^\d{4}-\d{2}$' THEN RETURN false; END IF; parsed=(val||'-01')::date;
  WHEN 'day' THEN IF val !~ '^\d{4}-\d{2}-\d{2}$' THEN RETURN false; END IF; parsed=val::date;
  ELSE RETURN false; END CASE; RETURN true;
 WHEN 'geo' THEN
  IF jsonb_typeof(v)<>'object' OR NOT v ?& ARRAY['latitude','longitude','accuracyMeters'] OR (v-ARRAY['latitude','longitude','accuracyMeters'])<>'{}'::jsonb THEN RETURN false; END IF;
  IF jsonb_typeof(v->'latitude')<>'number' OR jsonb_typeof(v->'longitude')<>'number' THEN RETURN false; END IF;
  latitude=(v->>'latitude')::numeric; longitude=(v->>'longitude')::numeric;
  IF latitude NOT BETWEEN -90 AND 90 OR longitude NOT BETWEEN -180 AND 180 THEN RETURN false; END IF;
  IF v->'accuracyMeters'='null'::jsonb THEN RETURN true; END IF;
  IF jsonb_typeof(v->'accuracyMeters')<>'number' THEN RETURN false; END IF;
  acc=(v->>'accuracyMeters')::numeric; RETURN acc>0 AND acc<=9007199254740991;
 ELSE RETURN false;
 END CASE;
EXCEPTION WHEN invalid_text_representation OR datetime_field_overflow OR invalid_datetime_format OR numeric_value_out_of_range THEN RETURN false;
END $$;
