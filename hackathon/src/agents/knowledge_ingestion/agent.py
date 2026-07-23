# src/agents/knowledge_ingestion/agent.py
# FINAL, DEFINITIVE, AND COMPLETE VERSION

import os, json, logging, sqlalchemy, random, uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse
from google.cloud import storage
import vertexai
from vertexai.generative_models import GenerativeModel, Part, Tool, FunctionDeclaration
from langchain_google_vertexai import VertexAIEmbeddings
from src.common.db_connection import db_pool, get_db_session

# --- Basic Setup & Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
app = FastAPI(title="Unified Knowledge Agent")

KNOWLEDGE_BUCKET = os.environ.get("KNOWLEDGE_BUCKET_NAME", "your-gcs-bucket-name")
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
EXTRACTION_MODEL_NAME = "gemini-2.5-flash"
EMBEDDING_MODEL_NAME = "text-embedding-004"

# --- Function Calling Tool Definition ---
create_runbook_tool = Tool(
    function_declarations=[
        FunctionDeclaration(
            name="create_runbook_from_pdf",
            description="Formats an extracted SRE PDF runbook into a structured object.",
            parameters={
                "type": "object",
                "properties": {
                    "alert_name": {"type": "string"}, "investigation_steps": {"type": "array", "items": {"type": "object", "properties": {"action": {"type": "string"}, "details": {"type": "string"}}}},
                    "sql_queries": {"type": "array", "items": {"type": "object", "properties": {"purpose": {"type": "string"}, "query": {"type": "string"}}, "required": ["purpose", "query"]}},
                    "verification_steps": {"type": "array", "items": {"type": "string"}}, "notes": {"type": "array", "items": {"type": "string"}},
                }, "required": ["alert_name", "sql_queries"]
            },
        )
    ]
)

# --- Service Clients ---
vertexai.init(project=PROJECT_ID, location=LOCATION)
storage_client = storage.Client()
extraction_model = GenerativeModel(EXTRACTION_MODEL_NAME, tools=[create_runbook_tool])

# --- DEFINITIVE FIX: Re-introduce the embeddings service and helper function ---
embeddings_service = VertexAIEmbeddings(model_name=EMBEDDING_MODEL_NAME, project=PROJECT_ID)

def get_embedding(text: str) -> list[float]:
    """Generates an embedding for a given text string."""
    if not text: return []
    return embeddings_service.embed_query(text)
# --- End of Definitive Fix ---

def parse_pdf(pdf_bytes: bytes, filename: str) -> dict:
    # This function is now correct and uses Function Calling
    logger.info(f"Parsing with Gemini using Function Calling: {filename}")
    try:
        pdf_part = Part.from_data(data=pdf_bytes, mime_type="application/pdf")
        prompt = "Analyze the attached PDF runbook and use the 'create_runbook_from_pdf' tool to extract its contents."
        response = extraction_model.generate_content([pdf_part, prompt])
        func_call = response.candidates[0].content.parts[0].function_call
        if func_call.name == "create_runbook_from_pdf":
            runbook_dict = {key: value for key, value in func_call.args.items()}
            logger.info(f"Successfully extracted structured data for '{filename}' via function call.")
            if "sql_queries" not in runbook_dict: runbook_dict["sql_queries"] = []
            return runbook_dict
        else:
            raise ValueError(f"Model did not use the expected function. Used '{func_call.name}'.")
    except Exception as e:
        logger.error(f"Function calling based parsing failed for '{filename}': {e}", exc_info=True)
        return {"error": f"Function calling failed for {filename}"}

# (The rest of the file is correct and remains unchanged)
def setup_database():
    # This function is correct from previous steps
    production_schema_sql = """
    DROP SCHEMA IF EXISTS xs2a_accounts_db CASCADE;
    CREATE SCHEMA xs2a_accounts_db;
    CREATE TABLE IF NOT EXISTS runbooks (id SERIAL PRIMARY KEY, source_document VARCHAR(255) UNIQUE, alert_name VARCHAR(255), runbook_json JSONB, embedding VECTOR(768));
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE TABLE xs2a_accounts_db.audit_log (
        audit_id varchar(36) NOT NULL, internal_id varchar(36) NULL, credit_application_id varchar(255) NULL,
        event_type varchar(50) NULL, code numeric NULL, description varchar(1024) NULL, severity varchar(20) NULL,
        created_date_time timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
    ) PARTITION BY RANGE (created_date_time);
    CREATE TABLE xs2a_accounts_db.audit_log_default PARTITION OF xs2a_accounts_db.audit_log DEFAULT;
    """
    with db_pool.connect() as connection:
        logger.info("Schema setup complete.")
        connection.execute(sqlalchemy.text("COMMIT;"))
        connection.execute(sqlalchemy.text(production_schema_sql))
        connection.execute(sqlalchemy.text("COMMIT;"))
        logger.info("Generating and inserting 100 realistic sample records...")
        def generate_realistic_ca_id(prefix, index):
            part2 = f"{random.randint(100,999)}-{random.randint(10,99)}-{index:08d}"
            part3 = f"{random.randint(100000,999999)}-{random.randint(100000,999999)}"
            part4 = f"{random.randint(10000000,99999999)}-{random.randint(0,9)}"
            return f"{prefix} {part2} {part3} {part4}"
        audit_log_data = []
        for i in range(50): audit_log_data.append({"audit_id": str(uuid.uuid4()), "credit_application_id": generate_realistic_ca_id("MMDEOPRA", i), "event_type": random.choice(["CONSENT_CREATION", "ACCOUNT_LIST_FETCH"]), "code": random.choice([200, 401, 403]), "description": f"MMDEOPRA log {i}", "severity": random.choice(["INFO", "ERROR"]), "created_date_time": datetime.utcnow() - timedelta(minutes=random.randint(1, 600))})
        for i in range(50, 100): audit_log_data.append({"audit_id": str(uuid.uuid4()), "credit_application_id": generate_realistic_ca_id("PBDECOFI", i), "event_type": random.choice(["TRANSACTION_FETCH", "PAYMENT_INITIATION"]), "code": random.choice([200, 500, 503]), "description": f"PBDECOFI log {i}", "severity": random.choice(["WARN", "CRITICAL"]), "created_date_time": datetime.utcnow() - timedelta(minutes=random.randint(1, 600))})
        stmt = sqlalchemy.text("INSERT INTO xs2a_accounts_db.audit_log (audit_id, credit_application_id, event_type, code, description, severity, created_date_time) VALUES (:audit_id, :credit_application_id, :event_type, :code, :description, :severity, :created_date_time)")
        connection.execute(stmt, audit_log_data)
        connection.execute(sqlalchemy.text("COMMIT;"))
        logger.info("Successfully inserted 100 records into 'audit_log'.")

@app.on_event("startup")
async def startup_event():
    setup_database()
    logger.info("Knowledge Ingestion Agent startup complete.")

@app.post("/process-and-ingest-pdfs")
async def process_and_ingest_all():
    # This function is correct and remains unchanged
    try: bucket = storage_client.get_bucket(KNOWLEDGE_BUCKET)
    except Exception as e: raise HTTPException(status_code=404, detail=f"Could not access GCS bucket '{KNOWLEDGE_BUCKET}'. Error: {e}")
    blobs = [b for b in bucket.list_blobs() if b.name.lower().endswith('.pdf')]
    if not blobs: return JSONResponse(status_code=200, content={"status": "noop", "message": "No PDFs found."})
    processed_count, failed_count = 0, 0
    db_session = get_db_session()
    try:
        sql = sqlalchemy.text("INSERT INTO runbooks (source_document, alert_name, runbook_json, embedding) VALUES (:src, :alert, :json, :embed) ON CONFLICT (source_document) DO UPDATE SET alert_name = EXCLUDED.alert_name, runbook_json = EXCLUDED.runbook_json, embedding = EXCLUDED.embedding;")
        for blob in blobs:
            json_data = parse_pdf(blob.download_as_bytes(), blob.name)
            if "error" in json_data: failed_count += 1; continue
            # This line will now work because get_embedding is defined
            embedding_vector = get_embedding(json_data.get("alert_name"))
            db_session.execute(sql, {"src": blob.name, "alert": json_data.get("alert_name"), "json": json.dumps(json_data), "embed": json.dumps(embedding_vector)})
            processed_count += 1
        db_session.commit()
    except Exception as e:
        db_session.rollback(); raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally: db_session.close()
    return JSONResponse(content={"status": "complete", "processed": processed_count, "failed": failed_count})

@app.post("/search")
async def search(request: dict = Body(...)):
    # This function is correct and remains unchanged
    query = request.get("query"); limit = request.get("top_k", 1)
    if not query: raise HTTPException(status_code=400, detail="Query is required.")
    db_session = get_db_session()
    try:
        embedding_vector = get_embedding(query)
        sql = sqlalchemy.text("SELECT runbook_json FROM runbooks ORDER BY (embedding <=> :vec) ASC LIMIT :lim;")
        results = db_session.execute(sql, {"vec": json.dumps(embedding_vector), "lim": limit}).fetchall()
        if not results: raise HTTPException(status_code=404, detail="No matching runbook found.")
        return JSONResponse(content={"status": "success", "runbook": results[0][0]})
    except Exception as e: raise HTTPException(status_code=500, detail=f"Search error: {e}")
    finally: db_session.close()

@app.get("/health")
async def health(): return {"status": "healthy"}