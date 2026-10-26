# syntax=docker/dockerfile:1
FROM node:22-alpine AS frontend
WORKDIR /src
COPY webapp/package.json webapp/package-lock.json webapp/
COPY webapp/ webapp/
RUN mkdir -p predictor/web/static
WORKDIR /src/webapp
RUN npm ci && npm run build

FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml README.md LICENSE predict.py ./
COPY predictor/ ./predictor/
COPY .cursor/ ./.cursor/
COPY .analysis/MASTER.md ./.analysis/MASTER.md
COPY --from=frontend /src/predictor/web/static ./predictor/web/static/

RUN pip install --no-cache-dir -e ".[web]"

ENV PREDICTOR_HOST=0.0.0.0
ENV PORT=8765

EXPOSE 8765

CMD ["sh", "-c", "exec python -m predictor.web.app"]
