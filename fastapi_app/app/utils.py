from typing import Any
from fastapi.requests import Request


# https://medium.com/@arunksoman5678/fastapi-flash-message-like-flask-f0970605031a
def flash(request: Request, message: Any, category: str) -> None:
    if "_messages" not in request.session:
        request.session["_messages"] = []
    request.session["_messages"].append({"message": message, "category": category})


def get_flashed_messages(request: Request):
    return request.session.pop("_messages") if "_messages" in request.session else []


allowed_extensions = ['ttl', 'rdf']  # TODO 'trig' format may be needed for serializing named graphs


def is_file_allowed(filename):
    """To check if file extensions are allowed to upload"""
    if filename.rsplit('.', 1)[1].lower() in allowed_extensions:
        return True
    return False


def extract_queryresults(result):
    """Extract the header and the data that will be sent to the frontend as JSONResponse and create the table"""
    if "results" in result:  # when using SELECT, see https://www.w3.org/TR/sparql11-query/#select
        head = result.get("head", {"vars": []}).get("vars", [])
        bindings = result.get("results", {"bindings": []}).get("bindings", [])
        data = []
        for binding in bindings:
            result_line = []
            for var_name in head:
                value = binding.get(var_name, {}).get("value", "")
                result_line.append(value)
            data.append(result_line)
        return head, data
    else:  # when using ASK, see https://www.w3.org/TR/sparql11-query/#ask
        boolean_value = result["boolean"]
        print("boolean value:", boolean_value)
        return ["Boolean"], [[boolean_value]]
