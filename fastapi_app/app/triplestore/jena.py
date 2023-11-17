import base64
import json
import os
import sys
from functools import lru_cache
from typing import Optional, List

from fastapi.responses import JSONResponse

from pydantic import BaseSettings
from .misc import upload_onto

sys.path.append("..")  # Adds higher directory to python modules path.
from config import FusekiSettings, get_fuseki_settings

filename = os.path.basename(__file__)
filedir = os.path.dirname(os.path.realpath(__file__)) + "/"


class FusekiConnection():
    _url = f'http://fuseki:3030'

    # this is Fuseki UI admin credentials, required when using secoresearch/fuseki
    credentials = get_fuseki_settings().credentials
    encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')
    # print(f"{credentials.encode('utf-8') = }")
    # print(f"{base64.b64encode(credentials.encode('utf-8')) = }")
    # print(f"{encoded_credentials = }")
    _header = {"Authorization": f"Basic {encoded_credentials}"}

    def __init__(self, tdb_id):
        self.tdb_id = tdb_id
        self.endpoint = f'{self._url}/{tdb_id}'
        self.server = f'{self.endpoint}/sparql'
        # TODO Note: default dataset "ds" of secoresearch/fuseki, doesn't contain "/query" endpoint
        self.upserver = f'{self.endpoint}/update'

    @staticmethod
    async def get_server_status(client):
        return await client.get(f'{FusekiConnection._url}/$/server', headers=FusekiConnection._header)


    @staticmethod
    async def get_all_tdb_ids(client):
        r = await client.get(f'{FusekiConnection._url}/$/server', headers=FusekiConnection._header)
        # print(f"{r.status_code = }")
        if r.status_code == 200:
            rcontent = str(r.content.decode("utf-8"))
            lst = json.loads(rcontent).get("datasets", {})
            tbds = []
            for l in lst:
                tbds.append(
                    l["ds.name"][1:] if l["ds.name"][0] == "/" else l["ds.name"]
                )  # cut of leading backslash

            return tbds
        else:
            # print(f"\n###{r.text = }\n###\n")
            # print(f"\n###{r.content.decode('utf-8') = }\n###\n")
            return None

    async def create_ds(self, client):
        # https://stackoverflow.com/q/42421915
        return await client.post(f'{self._url}/$/datasets', params={"dbName": self.tdb_id, "dbType": "tdb2"},
                                 headers=FusekiConnection._header)

    async def destroy_ds(self, client):
        return await client.delete(f'{self._url}/$/datasets/{self.tdb_id}', headers=FusekiConnection._header)

    async def query(self, query, client):
        return await client.post(self.server, params={"query": query}, headers=FusekiConnection._header)

    async def update(self, update_query, client):  # TODO ERROR when using stain/jena-fuseki:4.0.0
        return await client.post(self.upserver, data={"update": update_query}, headers=FusekiConnection._header)

    async def upload(self, path_to_onto, client):
        print(f"\n####\n{path_to_onto = }\n####\n")
        return await upload_onto(f'{self.endpoint}/data', path_to_onto, client, headers=FusekiConnection._header)


def get_jenaconn(tdb_id):
    return FusekiConnection(tdb_id)


class FusekiDataset(BaseSettings):
    tbds: Optional[List[str]] = None


@lru_cache()
def get_fusekidataset():
    return FusekiDataset()
