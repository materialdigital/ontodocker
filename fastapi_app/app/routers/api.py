import json
from typing import Annotated

import httpx
from fastapi import APIRouter, Query, UploadFile, File, Depends, Path, HTTPException
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import create_model, BaseModel

from .auth import create_keycloak_apikey

from triplestore.jena import get_jenaconn, FusekiConnection
from dependencies import check_auth, get_client, admin_required
from config import get_settings, get_keycloak_settings, Settings

# Note: when using from ..config import moduleA, I got ImportError: attempted relative import beyond top-level package
# so the hack here is just remove .. but then IDE will show Unresolved reference (Application startup will be fine)

router = APIRouter()


@router.post("/login",
             description="Grant login access to application via API key.<br>"
                         "Note: Enter the API key on the right side first!",
             summary="Grant login access to application via API key",
             )
async def api_login(keycloak_settings: Annotated[Settings, Depends(get_keycloak_settings)],
                    client: httpx.AsyncClient = Depends(get_client)):
    response = await create_keycloak_apikey(keycloak_settings, client)
    if "status_code" in response:  # if error occurs
        return JSONResponse(content={"error": response["reason_phrase"]}, status_code=response["status_code"])

    return JSONResponse(content={"msg": "API key is valid", "jwt": response}, status_code=200)


@router.get("/ds/all",
            description="Get all datasets in Fuseki Jena via API",
            summary="Get all datasets in Fuseki Jena via API",
            )
async def ds_all(client: httpx.AsyncClient = Depends(get_client)):
    return JSONResponse(content={"fuseki": await FusekiConnection.get_all_tdb_ids(client)})


@router.post("/jena/{tdb_id}/create",
             description="Create new datasets in Fuseki Jena via API",
             summary="Create new datasets in Fuseki Jena via API",
             )
async def create_jena(admin: Annotated[bool, Depends(admin_required)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client)):
    if admin:
        r = await get_jenaconn(tdb_id).create_ds(client)
        if r.status_code == 200:
            return JSONResponse(content=f"Dataset name {tdb_id} created", status_code=200)
        else:
            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content="Access forbidden", status_code=403)


@router.post('/jena/{tdb_id}/destroy',
             description="Destroy datasets in Fuseki Jena via API",
             summary="Destroy datasets in Fuseki Jena via API",
             )
async def destroy_jena(admin: Annotated[bool, Depends(admin_required)],
                       tdb_id: str = Path(..., description="The dataset name"),
                       client: httpx.AsyncClient = Depends(get_client)):
    if admin:
        r = await get_jenaconn(tdb_id).destroy_ds(client)
        if r.status_code == 200:
            return JSONResponse(content=f"Dataset name {tdb_id} destroyed", status_code=200)
        else:
            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content="Access forbidden", status_code=403)


@router.post("/jena/{tdb_id}/sparql",
             description="You can query the data with the name of the dataset and the SPARQL query parameter.",
             summary="Query datasets in Fuseki Jena via API",
             )
async def sparql_jena(request: Request, tdb_id: str = Path(..., description="The dataset name"),
                      query: str = Query("SELECT * WHERE {?sub ?pred ?obj .} LIMIT 10"),
                      client: httpx.AsyncClient = Depends(get_client),
                      ):
    r = await get_jenaconn(tdb_id).query(query, client)
    if r.status_code == 200:
        return JSONResponse(content=r.json(), status_code=200)
    else:
        return JSONResponse(content=r.text, status_code=r.status_code)


@router.post("/jena/{tdb_id}/update",
             description="Update datasets in Fuseki Jena via API",
             summary="Update datasets in Fuseki Jena via API",
             )
async def update_jena(request: Request,
                      admin: Annotated[bool, Depends(admin_required)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      update: str = Query(),
                      client: httpx.AsyncClient = Depends(get_client)):
    if admin:
        r = await get_jenaconn(tdb_id).update(update, client)
        if r.status_code == 204 or r.status_code == 200:
            return JSONResponse(content="Update succeeded", status_code=200)
        if r.status_code != 200:
            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content="Access forbidden", status_code=403)


@router.post("/jena/{tdb_id}/upload",
             description="Upload RDF data (.rdf or .ttl) to Fuseki Jena via API",
             summary="Upload RDF data (.rdf or .ttl) to Fuseki Jena via API",
             )
async def upload_jena(request: Request,
                      admin: Annotated[bool, Depends(admin_required)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      file: UploadFile = File(...),
                      client: httpx.AsyncClient = Depends(get_client)):
    if admin:
        # overwrite content-type since content-type of .ttl file is not recognized as "text/turtle"
        file_extension = file.filename.rsplit('.', 1)[1].lower()
        if file_extension == "ttl":
            content_type = "text/turtle"
        elif file_extension == "rdf":
            content_type = "application/rdf+xml"
        else:
            return JSONResponse(content={"message": "Invalid content-type"}, status_code=400)

        data = await file.read()

        endpoint = get_jenaconn(tdb_id).endpoint + "/data"
        headers = {"Content-Type": content_type}

        r = await client.post(endpoint, headers=headers, content=data)
        if r.status_code == 200:
            return JSONResponse(content="Upload succeeded " + r.content.decode("utf-8"), status_code=r.status_code)
        else:
            return JSONResponse(content="Error " + r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content="Access forbidden", status_code=403)

