FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.lock .
RUN --mount=type=secret,id=build_ca,required=false if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; pip install -r requirements.lock && useradd --create-home --uid 10001 agriscan && mkdir -p /data/images && chown -R agriscan /data
COPY --chown=agriscan . .
USER agriscan
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
