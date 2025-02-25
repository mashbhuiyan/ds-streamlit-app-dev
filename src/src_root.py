from pathlib import Path


def get_project_root():
    """
    Returns the absolute path of the project root directory.
    """
    current_file_path = Path(__file__).resolve()
    src_root_dir = current_file_path.parent
    return src_root_dir


src_root = get_project_root()

if __name__ == "__main__":
    print(src_root)
