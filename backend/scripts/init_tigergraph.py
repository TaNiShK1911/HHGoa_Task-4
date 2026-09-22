"""
Initialize TigerGraph Schema via REST API.
"""

import os
import sys
import logging
import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_schema():
    logger.info("Connecting to TigerGraph...")
    try:
        conn = tg.TigerGraphConnection(
            host=os.environ["TIGERGRAPH_HOST"],
            username=os.environ.get("TIGERGRAPH_USERNAME", "tigergraph"),
            password=os.environ["TIGERGRAPH_PASSWORD"]
        )
        # Auth token is usually required for DDL
        try:
            conn.getToken(conn.createSecret())
        except Exception as e:
            logger.warning(f"Could not get token (might be okay for DDL): {e}")

        schema_path = os.path.join(os.path.dirname(__file__), "..", "schema", "create_schema.gsql")
        
        with open(schema_path, "r") as f:
            gsql_script = f.read()

        logger.info("Executing schema DDL (this may take a minute)...")
        # Run the GSQL script
        results = conn.gsql(gsql_script)
        logger.info("Schema execution results:")
        print(results)

    except Exception as e:
        logger.error(f"Failed to initialize schema: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_schema()
