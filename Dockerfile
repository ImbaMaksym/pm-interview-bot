FROM python:3.11-slim

WORKDIR /app

# dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# app
COPY . .

CMD ["python", "bot.py"]
