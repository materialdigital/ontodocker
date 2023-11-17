import os
from datetime import datetime, timedelta
from typing import Annotated, Optional

import httpx
import jwt
from fastapi import Depends, APIRouter
from fastapi.requests import Request
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session

import sys

sys.path.append("..")  # Adds higher directory to python modules path.
from config import get_settings, get_keycloak_settings, Settings
from db import User, filter_users
from dependencies import check_auth, get_client, get_session, oidc, require_role

# Note: when using from ..config import moduleA, I got ImportError: attempted relative import beyond top-level package
# so the hack here is to use sys.path.append("..")

router = APIRouter()


def create_ontodocker_apikey(sub: str, name: str, email: str, role: list, request: Request,
                             settings: Annotated[Settings, Depends(get_settings)]):
    issued_at = datetime.now()
    expires_at = issued_at + timedelta(days=settings.JWT_DAYS_VALID)
    claim_set = {
        "iss": "GlasDigital",  # Identifier (or, name) of the server or system issuing the token
        "iat": issued_at.timestamp(),  # Date/time when the token was issued
        "exp": expires_at.timestamp(),  # Date/time at which point the token is no longer valid
        "aud": request.client.host,  # The Intended recipient of this token is its own_url
        "sub": sub,  # Identifier (or, name) of the user this token represents
        "name": name,  # The full name of the user
        "email": email,  # The email address of the user
        "role": role  # The role of the user
    }
    encoded_jwt = jwt.encode(payload=claim_set,
                             key=settings.JWT_SECRET_KEY,
                             algorithm='HS256')
    return encoded_jwt


async def create_keycloak_apikey(keycloak_settings: Annotated[Settings, Depends(get_keycloak_settings)],
                                 client: httpx.AsyncClient = Depends(get_client)):
    data = {
        "client_id": keycloak_settings.client_id,
        "grant_type": "client_credentials",
        "client_secret": keycloak_settings.client_secret
    }

    response = await client.post(keycloak_settings.token_uri,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"},
                                 data=data)


    if response.status_code == 200:
        return response.json()['access_token']
    else:
        return {"status_code": response.status_code, "reason_phrase": response.reason_phrase}


@router.get("/login",
            description="Login via username/password in Homepage.<br>"
                        "Note: You cannot try it in the document, but only via the "
                        "<a href='/'>Homepage</a>.",
            summary="Login",
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
            )
@oidc.require_login
@require_role()
def login(request: Request, settings: Annotated[Settings, Depends(get_settings)],
          session: Session = Depends(get_session),
          redirect: Optional[str] = None):
    sub = request.user_info['sub']
    name = request.user_info['name']
    email = request.user_info['email']
    role = request.user_info['realm_access']['roles']

    # get user by query
    user = filter_users(email, session)
    # register if not existent
    if not user:
        user = User(name=name,
                    email=email,
                    role=role,
                    api_key=create_ontodocker_apikey(sub, name, email, role, request, settings)
                    )
        session.add(user)
        session.commit()
    else:
        # check for possible updates of user info
        # could add logic to auto-renew apikey if expired # TODO
        attribute_changed = False
        if user.name != name:
            user.name = name
            attribute_changed = True
        if user.email != email:
            user.email = email
            attribute_changed = True
        if user.role != role:
            user.role = role
            attribute_changed = True

        if attribute_changed:
            user.api_key = create_ontodocker_apikey(sub, name, email, role, request, settings)
            session.commit()
            session.refresh(user)
            print("Updated user:", user)

    request.session["email"] = user.email
    request.session["name"] = user.name
    request.session["role"] = user.role
    request.session["api_key"] = user.api_key

    if redirect:
        return RedirectResponse(url=redirect)
    else:
        return RedirectResponse(url="/project")


@router.get("/logout",
            description="Logout.<br>"
                        "Note: You cannot try it in the document, but only via the <a href='/'>Website</a>.",
            summary="Logout",
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
            )
def logout(request: Request, response: Response) -> RedirectResponse:
    # Clear session
    request.session.clear()
    # redirect to logout page
    return oidc.logout(request)