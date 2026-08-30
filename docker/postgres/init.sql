-- Initialize PostgreSQL database for RAGForge
-- Enable the pgvector extension for dense and hybrid vector search operations

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
