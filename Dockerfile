FROM python:3.10-slim
WORKDIR /app
COPY ./requirements.txt .
RUN pip install -r requirements.txt

USER 1000:1000
COPY ./src/ .
CMD ["python", "main.py"]
