-- DECIDE-0004: the cache key is the bytes that were sent. JSONB forgets key
-- order and the sorted cassette forgets it too, and order is now part of the
-- key, so the body is kept as the text it was.
ALTER TABLE model_calls ADD COLUMN wire text;
