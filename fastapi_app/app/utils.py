from typing import Any
from fastapi.requests import Request
from rdflib import Graph


# https://medium.com/@arunksoman5678/fastapi-flash-message-like-flask-f0970605031a
def flash(request: Request, message: Any, category: str) -> None:
    if "_messages" not in request.session:
        request.session["_messages"] = []
    request.session["_messages"].append({"message": message, "category": category})


def get_flashed_messages(request: Request):
    return request.session.pop("_messages") if "_messages" in request.session else []


allowed_extensions = ['ttl', 'rdf', 'trig']


def is_file_allowed(filename):
    """To check if file extensions are allowed to upload"""
    if filename.rsplit('.', 1)[1].lower() in allowed_extensions:
        return True
    return False


def extract_queryresults(result):
    if result is None:
        return [], [], None
    try:
        result_json = result.json()
        """Extract the header and the data that will be sent to the frontend as JSONResponse and create the table"""
        if "results" in result_json:  # when using SELECT, see https://www.w3.org/TR/sparql11-query/#select
            head = result_json.get("head", {"vars": []}).get("vars", [])
            bindings = result_json.get("results", {"bindings": []}).get("bindings", [])
            data = []
            for binding in bindings:
                result_line = []
                for var_name in head:
                    value = binding.get(var_name, {}).get("value", "")
                    result_line.append(value)
                data.append(result_line)
            return head, data, None
        else:  # when using ASK, see https://www.w3.org/TR/sparql11-query/#ask
            boolean_value = result_json["boolean"]
            print("boolean value:", boolean_value)
            return ["Boolean"], [[boolean_value]], None
    except Exception as e:
        g = Graph()
        g.parse(data=result.content, format="turtle")

        q = "SELECT DISTINCT * WHERE { ?subject ?predicate ?object . }"
        res = g.query(q)
        data = []
        for r in list(res):
            print(r)
            objectIdx = r.labels.get("object", 0)
            subjectIdx = r.labels.get("subject", 1)
            predicateIdx = r.labels.get("predicate", 2)
            data.append([r[subjectIdx], r[predicateIdx], r[objectIdx]])

        return ['subject', 'predicate', 'object'], data, result.content.decode("utf-8")
