FROM mcr.microsoft.com/playwright/python:v1.49.1-jammy

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV WEB_HOST=0.0.0.0
ENV HEADLESS=true
ENV BROWSER_MODE=launch

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium

COPY . .

RUN mkdir -p data credentials

EXPOSE 8080

CMD ["python", "main.py", "web"]
