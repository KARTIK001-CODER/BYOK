# BYOK (Bring Your Own Knowledge) Architecture

This document provides a high-level overview of the BYOK platform's architecture, including the technologies used and the core flow of data across the system. 

## 1. System Overview

BYOK is a Retrieval-Augmented Generation (RAG) platform. It allows users to upload documents, converts those documents into embeddings (vector representations), stores them, and then uses a Large Language Model (LLM) to answer user questions based on the retrieved context from those documents.

The project is structured as a full-stack application with a clear separation of concerns:
- **Frontend (Client)**: A modern web interface for users to upload knowledge, manage settings, and chat with their knowledge base.
- **Backend (API Layer & Business Logic)**: A robust REST API that handles data processing, authentication, integration with vector and relational databases, and orchestration of RAG operations.
- **Data Persistence**: A mix of relational databases (for structured relational data) and vector databases (for semantic search).

---

## 2. Technology Stack

### Frontend (Client-Side)
The frontend is built for performance and a modern development experience:
- **Framework**: [React 19](https://react.dev/) - A JavaScript library for building user interfaces.
- **Build Tool**: [Vite](https://vitejs.dev/) - A fast, modern frontend build tool.
- **Language**: [TypeScript](https://www.typescriptlang.org/) - For static typing and better developer tooling.
- **Routing**: [React Router](https://reactrouter.com/) (v7) - For client-side navigation.
- **Icons**: [Lucide React](https://lucide.dev/) - A beautiful and consistent icon toolkit.
- **Markdown Rendering**: [React Markdown](https://github.com/remarkjs/react-markdown) (with GFM & syntax highlighting via rehype/remark plugins) for displaying rich chat responses.

### Backend (Server-Side)
The backend follows a clean architecture pattern, prioritizing type safety, validation, and modularity:
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) - A modern, fast web framework for building APIs with Python 3.8+ based on standard Python type hints.
- **Language**: [Python 3.11/3.13](https://www.python.org/)
- **Data Validation**: [Pydantic](https://docs.pydantic.dev/latest/) - Data parsing and validation using Python type annotations.
- **ORM (Object-Relational Mapping)**: [SQLAlchemy](https://www.sqlalchemy.org/) - The Python SQL toolkit and Object Relational Mapper.
- **Database Migrations**: [Alembic](https://alembic.sqlalchemy.org/en/latest/) - A lightweight database migration tool for usage with SQLAlchemy.
- **RAG & AI Stack**: Custom modular integrations for LLM providers (OpenAI, Gemini, Groq, local models) and Embedding models.
- **Package Management**: Typically `pip` with `pyproject.toml` (potentially using `poetry` or standard `venv`).

---

## 3. Backend Architecture & Core Modules

The backend (`/backend/app`) is designed in a modular way, where different domains of the application are encapsulated within their own services.

### Directory Structure & Responsibilities

1. **`app/main.py`**: The application entry point. Initializes FastAPI, configures CORS, handles global exception logic, and registers API routers.
2. **`app/core/`**: Core configuration (environment variables), security (password hashing), and application logging.
3. **`app/api/`**: The presentation layer. Defines the REST endpoints (`GET`, `POST`, etc.), receives HTTP requests, validates them via schemas, and calls the appropriate services.
4. **`app/db/`**: Handles the connection to the underlying relational database (via SQLAlchemy).
5. **`app/models/`**: SQLAlchemy models that define the structure of the database tables (e.g., `User`, `Document`, `Conversation`, `Message`).
6. **`app/schemas/`**: Pydantic models (Data Transfer Objects) that define the shape of the data entering (requests) and leaving (responses) the API.
7. **`app/services/`**: The business logic layer. 
   - `auth/`: User authentication, JWT token generation, and password validation.
   - `ingestion/`: Handles document uploads, extracts text (PDF, Word, Markdown, Text), normalizes it, and splits it into smaller chunks suitable for embedding.
   - `embeddings/`: Takes text chunks and converts them into dense vector embeddings.
   - `retrieval/`: Handles searching the vector store (Keyword search, Vector similarity, Hybrid fusion) to find context relevant to a user's prompt.
   - `llm/`: The interface to communicate with Large Language Models to generate answers.
   - `rag/`: The orchestrator that ties Retrieval and LLMs together (managing context, citations, and prompts).
   - `documents/`, `users/`, `organizations/`: Standard CRUD services for application entities.

---

## 4. The Core Flow (How a Chat Works)

When a user asks a question about their uploaded documents, the data flows through the system as follows:

1. **Request**: The Frontend sends a `POST` request with the user's message to the `app/api/` chat endpoint.
2. **Validation**: The API layer uses Pydantic (`app/schemas/`) to validate the incoming request.
3. **Retrieval (RAG Service)**: The `rag` service takes the user's message and asks the `retrieval` service to find relevant context.
4. **Vector Search**: The `retrieval` service converts the user's message into an embedding and performs a similarity search against the previously embedded `document_chunks` in the database.
5. **Prompt Construction**: The `rag` service gathers the retrieved chunks (context), formats them along with the conversation history into a structured prompt.
6. **LLM Generation**: The prompt is sent to the `llm` service (which talks to an AI provider like OpenAI, Gemini, etc.).
7. **Response & Citations**: The LLM streams back an answer based *only* on the provided context. The `rag` service maps the chunks used back to their source documents to generate citations.
8. **Delivery**: The answer and citations are returned through the API to the Frontend, which renders the markdown response to the user.
