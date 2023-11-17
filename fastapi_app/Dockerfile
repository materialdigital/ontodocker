FROM tiangolo/uvicorn-gunicorn-fastapi:python3.11

COPY ./requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt
#RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

COPY ./app /app
