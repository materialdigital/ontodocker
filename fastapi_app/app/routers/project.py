from fastapi import APIRouter
from fastapi.requests import Request
from fastapi.responses import Response
import sys

sys.path.append("..")  # Adds higher directory to python modules path.
from __init__ import templates

# Note: when using from ..config import moduleA, I got ImportError: attempted relative import beyond top-level package
# so the hack here is to use sys.path.append("..")

router = APIRouter()


@router.get("/project",
            description="Choose Project.<br>"
                        "Visit <a href='/project'>Project Choose Page</a>.",
            summary="Choose Project",
            include_in_schema=False  # hide this endpoint in Swagger UI (http://localhost/docs)
            )
async def project(response: Response, request: Request):
    return templates.TemplateResponse("projects.html", {"request": request
                                                        })
