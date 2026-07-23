# cloud_sql_inspector.py
# A simple, clear script to connect to Cloud SQL and display the schemas and tables.

import os
from sqlalchemy import create_engine, text
from google.cloud.sql.connector import Connector, IPTypes

# ==============================================================================
# --- ACTION: Fill in your actual database credentials here ---
# ==============================================================================
INSTANCE_CONNECTION_NAME = "db-dev-a7km-mp-aiw-pb-tech:europe-west3:database"  # e.g., "my-project:us-central1:my-instance"
DB_USER = "master"                  # e.g., "postgres"
DB_PASS = "376g9b5M2RHUUgiOkU"              # Your database password
DB_NAME = "database"                  # e.g., "postgres"
# ==============================================================================

def main():
    """Connects to the database and prints a clear report of its contents."""
    
    try:
        # Use a context manager to handle the connector lifecycle
        with Connector() as connector:
            # Function to create a connection using the private IP
            def getconn():
                return connector.connect(
                    INSTANCE_CONNECTION_NAME,
                    "pg8000",
                    user=DB_USER,
                    password=DB_PASS,
                    db=DB_NAME,
                    ip_type=IPTypes.PSC,  # Use Private IP for secure connection
                )

            # Create the SQLAlchemy engine
            pool = create_engine("postgresql+pg8000://", creator=getconn)

            # Connect and start the verification
            with pool.connect() as connection:
                
                # --- 1. Display Connection Success ---
                print("\n✅ Result: You are connected to the Cloud SQL instance- DEV AI Triage GCP Project.")
                print(f"   Instance: {INSTANCE_CONNECTION_NAME}")
                print(f"   Database: {DB_NAME}\n")
                
                # --- 2. Display Schemas ---
                schema_query = text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast') "
                    "AND schema_name NOT LIKE 'pg_temp_%' AND schema_name NOT LIKE 'pg_toast_temp_%';"
                )
                schemas = connection.execute(schema_query).fetchall()
                
                print("--- These are the schemas created in your database: ---")
                if not schemas:
                    print("   No custom schemas found.")
                else:
                    for (schema_name,) in schemas:
                        print(f"  - {schema_name}")
                
                print("\n--- These are the tables created within each schema: ---")
                # --- 3. Display Tables within Each Schema ---
                for (schema_name,) in schemas:
                    print(f"\n  In schema '{schema_name}':")
                    table_query = text(
                        "SELECT table_name FROM information_schema.tables WHERE table_schema = :schema"
                    )
                    tables = connection.execute(table_query, {"schema": schema_name}).fetchall()
                    
                    if not tables:
                        print("    (No tables found)")
                    else:
                        for (table_name,) in tables:
                            print(f"    - {table_name}")
                            
    except Exception as e:
        print(f"\n❌ An error occurred during verification: {e}")
    
    print("\nVerification script finished.\n")

if __name__ == "__main__":
    main()