import os
import shutil
from pathlib import Path
from typing import Callable


def filter_and(*filters):
    def and_test(path: Path):
        return all(filter(path) for filter in filters)

    return and_test


def filter_or(*filters):
    def and_test(path: Path):
        return any(filter(path) for filter in filters)

    return and_test


def filter_not(filter):
    def and_test(path: Path):
        return not filter(path)

    return and_test


def filter_name_end(name_end: str):
    def ends_with(path: Path):
        return os.path.splitext(path)[0].endswith(name_end)

    return ends_with


def filter_name_not_end(name_end: str):
    def ends_with(path: Path):
        return not os.path.splitext(path)[0].endswith(name_end)

    return ends_with


def copy_files(from_path: Path, to_path: Path, filter: Callable[[Path], bool] = None):
    for entry in from_path.iterdir():
        target_entry = to_path / entry.name
        if entry.name.startswith(".") or entry.name == "__MACOSX":
            continue
        elif entry.is_dir():
            if not target_entry.is_dir():
                target_entry.mkdir()
            copy_files(entry, target_entry, filter)
            if len(list(target_entry.iterdir())) == 0:
                target_entry.rmdir()
        else:
            if filter is None or filter(entry):
                shutil.copy(entry, target_entry)
