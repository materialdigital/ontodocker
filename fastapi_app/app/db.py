from typing import Optional

from sqlmodel import Field, SQLModel, select
from sqlalchemy import or_

class BaseModel(SQLModel):
    id: Optional[int] = Field(default=None, nullable=False, primary_key=True)

class User(BaseModel, table=True):
    name: str
    user_identifier: str = Field(index=True, nullable=False)
    password: str = Field(default=None)
    role: str = Field(index=True, nullable=False)
    api_key: str = Field(default=None)
    sso_provider_id: int = Field(default=None)
    last_login_timestamp: int = Field(default=None)

def get_user_by_user_identifier(user_identifier, session):
    statement = select(User).where(User.user_identifier == user_identifier)
    user = session.exec(statement).first()
    return user

def get_user_by_id(id, session):
    statement = select(User).where(User.id == id)
    user = session.exec(statement).first()
    return user

def get_all_users_order_by_name(session):
    statement = select(User).order_by(User.name)
    users = session.exec(statement).all()
    return users

def get_user_by_sso_provider_and_user_identifier(sso_provider_id, user_identifier, session):
    statement = select(User).where(User.sso_provider_id == sso_provider_id).where(User.user_identifier == user_identifier)
    user = session.exec(statement).first()
    return user

def get_users_by_sso_provider_id(sso_provider_id, session):
    statement = select(User).where(User.sso_provider_id == sso_provider_id)
    users = session.exec(statement).all()
    return users

def get_db_version_or_init(session):
    statement = select(ApplicationStore).where(ApplicationStore.key == "db_version")
    app_version = session.exec(statement).first()
    if not app_version:
        app_version = ApplicationStore(key="db_version", value="0")
        session.add(app_version)
        session.commit()
    return int(app_version.value)

def get_application_store_by_key(session, key, default=None):
    statement = select(ApplicationStore).where(ApplicationStore.key == key)
    app_store = session.exec(statement).first()
    if not app_store:
        return default
    return app_store.value

def create_or_update_application_store_by(session, key, value):
    statement = select(ApplicationStore).where(ApplicationStore.key == key)
    app_store = session.exec(statement).first()
    if not app_store:
        app_store = ApplicationStore(key=key, value=value)
        session.add(app_store)
    else:
        app_store.value = value
    session.commit()
    return app_store
class ApplicationStore(BaseModel, table=True):
    key: str
    value: str

class SSOProvider(BaseModel, table=True):
    type: str
    name: str
    client_id: str
    client_secret: str
    server_metadata_url: str= Field(default=None)
    access_token_url: str = Field(default=None)
    access_token_params: str = Field(default=None)
    authorize_url: str = Field(default=None)
    authorize_params: str = Field(default=None)
    api_base_url: str = Field(default=None)
    scope: str = Field(default=None)
    enabled: bool= Field(default=False),
    new_user_role: str = Field(default=None)

def get_sso_provider_by_id(id, session):
    statement = select(SSOProvider).where(SSOProvider.id == id)
    sso_provider = session.exec(statement).first()
    return sso_provider

def get_sso_provider_by_name(name, session):
    statement = select(SSOProvider).where(SSOProvider.name == name)
    sso_provider = session.exec(statement).first()
    return sso_provider

def get_all_sso_providers(session):
    statement = select(SSOProvider)
    sso_providers = session.exec(statement).all()
    return sso_providers

def get_enabled_sso_providers(session):
    statement = select(SSOProvider).where(SSOProvider.enabled == True)
    sso_providers = session.exec(statement).all()
    return sso_providers

def get_sso_provider_by_name_and_enabled(name, session):
    statement = select(SSOProvider).where(SSOProvider.name == name).where(SSOProvider.enabled == True)
    sso_provider = session.exec(statement).first()
    return sso_provider

class SparqlQuery(BaseModel, table=True):
    query: str
    name: str
    user_id: int
    public: bool = False

def find_sparql_query_by_user_id_or_public(user_id, session):
    statement = select(SparqlQuery).where(or_(SparqlQuery.user_id == user_id, SparqlQuery.public == True)).order_by(SparqlQuery.name)
    sparql_query = session.exec(statement).all()
    return sparql_query

def find_sparql_query_by_user(user_id, session):
    statement = select(SparqlQuery).where(SparqlQuery.user_id == user_id).order_by(SparqlQuery.name)
    sparql_query = session.exec(statement).all()
    return sparql_query

def find_sparql_query_by_id(id, session):
    statement = select(SparqlQuery).where(SparqlQuery.id == id)
    sparql_query = session.exec(statement).first()
    return sparql_query

def find_all_sparql_query(session):
    statement = select(SparqlQuery)
    sparql_query = session.exec(statement).all()
    return sparql_query

class CkanDataset(BaseModel, table=True):
    dataset_name: str
    ckan_id: str
    user_id: int
    published_timestamp: int = Field(default=None)

def find_ckan_dataset_by_dataset_name(dataset_name, session):
    statement = select(CkanDataset).where(CkanDataset.dataset_name == dataset_name)
    ckan_dataset = session.exec(statement).first()
    return ckan_dataset