FROM python:3.10

WORKDIR /app

COPY not_requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD [ "python3.10", "main.py"]