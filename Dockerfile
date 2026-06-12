FROM python:3.12-slim

WORKDIR /app

# Cài dependencies trước để tận dụng cache layer
COPY requirements.txt ./erav/requirements.txt
RUN pip install --no-cache-dir -r erav/requirements.txt

# Copy source. Script tham chiếu đường dẫn "erav/..." nên đặt project
# trong thư mục con erav/ và chạy từ /app
COPY . ./erav/

# Chạy từ /app để "erav/details.json" và "erav/files/" khớp với code
CMD ["python", "erav/download_files.py"]
