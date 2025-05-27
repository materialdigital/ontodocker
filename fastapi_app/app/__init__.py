from fastapi.templating import Jinja2Templates
from sqlmodel import SQLModel, create_engine

from config import get_settings
from utils import get_flashed_messages
from triplestore.jena import get_jenaconn, FusekiConnection
import jpype
import os


filedir = os.path.dirname(os.path.realpath(__file__)) + "/"
jar_dir = filedir + "jars/"
jpype.startJVM(jpype.getDefaultJVMPath(),"-Dlog4j2.formatMsgNoLookups=true", **{"classpath" : jar_dir + "*"}, ignoreUnrecognized=True)

templates = Jinja2Templates(directory="templates")
templates.env.globals['get_flashed_messages'] = get_flashed_messages

setting = get_settings()

connect_args = {"check_same_thread": False}

engine = create_engine(setting.SQLALCHEMY_DATABASE_URI, echo=True, connect_args=connect_args)


# You can use echo=True to make the engine print all SQL statements it executes

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)
