import json
import os
import requests
import pandas as pd
from datetime import datetime

CHECKPOINT_FILE = "erav/progress.log"
ERROR_LOG_FILE = "erav/error.log"
# Giới hạn an toàn cho 1 thành phần đường dẫn (NAME_MAX thường = 255 byte).
# Tiếng Việt là UTF-8 đa byte nên dùng byte length, chừa biên an toàn.
MAX_COMPONENT_BYTES = 200


def load_checkpoint():
    """Đọc index item cuối cùng đã tải xong (0 nếu chưa có)."""
    if not os.path.exists(CHECKPOINT_FILE):
        return 0
    try:
        with open(CHECKPOINT_FILE, "r") as f:
            return int(f.read().strip() or 0)
    except (ValueError, OSError):
        return 0


def save_checkpoint(index):
    """Ghi lại index item đã tải xong."""
    with open(CHECKPOINT_FILE, "w") as f:
        f.write(str(index))


def log_error(message):
    """In ra màn hình và ghi lỗi (kèm thời gian) vào file log để xem lại sau."""
    line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
    print(line, flush=True)
    with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def industry_folder(item):
    """Tên thư mục ngành nghề; nếu rỗng -> 'Chưa có...', nếu quá dài -> 'Others'."""
    name = item["Ngành nghề kinh doanh hiện tại"]
    if name is None or name.strip() == "":
        return "Chưa có ngành nghề kinh doanh hiện tại"
    name = name.lower().replace("/", "_")
    if len(name.encode("utf-8")) > MAX_COMPONENT_BYTES:
        return "Others"
    return name


def download_files(url, output_path):
    try:
        response = requests.get(url, timeout=60)
    except requests.RequestException as e:
        log_error(f"Lỗi request khi tải {url}: {e}")
        return
    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
    else:
        log_error(f"Tải thất bại (status {response.status_code}): {url}")


with open("erav/details.json", "r") as f:
    details = json.load(f)

leng = len(details)
done = load_checkpoint()
if done > 0:
    print(f"Tiếp tục từ item {done + 1}/{leng} (đã bỏ qua {done} item đã tải)", flush=True)

for index, item in enumerate(details, start=1):
    if index <= done:
        continue
    doc_id = item.get("_DocId")
    try:
        folder = (
            "erav/files/"
            + industry_folder(item)
            + "/"
            + str(item["Số giấy phép"]).strip().replace("/", "_")
            + "--"
            + str(item["Ngày cấp phép"]).strip().replace("/", "_")
        ).strip()
        if not os.path.exists(folder):
            os.makedirs(folder)
        df = pd.DataFrame(item["files"])
        df.index += 1
        df.to_excel(folder + f"/{doc_id}.xlsx", index=True, index_label="STT")
        for file in item["files"]:
            file_name = file["Đường dẫn"].split("/")[-1]
            url = file["Đường dẫn"]
            output_path = folder + "/" + file_name
            download_files(url, output_path)
        save_checkpoint(index)
        print(f"Đã tải xong {index}/{leng} files (docId={doc_id})", flush=True)
    except Exception as e:
        log_error(f"LỖI tại item {index}/{leng} (docId={doc_id}): {e}")
