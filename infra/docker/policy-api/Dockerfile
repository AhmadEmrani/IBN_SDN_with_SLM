FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/service
WORKDIR /service
COPY policy-manager/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --timeout 120 --retries 8 -r requirements.txt
COPY policy-manager/app ./app
COPY policy-manager/alembic.ini ./alembic.ini
COPY policy-manager/alembic ./alembic
COPY policy-manager/tests ./tests
COPY policy-manager/scripts ./scripts
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
