# src/agents/postgres-agent/agent.py
# DEFINITIVE "MANAGER DEMO" & ENVIRONMENT-AWARE VERSION

import os, json, logging
import sqlalchemy
from fastapi import FastAPI, HTTPException, Request
from google.cloud.sql.connector import Connector, IPTypes
from dotenv import load_dotenv # <--- 1. IMPORT THE LIBRARY

load_dotenv() # <--- 2. LOAD THE .ENV FILE

# --- Color formatting for demo logs ---
class C:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'

# --- Basic Setup ---
logging.basicConfig(level=logging.WARNING)
app = FastAPI(title="Postgres Agent (DEMO MODE)")

# --- Cloud SQL Connection ---
# --- 3. THIS LINE NOW WORKS CORRECTLY ---
INSTANCE_CONNECTION_NAME = os.environ.get("INSTANCE_CONNECTION_NAME", "")
DB_USER = os.environ.get("DB_USER", "")
DB_PASS = os.environ.get("DB_PASS", "")
DB_NAME = os.environ.get("DB_NAME", "")
db_pool = None

# THE REST OF THE FILE IS IDENTICAL TO THE PREVIOUS "DEMO MODE" VERSION AND IS CORRECT.
# NO OTHER CHANGES ARE NEEDED IN THIS FILE.

@app.on_event("startup")
def startup_event():
    global db_pool
    # This check provides a clear error if the .env file is missing or misconfigured.
    if not INSTANCE_CONNECTION_NAME:
        print(f"{C.RED}FATAL ERROR: INSTANCE_CONNECTION_NAME is not set. Please check your .env file.{C.END}")
        raise RuntimeError("INSTANCE_CONNECTION_NAME is not set.")
        
    print(f"{C.YELLOW}Attempting to connect to Cloud SQL instance: {INSTANCE_CONNECTION_NAME}{C.END}")
    connector = Connector()
    db_pool = sqlalchemy.create_engine(
        "postgresql+pg8000://",
        creator=lambda: connector.connect(
            INSTANCE_CONNECTION_NAME, "pg8000", user=DB_USER,
            password=DB_PASS, db=DB_NAME, ip_type=IPTypes.PSC,
        ),
    )
    print(f"{C.GREEN}Postgres Agent connected successfully to Cloud SQL.{C.END}")

@app.post("/execute-query")
async def handle_query(request: Request):
    try:
        data = await request.json()
        query = data.get("query")
        if not query:
            raise HTTPException(status_code=400, detail="Query cannot be empty.")

        print("\n" + "-"*60)
        print(f"{C.YELLOW}Received SQL query from Orchestrator:{C.END}")
        print(f"  {query}")
        
        with db_pool.connect() as conn:
            result_proxy = conn.execute(sqlalchemy.text(query))
            if result_proxy.returns_rows:
                results = [dict(row._mapping) for row in result_proxy]
                print(f"{C.GREEN}Query executed successfully. Returning {len(results)} rows.{C.END}")
                return {"status": "success", "data": results}
            else:
                print(f"{C.GREEN}Query executed successfully (e.g., UPDATE/INSERT). Rows affected: {result_proxy.rowcount}{C.END}")
                return {"status": "success", "rows_affected": result_proxy.rowcount}
                
    except Exception as e:
        print(f"{C.RED}Failed to execute query: {e}{C.END}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health(): return {"status": "healthy"}