FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# данные и отчёты монтируются снаружи: -v ./data:/app/data -v ./reports:/app/reports
VOLUME ["/app/data", "/app/reports"]
ENTRYPOINT ["job-agent"]
CMD ["demo"]
