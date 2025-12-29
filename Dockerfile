FROM python:3.11-slim

# Install system deps (LibreOffice for docx/pptx -> PDF conversion)
RUN apt-get update && \
    apt-get install -y libreoffice && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["uvicorn", "main:socket_app", "--host", "0.0.0.0", "--port", "10000"]

