from typing import Optional, List

from sqlmodel import Field, SQLModel, select, JSON, Column
from sqlalchemy import or_


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True)
    role: List[str] = Field(sa_column=Column(JSON))
    api_key: str


def filter_users(email, session):
    statement = select(User).where(User.email == email)
    user = session.exec(statement).first()
    return user

class SparqlQuery(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
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