CREATE TABLE tags (id INTEGER PRIMARY KEY, name VARCHAR, synonyms VARCHAR, flags INTEGER);
CREATE UNIQUE INDEX tags_name_idx ON tags (name);
