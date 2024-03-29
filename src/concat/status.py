import os
import json
import datetime
from uu import Error

import numpy as np
import pytz

from config import LOCAL_PATH, SAVE_PATH, SPS, CHUNK_SIZE

from log.main_logger import logger as log
from h5py import File, Dataset


class FileManager:
    def __init__(self, path: str = LOCAL_PATH, save_path: str = SAVE_PATH):
        self.path = path
        self.save_path = save_path

    def require_h5(self, chunk_time: float, space_samples: int) -> Dataset | None:
        """Creates/Checks h5 file

        Args:
            chunk_time (float): Time of the chunk

        Returns:
            h5py.Dataset: Returns dataset of the created/checked h5 file
        """

        # Calculation of the date in YYYYMMDD format
        # based on the chunk time provided in UNIX timestamp
        chunk_time = round(chunk_time, 0)
        save_date_dt = datetime.datetime.fromtimestamp(chunk_time, tz=pytz.UTC)
        save_date = datetime.datetime.strftime(save_date_dt, "%Y%m%d")
        save_year = datetime.datetime.strftime(save_date_dt, "%Y")
        filename = save_date + "_" + str(chunk_time) + ".h5"
        if not os.path.isdir(os.path.join(self.save_path, save_year, save_date)):
            os.makedirs(os.path.join(self.save_path, save_year, save_date))
        file = File(os.path.join(self.save_path, save_year, save_date, filename), "a")
        log.debug(f"Provided chunk time: {chunk_time}. File: {filename} provided")

        return file.require_dataset(
            "data_down",
            (space_samples, 0),
            maxshape=(space_samples, SPS * CHUNK_SIZE),  # Set maxshape to CHUNK_SIZE
            chunks=True,
            dtype=np.float32,
        )

    def get_sorted_dirs(self) -> list[str]:
        """
        Returns a sorted list of dirs in the specified path, excl today's directory.

        Returns:
            A list of directory names (strings).
        """
        filedir_abs: str = self.path
        if os.path.isdir(filedir_abs):
            log.debug(f"Scanning {filedir_abs} for dirs except today's dir")

            return sorted(
                [
                    dir
                    for dir in os.listdir(filedir_abs)
                    # if os.path.isdir(os.path.join(filedir_abs, dir))
                    # and dir != today_formatted
                ]
            )

        else:
            log.warning(f"Unable to scan {filedir_abs} for dirs: dir does not exist")
            return []

    def get_sorted_h5_files(
        self, dir_path_r: str, last_filename: str | None = None
    ) -> list[str]:
        """
        Returns a sorted list of h5 files in the specified directory.

        Args:
            dir_path_r (str): Path to directory with h5 files.
            last_filename (str | None, optional): Last processed file. Defaults to None.

        Returns:
            A list of relevant h5 files in the directory.
        """
        try:
            file_names: list[str] = sorted(
                [
                    os.path.join(self.path, dir_path_r, name)
                    for name in os.listdir(os.path.join(self.path, dir_path_r))
                    if name.endswith(".h5")
                ]
            )

            if last_filename is not None:
                try:
                    file_names = file_names[file_names.index(last_filename) + 1 :]
                except ValueError:
                    log.warning(
                        "File was not found in dir during indexing last filename"
                    )

            return sorted(file_names)

        except FileNotFoundError:
            log.warning(f"Unable to scan {dir_path_r} for h5 files: dir does not exist")
            return []

        except ValueError:
            return []

    def save_status(
        self,
        filedir_r: str,
        last_filename: str,
        last_filedir_r: str,
        start_chunk_time: float,
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
            }
        )

        with open(
            os.path.join(self.path, filedir_r, ".last"), "w", encoding="UTF-8"
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
                os.path.join(self.path, last_filedir_r, ".last"), "w", encoding="UTF-8"
            ) as status_file:
                status_file.write(status_vars_n)

        with open(
            os.path.join(self.path, ".last_timestamp"), "w", encoding="UTF-8"
        ) as status_file:
            status_file.write(
                str(last_filename.split("_")[-1].rsplit(".", maxsplit=1)[0])
            )

    def get_queue(self, filepath_r: str):
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

        def set_defaults(last_filename: str = None, last_timestamp: float = 0) -> tuple:
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
            h5_files_list = self.get_sorted_h5_files(
                dir_path_r=filepath_r, last_filename=last_filename
            )
            start_chunk_time = (
                float(h5_files_list[0].split("_")[-1].rsplit(".", 1)[0])
                if h5_files_list
                else 0
            )
            return h5_files_list, start_chunk_time, last_timestamp

        completed_filepath = os.path.join(self.path, filepath_r, ".completed")
        if os.path.isfile(completed_filepath):
            # If the directory is marked as completed, skip it
            log.info(f"Skipping {filepath_r} as it is marked as completed")
            return [], None, None

        last_timestamp_filepath = os.path.join(self.path, ".last_timestamp")
        if os.path.isfile(last_timestamp_filepath):
            with open(last_timestamp_filepath, "r", encoding="UTF-8") as status_file:
                last_timestamp = float(status_file.read())
        else:
            last_timestamp = 0

        status_filepath = os.path.join(self.path, filepath_r, ".last")
        if os.path.isfile(status_filepath):
            with open(status_filepath, "r", encoding="UTF-8") as status_file:
                status_vars: dict = json.load(status_file)
                last_filename = status_vars.get("last_filename")
                last_filedir_r = status_vars.get("last_filedir")
                start_chunk_time = status_vars.get("start_chunk_time")

            if start_chunk_time is not None:
                file_names_tbd = self.get_sorted_h5_files(
                    dir_path_r=last_filedir_r, last_filename=last_filename
                )
                return file_names_tbd, start_chunk_time, last_timestamp
            else:
                return set_defaults(last_filename, last_timestamp)
        return set_defaults()

    def reset_chunks(self, file_dir_r: str) -> bool:
        """Deletes start_chunk_time and total_unit_size
        Used upon error (gap) in data to proceed after without exiting

        Args:
            path_dir (str): absolute PATH to working dir
        """

        log.info(f"Resetting chunk tracking to start from new chunk in {file_dir_r}")
        status_filepath_r = os.path.join(self.path, file_dir_r, ".last")
        if os.path.isfile(status_filepath_r):
            with open(status_filepath_r, "r", encoding="UTF-8") as status_file:
                status_vars: dict = json.load(status_file)

            status_vars.pop("start_chunk_time", None)

            with open(status_filepath_r, "w", encoding="UTF-8") as status_file:
                status_vars: dict = json.dump(status_vars, status_file)

        if os.path.isfile(os.path.join(self.path, ".last_timestamp")):
            os.remove(os.path.join(self.path, ".last_timestamp"))
        return True

    def set_completed(self, working_dir: str):
        with open(os.path.join(self.path, working_dir, ".completed"), "w") as f:
            f.write("")

    def read_attrs(self, working_dir: str, filename: str = "attrs.json"):
        # Read attributes from json file from working dir
        print(os.path.exists(os.path.join(self.path, working_dir, filename)))
        try:
            with open(os.path.join(self.path, working_dir, filename), "r") as json_file:
                attrs = json.load(fp=json_file)
                self.write_attrs(attrs, working_dir)
            return attrs
        except FileNotFoundError:
            print(os.path.join(self.path, working_dir, filename))
            raise Error(f"File {filename} not found in {working_dir}")

    def write_attrs(self, attrs: dict, working_dir: str):
        # Write attributes to json file in save dir
        os.makedirs(
            os.path.join(self.save_path, working_dir[:4], working_dir), exist_ok=True
        )
        with open(
            os.path.join(self.save_path, working_dir[:4], working_dir, "attrs.json"),
            "w",
        ) as f:
            json.dump(attrs, f)
