FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY gep ./gep
RUN pip install --no-cache-dir .
ENTRYPOINT ["python", "-m", "gep"]
