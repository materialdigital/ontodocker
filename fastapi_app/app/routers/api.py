import json
import os
from typing import Annotated

import httpx
from fastapi import APIRouter, Query, UploadFile, File, Depends, Path
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from pydantic import create_model, BaseModel
from fastapi import Response as ResponseFastApi
import requests
#from .auth import create_keycloak_apikey

from triplestore.jena import get_jenaconn, FusekiConnection
from dependencies import check_auth, get_client, verify_readonly, verify_readwrite, verify_admin
from config import get_settings, get_keycloak_settings, Settings
from fastapi_jwt_auth import AuthJWT
#from fastapi_jwt_auth.exceptions import AuthJWTException

# Note: when using from ..config import moduleA, I got ImportError: attempted relative import beyond top-level package
# so the hack here is just remove .. but then IDE will show Unresolved reference (Application startup will be fine)
from werkzeug import Response

router = APIRouter()


@router.get("/endpoints",
            description="Get all datasets in Fuseki Jena via API",
            summary="Get all datasets in Fuseki Jena via API",
            )
async def ds_all(request: Request,
                 allowed: Annotated[bool, Depends(verify_readonly)],
                 client: httpx.AsyncClient = Depends(get_client),
                 authorize: AuthJWT = Depends(get_client)
                 ):
    if allowed:
        ownurl = f"{request.url.scheme}://{request.url.hostname}"
        if request.url.port != 443 and request.url.port != 80:
            ownurl = f"{request.url.scheme}://{request.url.hostname}:{request.url.port}"
        endpoint_list = [f"{ownurl}/api/jena/{fid}/sparql" for fid in await FusekiConnection.get_all_tdb_ids(client)]
        return JSONResponse(content=endpoint_list)
    return JSONResponse(content=str("Minimum readonly API-Key required"), status_code=403)




# DATA Endpoints
@router.get("/jena/{tdb_id}",
             description="get all data as ttl",
             summary="Download Turtle",
            )
async def download_jena(
                      allowed: Annotated[bool, Depends(verify_readonly)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client),
                    #   authorize: AuthJWT = Depends(get_client)
                      ):
    if allowed:
        url = f'{get_jenaconn(tdb_id).endpoint}/data'
        r = requests.get(url, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", "")))
        return ResponseFastApi(content=r.content, media_type="text/turtle")
    
    return JSONResponse(content=str("Minimum readonly API-Key required"), status_code=403)


@router.post("/jena/{tdb_id}",
             description="Upload RDF data (.rdf or .ttl) to Fuseki Jena via API",
             summary="Upload RDF data (.rdf or .ttl) to Fuseki Jena via API",
             )
async def upload_jena(request: Request,
                      allowed: Annotated[bool, Depends(verify_readwrite)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      file: UploadFile = File(...),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)):
    if allowed:
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

        r = requests.post(endpoint, headers=headers, data=data, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", ""))) 
        if r.status_code == 200:
            return JSONResponse(content="Upload succeeded " + r.content.decode("utf-8"), status_code=r.status_code)
        else:
            return JSONResponse(content="Error " + r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)


@router.put("/jena/{tdb_id}",
             description="Create new datasets in Fuseki Jena via API",
             summary="Create new datasets in Fuseki Jena via API",
             )
async def create_jena(allowed: Annotated[bool, Depends(verify_readwrite)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)):
    if allowed:
        r = await get_jenaconn(tdb_id).create_ds(client)
        if r.status_code == 200:
            return JSONResponse(content=f"Dataset name {tdb_id} created", status_code=200)
        else:
            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)


@router.delete('/jena/{tdb_id}',
             description="Destroy datasets in Fuseki Jena via API",
             summary="Destroy datasets in Fuseki Jena via API",
             )
async def destroy_jena(allowed: Annotated[bool, Depends(verify_readwrite)],
                       tdb_id: str = Path(..., description="The dataset name"),
                       client: httpx.AsyncClient = Depends(get_client),
                       authorize: AuthJWT = Depends(get_client)):
    if allowed:
        r = await get_jenaconn(tdb_id).destroy_ds(client)
        if r.status_code == 200:
            return JSONResponse(content=f"Dataset name {tdb_id} destroyed", status_code=200)
        else:
            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)

# SPARQL endpoints
@router.get("/jena/{tdb_id}/sparql",
             description="You can query the data with the name of the dataset and the SPARQL query parameter.",
             summary="Query datasets in Fuseki Jena via API",
             )
async def sparql_jena(request: Request,
                      allowed: Annotated[bool, Depends(verify_readonly)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)
                      ):
    if allowed:
        url = f"http://fuseki:3030/{tdb_id}/sparql"
        resp = requests.get(url, headers=request.headers, params={"query":request.query_params["query"]}, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", "")))
        headers = {name : value for (name, value) in resp.raw.headers.items()}
        return JSONResponse(content=resp.json(), status_code=200, headers=headers)
    return JSONResponse(content=str("Minimum readonly API-Key required"), status_code=403)

@router.post("/jena/{tdb_id}/sparql",
             description="You can query the data with the name of the dataset and the SPARQL query parameter.",
             summary="Query datasets in Fuseki Jena via API",
             )
async def sparql_jena(request: Request,
                      allowed: Annotated[bool, Depends(verify_readwrite)],
                      tdb_id: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)
                      ):
    if allowed:
        url = f"http://fuseki:3030/{tdb_id}/update"
        form_data = await request.form()
        resp = requests.post(url=url, headers=request.headers, data=form_data, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", ""))).content.decode("utf-8")
        return JSONResponse({"r":str(resp)}) #todo richtige Response bauen
    return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)
