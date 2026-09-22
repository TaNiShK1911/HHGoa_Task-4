import os
import sys
import logging
import pyTigerGraph as tg
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def run_gsql():
    logger.info("Connecting to TigerGraph...")
    try:
        conn = tg.TigerGraphConnection(
            host=os.environ["TIGERGRAPH_HOST"],
            username=os.environ.get("TIGERGRAPH_USERNAME", "tigergraph"),
            password=os.environ["TIGERGRAPH_PASSWORD"]
        )
        try:
            conn.getToken(conn.createSecret())
        except Exception:
            pass

        schema_path = os.path.join(os.path.dirname(__file__), "build_next_edges.gsql")
        
        with open(schema_path, "r") as f:
            gsql_script = f.read()

        logger.info("Executing build_next_edges.gsql (this may take a minute)...")
        results = conn.gsql(gsql_script)
        logger.info("Execution results:")
        print(results)

    except Exception as e:
        logger.error(f"Failed to execute GSQL: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_gsql()
