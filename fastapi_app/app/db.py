from typing import Optional, List

from sqlmodel import Field, SQLModel, select, JSON, Column


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
