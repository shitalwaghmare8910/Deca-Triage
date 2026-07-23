# src/common/db_connection.py
import os
from dotenv import load_dotenv
import sqlalchemy
from google.cloud.sql.connector import Connector, IPTypes
# --- ACTION: Import 'sessionmaker' directly from the 'orm' module ---
from sqlalchemy.orm import sessionmaker

load_dotenv()
INSTANCE_CONNECTION_NAME = os.environ["INSTANCE_CONNECTION_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASS = os.environ["DB_PASS"]
DB_NAME = os.environ["DB_NAME"]
connector = Connector()

def getconn():
    return connector.connect(
        INSTANCE_CONNECTION_NAME, "pg8000", user=DB_USER,
        password=DB_PASS, db=DB_NAME, ip_type=IPTypes.PSC
    )

db_pool = sqlalchemy.create_engine("postgresql+pg8000://", creator=getconn)

# --- ACTION: Use the imported sessionmaker ---
# OLD, DEPRECATED WAY:
# Session = sqlalchemy.orm.sessionmaker(bind=db_pool)

# NEW, CORRECT WAY:
Session = sessionmaker(bind=db_pool)

def get_db_session():
    # This now correctly uses the Session factory we created
    return Session()