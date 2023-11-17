from fastapi.templating import Jinja2Templates
from sqlmodel import SQLModel, create_engine

from config import get_settings
from utils import get_flashed_messages
from triplestore.jena import get_jenaconn, FusekiConnection

templates = Jinja2Templates(directory="templates")
templates.env.globals['get_flashed_messages'] = get_flashed_messages

setting = get_settings()

connect_args = {"check_same_thread": False}

engine = create_engine(setting.SQLALCHEMY_DATABASE_URI, echo=False, connect_args=connect_args)


# You can use echo=True to make the engine print all SQL statements it executes

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
