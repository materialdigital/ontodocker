from typing import Optional, List

from fastapi import Depends
from sqlmodel import Field, Session, SQLModel, select, JSON, Column

from dependencies import get_session


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(index=True)
    role: List[str] = Field(sa_column=Column(JSON))
    api_key: str


def filter_users(email, session: Session = Depends(get_session)):
    statement = select(User).where(User.email == email)
    user = session.exec(statement).first()
    return user
