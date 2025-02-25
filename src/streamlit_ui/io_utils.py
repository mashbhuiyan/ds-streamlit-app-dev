import hashlib
import os


def md5_hash(file_path: str) -> str | None:
    if not os.path.isfile(file_path):
        return None

    with open(file_path, "rb") as f:
        file_hash = hashlib.md5()
        while chunk := f.read(8192):
            file_hash.update(chunk)

    return file_hash.hexdigest()
