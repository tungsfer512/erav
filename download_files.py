import json
import os
import requests
import pandas as pd

CHECKPOINT_FILE = "erav/progress.log"


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


def download_files(url, output_path):
    response = requests.get(url)
    if response.status_code == 200:
        with open(output_path, "wb") as f:
            f.write(response.content)
    else:
        print(f"Failed to download data. Status code: {response.status_code}")


with open("erav/details.json", "r") as f:
    details = json.load(f)

leng = len(details)
done = load_checkpoint()
if done > 0:
    print(f"Tiếp tục từ item {done + 1}/{leng} (đã bỏ qua {done} item đã tải)")

for index, item in enumerate(details, start=1):
    if index <= done:
        continue
    folder = (
        "erav/files/"
        + (
            str(item["Ngành nghề kinh doanh hiện tại"]).lower().replace("/", "_")
            if (
                item["Ngành nghề kinh doanh hiện tại"] is not None
                and item["Ngành nghề kinh doanh hiện tại"].strip() != ""
            )
            else "Chưa có ngành nghề kinh doanh hiện tại"
        )
        + "/"
        + str(item["Số giấy phép"]).strip().replace("/", "_")
        + "--"
        + str(item["Ngày cấp phép"]).strip().replace("/", "_")
    ).strip()
    if not os.path.exists(folder):
        os.makedirs(folder)
    df = pd.DataFrame(item["files"])
    df.index += 1
    df.to_excel(folder + "/link.xlsx", index=True, index_label="STT")
    for file in item["files"]:
        file_name = file["Đường dẫn"].split("/")[-1]
        url = file["Đường dẫn"]
        output_path = folder + "/" + file_name
        download_files(url, output_path)
    save_checkpoint(index)
    print(f"Đã tải xong {index}/{leng} files")
