import json
import os
import gzip
from typing import Annotated

import httpx
from fastapi import APIRouter, UploadFile, File, Depends, Path, Response
from fastapi.requests import Request
from fastapi.responses import JSONResponse
from fastapi import Response as ResponseFastApi
import requests

from triplestore.jena import get_jenaconn, FusekiConnection
from dependencies import get_client, verify_readonly, verify_readwrite
from fastapi_jwt_auth import AuthJWT
#from fastapi_jwt_auth.exceptions import AuthJWTException

# Note: when using from ..config import moduleA, I got ImportError: attempted relative import beyond top-level package
# so the hack here is just remove .. but then IDE will show Unresolved reference (Application startup will be fine)
from werkzeug import Response

router = APIRouter()

@router.get("/endpoints",
            summary="Get all datasets in Ontodocker",
            responses={
                200: {
                    "description": "Successful response",
                    "content": {
                        "application/json": {
                            "example": [
                                "http://localhost:8000/api/jena/dataset1/sparql",
                                "http://localhost:8000/api/jena/dataset2/sparql"
                            ]
                        }
                    }
                },
                403: {
                    "description": "Authorization failure",
                    "content": {
                        "application/json": {
                            "example": "Minimum readonly API-Key required"
                        }
                    }
                }
            }
            )
async def ds_all(request: Request,
                 allowed: Annotated[bool, Depends(verify_readonly)],
                 client: httpx.AsyncClient = Depends(get_client),
                 authorize: AuthJWT = Depends(get_client)
                 ):
    """
    Get a list of SPARQL endpoints for all datasets.

    Args:
        request (Request): The incoming request object.
        allowed (bool): A boolean indicating whether the request is allowed.
        client (httpx.AsyncClient, optional): The HTTP client. Defaults to Depends(get_client).
        authorize (AuthJWT, optional): The authorization object. Defaults to Depends(get_client).

    Returns:
        JSONResponse: A JSON response containing a list of SPARQL endpoints for all datasets.
                     If the request is not allowed, returns a JSON response with a 403 status code.
    """
    if allowed:
        ownurl = f"{request.url.scheme}://{request.url.hostname}"
        if request.url.port != 443 and request.url.port != 80:
            ownurl = f"{request.url.scheme}://{request.url.hostname}:{request.url.port}"
        endpoint_list = [f"{ownurl}/api/jena/{fid}/sparql" for fid in await FusekiConnection.get_all_tdb_ids(client)]
        return JSONResponse(content=endpoint_list)
    return JSONResponse(content=str("Minimum readonly API-Key required"), status_code=403)




# DATA Endpoints
@router.get("/jena/{dataset_name}",
             description="Get all data in this dataset as Turtle File",
             summary="Download Turtle File for defined dataset",
             responses={
                200: {
                    "description": "Response with the Turtle File or Containing Error message in the body",
                    "content": {
                        "application/json": {
                            "example": "Error 404: Not Found"
                        },
                        "text/turtle": {
                            "example": "Turtle File Download Stream"
                        }
                    }
                },
                403: {
                    "description": "Authorization failure",
                    "content": {
                        "application/json": {
                            "example": "Minimum readonly API-Key required"
                        }
                    }
                }
            }
            )
async def download_jena(
                      allowed: Annotated[bool, Depends(verify_readonly)],
                      dataset_name: str = Path(..., description="The dataset name")):
    """
    Download the Jena dataset.

    Args:
        allowed (bool): A boolean value indicating whether the download is allowed.
        dataset_name (str): The name of the dataset.

    Returns:
        ResponseFastApi: The response containing the downloaded content in text/turtle format.

    Raises:
        JSONResponse: If the download is not allowed, returns a JSON response with a 403 status code.
    """
    if allowed:
        url = f'{get_jenaconn(dataset_name).endpoint}/data'
        r = requests.get(url, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", "")))
        return ResponseFastApi(content=r.content, media_type="text/turtle")
    
    return JSONResponse(content=str("Minimum readonly API-Key required"), status_code=403)


@router.post("/jena/{dataset_name}",
             summary="Upload RDF data (.rdf or .ttl) to Fuseki Jena",
             description="Upload RDF data (.rdf or .ttl) to Fuseki Jena",
             responses={
                200: {
                    "description": "Upload completed",
                    "content": {
                        "application/json": {
                            "example": "Error 404: Not Found"
                        },
                        "text/turtle": {
                            "example": "Turtle File Download Stream"
                        }
                    }
                },
                403: {
                    "description": "Authorization failure",
                    "content": {
                        "application/json": {
                            "example": "Minimum readwrite API-Key required"
                        }
                    }
                },
                400: {
                    "description": "Internal Error uploading the file",
                    "content": {
                        "application/json": {
                            "example": "Error 400: Invalid content-type"
                        }
                    }
                }
            }
             )
async def upload_jena(request: Request,
                      allowed: Annotated[bool, Depends(verify_readwrite)],
                      dataset_name: str = Path(..., description="The dataset name"),
                      file: UploadFile = File(...),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)):
    """
    Upload RDF data (.rdf or .ttl) to Fuseki Jena via API.

    Args:
        request (Request): The request object.
        allowed (bool): A boolean indicating if the user is allowed to upload data.
        dataset_name (str): The name of the dataset.
        file (UploadFile): The uploaded file.
        client (httpx.AsyncClient): The HTTP client.
        authorize (AuthJWT): The authorization object.

    Returns:
        JSONResponse: The response containing the upload status.

    Raises:
        JSONResponse: If the user is not allowed to upload data or if there is an error during the upload.
    """
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

        endpoint = get_jenaconn(dataset_name).endpoint + "/data"
        headers = {"Content-Type": content_type}

        r = requests.post(endpoint, headers=headers, data=data, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", ""))) 
        if r.status_code == 200:
            return JSONResponse(content="Upload succeeded " + r.content.decode("utf-8"), status_code=r.status_code)
        else:
            return JSONResponse(content="Error " + r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)


@router.put("/jena/{dataset_name}",
             summary="Create new datasets in Fuseki Jena via API",
             responses={
                200: {
                    "description": "Dataset created",
                    "content": {
                        "application/json": {
                            "example": "Dataset name abcdef created"
                        }
                    }
                },
                403: {
                    "description": "Authorization failure",
                    "content": {
                        "application/json": {
                            "example": "Minimum readwrite API-Key required"
                        }
                    }
                },
                400: {
                    "description": "Internal Error uploading the file",
                    "content": {
                        "application/json": {
                            "example": "Error 400: Invalid name"
                        }
                    }
                }
            }
             )
async def create_jena(allowed: Annotated[bool, Depends(verify_readwrite)],
                      dataset_name: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)):
    """
    Create a new dataset in Fuseki Jena via API.

    Args:
        allowed (bool): A boolean indicating if the user is allowed to create a dataset.
        dataset_name (str): The name of the dataset.
        client (httpx.AsyncClient): The HTTP client.
        authorize (AuthJWT): The authorization object.

    Returns:
        JSONResponse: The response containing the status of the dataset creation.

    Raises:
        JSONResponse: If the user is not allowed to create a dataset or if there is an error during the creation.
    """
    if allowed:
        r = await get_jenaconn(dataset_name).create_ds(client)
        if r.status_code == 200:
            return JSONResponse(content=f"Dataset name {dataset_name} created", status_code=200)
        else:
            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)


@router.delete('/jena/{dataset_name}',
             description="Destroy datasets in Fuseki Jena via API",
             summary="Destroy datasets in Fuseki Jena via API",
             responses={
                200: {
                    "description": "Dataset destroyed",
                    "content": {
                        "application/json": {
                            "example": "Dataset name abcdef destroyed"
                        }
                    }
                },
                403: {
                    "description": "Authorization failure",
                    "content": {
                        "application/json": {
                            "example": "Minimum readwrite API-Key required"
                        }
                    }
                }
            }
             )
async def destroy_jena(allowed: Annotated[bool, Depends(verify_readwrite)],
                       dataset_name: str = Path(..., description="The dataset name"),
                       client: httpx.AsyncClient = Depends(get_client),
                       authorize: AuthJWT = Depends(get_client)):
    """
    Destroy a dataset in Fuseki Jena via API.

    Args:
        allowed (bool): A boolean indicating if the user is allowed to destroy the dataset.
        dataset_name (str): The name of the dataset.
        client (httpx.AsyncClient): The HTTP client.
        authorize (AuthJWT): The authorization object.

    Returns:
        JSONResponse: The response containing the status of the dataset destruction.

    Raises:
        JSONResponse: If the user is not allowed to destroy the dataset or if there is an error during the destruction.
    """
    if allowed:
        r = await get_jenaconn(dataset_name).destroy_ds(client)
        if r.status_code == 200:
            return JSONResponse(content=f"Dataset name {dataset_name} destroyed", status_code=200)
        else:
            return JSONResponse(content=r.content.decode("utf-8"), status_code=r.status_code)
    else:
        return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)
    
# SPARQL endpoints
@router.get("/jena/{dataset_name}/sparql",
             description="Query the data with the name of the dataset and the SPARQL query parameter.",
             summary="Query datasets in Fuseki Jena",
             responses={
                200: {
                    "description": "Response with the SPARQL query results",
                    "content": {
                        "application/json": {
                            "example": {
                                "head":  [
                                        {
                                            "title": "Title Column 1"
                                        },
                                        {
                                            "title": "Title Column 2"
                                        },
                                        {
                                            "title": "Title Column 3"
                                        }
                                ],
                                "data": [
                                    ["Column 1 Value 1", "Column 2 Value 1", "Column 3 Value 1"],
                                    ["Column 1 Value 2", "Column 2 Value 2", "Column 3 Value 2"],
                                    ["Column 1 Value 3", "Column 2 Value 3", "Column 3 Value 3"]
                                ]
                            }
                        }
                    }
                },
                403: {
                    "description": "Authorization failure",
                    "content": {
                        "application/json": {
                            "example": "Minimum readonly API-Key required"
                        }
                    }
                }
            }
             )
async def sparql_jena(request: Request,
                      allowed: Annotated[bool, Depends(verify_readonly)],
                      dataset_name: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)
                      ):
    """
    Executes a SPARQL query on the Jena Fuseki server.

    Args:
        request (Request): The incoming HTTP request.
        allowed (bool): A boolean indicating if the user is allowed to query the dataset.
        dataset_name (str): The name of the dataset to query.
        client (httpx.AsyncClient): The HTTP client.
        authorize (AuthJWT): The authorization JWT.

    Returns:
        JSONResponse: The response containing the query results.
    """
    if allowed:
        url = f"http://fuseki:3030/{dataset_name}/sparql"
        resp = requests.get(url, headers=request.headers, params={"query":request.query_params["query"]}, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", "")))
        return JSONResponse(content=resp.json(), status_code=200)
    return JSONResponse(content=str("Minimum readonly API-Key required"), status_code=403)

@router.post("/jena/{dataset_name}/sparql",
             description="You can query the data with the name of the dataset and the SPARQL query parameter.",
             summary="Query datasets in Fuseki Jena with data update",
             responses={
                200: {
                    "description": "Jena Response of the SPARQL query",
                    "content": {
                        "application/json": {
                            "example": {
                                'r': '{ \n  "statusCode" : 200 ,\n  "message" : "Update succeeded"\n}\n'
                            }
                        }
                    }
                },
                403: {
                    "description": "Authorization failure",
                    "content": {
                        "application/json": {
                            "example": "Minimum readwrite API-Key required"
                        }
                    }
                }
            }
             )
async def sparql_jena(request: Request,
                      allowed: Annotated[bool, Depends(verify_readwrite)],
                      dataset_name: str = Path(..., description="The dataset name"),
                      client: httpx.AsyncClient = Depends(get_client),
                      authorize: AuthJWT = Depends(get_client)
                      ):
    """
    Endpoint to query datasets in Fuseki Jena.

    Args:
        request (Request): The incoming request object.
        allowed (bool): A boolean indicating if the user is allowed to make changing queries to the dataset.
        dataset_name (str): The name of the dataset to query.
        client (httpx.AsyncClient): The HTTP client.
        authorize (AuthJWT): The authorization object.

    Returns:
        JSONResponse: The response containing the query result or an error message.
    """
    if allowed:
        url = f"http://fuseki:3030/{dataset_name}/update"
        form_data = await request.form()
        resp = requests.post(url=url, headers=request.headers, data=form_data, auth=(os.environ.get("FUSEKI_ADMIN_USER", ""), os.environ.get("FUSEKI_ADMIN_PW", ""))).content.decode("utf-8")
        return JSONResponse({"r":resp}) #todo richtige Response bauen
    return JSONResponse(content=str("Minimum readwrite API-Key required"), status_code=403)
