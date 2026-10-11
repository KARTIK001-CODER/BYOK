-- Initialize PostgreSQL database for TracePilot
-- Enable the pgvector extension for dense and hybrid vector search operations

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
