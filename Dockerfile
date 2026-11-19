FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY proto proto
COPY scripts scripts
COPY app app
RUN sh scripts/gen_proto.sh
COPY tests tests
COPY eval eval
RUN useradd -r -u 10001 app && chown -R app /srv
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
