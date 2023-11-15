import os
import json
import datetime

from config import PATH

from log.main_logger import logger as log


# @deal.post(lambda x: type(x) is list)
def get_dirs() -> list:
    """
    Returns a sorted list of directories in the specified path, excl today's directory.

    Returns:
        A list of directory names (strings).
    """
    filedir_abs: str = PATH
    if os.path.isdir(filedir_abs):
        log.debug(
            f"Scanning {filedir_abs} for dirs except today's dir"
        )

        today_datetime: datetime.datetime = datetime.datetime.now(tz=datetime.UTC)
        today_formatted: str = datetime.datetime.strftime(today_datetime, "%Y%m%d")

        return sorted(
            [
                dir
                for dir in os.listdir(filedir_abs)
                if os.path.isdir(os.path.join(filedir_abs, dir))
                and dir != today_formatted
            ]
        )

    else:
        log.warning(
            f"Unable to scan {filedir_abs} for dirs except today's dir: dir does not exist"
        )
        return []


# @deal.post(lambda x: type(x) is list)
def get_h5_files(dir_path_r: str, last_filename: str | None = None) -> list[str]:
    """Returns h5 files for processing

    Args:
        path (str): Path to directory with h5 files
        last_file (str | None, optional): last processed file. Defaults to None.

    Returns:
        list: List relevant of h5 files in directory
    """
    try:
        file_names: list[str] = sorted(
            [
                os.path.join(PATH, dir_path_r, name)
                for name in os.listdir(os.path.join(PATH, dir_path_r))
                if name.endswith(".h5")
            ]
        )
        if last_filename is not None:
            try:
                file_names = file_names[file_names.index(last_filename) + 1 :]
            except ValueError:
                log.warning("File was not found in dir during indexing last filename")

        return sorted(file_names)
    except FileNotFoundError:
        log.warning(
            f"Unable to scan {dir_path_r} for h5 files: dir does not exist"
        )
        return []
    except ValueError:
        return []


# @deal.has("write")
def save_status(
    filedir_r: str,
    last_filename: str,
    last_filedir_r: str,
    start_chunk_time: float,
    processed_time: int,
):
    """
    Writes last processed file's name, total_unit_size and start_chunk_time
    to {date}/.last

    Args:
        filedir_r (str): relative PATH to working dir
        last_filename (str): last processed file's name
        last_filedir_r (str): last processed working dir
        start_chunk_time (float): time of the beginning of the first chunk
        processed_time (int): size of the last chunk including file's data
    """
    status_vars = json.dumps(
        {
            "last_filename": last_filename,
            "last_filedir": last_filedir_r,
            "start_chunk_time": start_chunk_time,
            "processed_time": processed_time,
        }
    )

    with open(
        os.path.join(PATH, filedir_r, ".last"), "w", encoding="UTF-8"
    ) as status_file:
        status_file.write(status_vars)
    if filedir_r != last_filedir_r:
        status_vars_n = json.dumps(
            {
                "last_filename": last_filename,
                "last_filedir": last_filedir_r,
            }
        )

        with open(
            os.path.join(PATH, last_filedir_r, ".last"), "w", encoding="UTF-8"
        ) as status_file:
            status_file.write(status_vars_n)


def get_queue(filepath_r: str):
    """
    Calculates files that are left to process in directory
    Also calculates several necessary vars to proceed with concat

    Args:
        filepath_r (str): absolute PATH to the working dir

    Returns:
        tuple: A tuple containing:
            - h5_files_list (list): A list of h5 files in the directory
            - start_chunk_time (float): The start time of the first chunk in the dir
            - processed_time (int): The total time processed so far
            - last_timestamp (int): The timestamp of the last file processed
    """

    def set_defaults(last_filename: str = None) -> tuple:
        """
        Sets default values for the variables used in get_queue

        Args:
            last_filename (str): The name of the last file processed

        Returns:
            tuple: A tuple containing:
                - h5_files_list (list): A list of h5 files in the directory
                - start_chunk_time (float): The start time of the chunk in the dir
                - processed_time (int): The total time processed so far
                - last_timestamp (int): The timestamp of the last file processed
        """
        h5_files_list: list[str] = get_h5_files(
            dir_path_r=filepath_r, last_filename=last_filename
        )

        if h5_files_list:
            start_chunk_time: float = float(
                h5_files_list[0].split("_")[-1].rsplit(".", 1)[0]
            )
        else:
            start_chunk_time = 0
        # Reset processed timer
        processed_time: int = 0
        last_timestamp: int = 0
        return (
            h5_files_list,
            start_chunk_time,
            processed_time,
            last_timestamp,
        )

    if os.path.isfile(os.path.join(PATH, filepath_r, ".last")):
        with open(
            os.path.join(PATH, filepath_r, ".last"), "r", encoding="UTF-8"
        ) as status_file:
            status_vars = json.load(status_file)
            last_filename = status_vars["last_filename"]
            last_filedir_r = status_vars["last_filedir"]

            if "start_chunk_time" in status_vars:
                start_chunk_time = status_vars["start_chunk_time"]
                processed_time = status_vars["processed_time"]

                file_names_tbd = get_h5_files(
                    dir_path_r=last_filedir_r,
                    last_filename=last_filename,
                )
                last_timestamp = float(
                    last_filename.split("_")[-1].rsplit(".", maxsplit=1)[0]
                )
                return (
                    file_names_tbd,
                    start_chunk_time,
                    processed_time,
                    last_timestamp,
                )
            else:
                return set_defaults(last_filename=last_filename)
    else:
        return set_defaults()


# @deal.post(lambda x: x is True)
def reset_chunks(file_dir_r: str) -> bool:
    """Deletes start_chunk_time and total_unit_size
    Used upon error (gap) in data to proceed after without exiting

    Args:
        path_dir (str): absolute PATH to working dir
    """

    log.info(
        f"Resetting chunk tracking to start from new chunk in {file_dir_r}"
    )
    status_filepath_r = os.path.join(PATH, file_dir_r, ".last")
    if os.path.isfile(status_filepath_r):
        with open(status_filepath_r, "r", encoding="UTF-8") as status_file:
            status_vars: dict = json.load(status_file)

        status_vars.pop("start_chunk_time", None)
        status_vars.pop("processed_time", None)

        with open(status_filepath_r, "w", encoding="UTF-8") as status_file:
            status_vars: dict = json.dump(status_vars, status_file)
    return True
