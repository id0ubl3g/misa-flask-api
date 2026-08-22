from config.path_config import add_project_root_to_path
from dotenv import load_dotenv
from src.utils.system_utils import create_google_credentials
from src.api.app import Server

load_dotenv()
add_project_root_to_path()
create_google_credentials()

server = Server()
app = server.app

if __name__ == "__main__":
    server.run_production()