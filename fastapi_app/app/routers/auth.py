from typing import Annotated, Optional

from fastapi import Depends, APIRouter
from fastapi.requests import Request
from fastapi.responses import RedirectResponse, Response
from sqlmodel import Session

import sys

sys.path.append("..")  # Adds higher directory to python modules path.
from config import get_settings, get_keycloak_settings, Settings
from db import User, filter_users
from dependencies import check_auth, get_client, get_db_session, oidc, require_role

# Note: when using from ..config import moduleA, I got ImportError: attempted relative import beyond top-level package
# so the hack here is to use sys.path.append("..")

router = APIRouter()


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
          db_session: Session = Depends(get_db_session),
          redirect: Optional[str] = None):
    # sub = request.user_info['sub']
    name = request.user_info.get("name", "")
    email = request.user_info.get("email", "")
    role = request.user_info['realm_access']['roles']

    # get user by query
    user = filter_users(email, db_session)
    # register if not existent
    if not user:
        user = User(name=name,
                    email=email,
                    role=role,
                    # api_key=create_ontodocker_apikey(sub, name, email, role, request, settings)
                    )
        db_session.add(user)
        db_session.commit()
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
            # user.api_key = create_ontodocker_apikey(sub, name, email, role, request, settings)
            db_session.commit()
            db_session.refresh(user)
            print("Updated user:", user)

    request.session["email"] = user.email
    request.session["name"] = user.name
    request.session["role"] = user.role
    request.session["api_key"] = user.api_key

    if redirect:
        return RedirectResponse(url=redirect)
    else:
        return RedirectResponse(url="/")


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