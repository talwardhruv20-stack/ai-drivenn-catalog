FROM python:3.11-slim

# Install C++ compiler for cpp_processor.cpp
RUN apt-get update && apt-get install -y \
    g++ \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Compile your C++ binary
RUN g++ -O3 cpp_processor.cpp -o cpp_processor

EXPOSE 8005

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8005"]