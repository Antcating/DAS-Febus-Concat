import os
import h5py
import datetime
import numpy as np

from config import PATH, SAVE_PATH, TIME_DIFF_THRESHOLD, CONCAT_TIME
from hdf import H5_FILE
from logger import set_console_logger, set_file_logger, log

# ---


# Already correctly downsampled file for reference
referenceFile = h5py.File("downsampled_reference.h5")
TimeSamples, SpaceSamples = referenceFile["data_down"].shape

UnitSizeSample = referenceFile.attrs["unit_size"]
CHUNK_SIZE = int(CONCAT_TIME / (UnitSizeSample / 2))

# *important* today's date according to UTC
today = datetime.datetime.now(tz=datetime.UTC)
date_list = [str(x) for x in [today.year, today.month, today.day]]
TODAY_DATE_STR = "".join(date_list)

def get_dirs(path: str) -> list:
    """Returns dirs in path except dir named by today's date in format YYYYMMDD

    Args:
        path (str): path to dir to scan to dirs

    Returns:
        list: list of dirs in the path except dir named by today's date in format YYYYMMDD
    """
    dirs = [
        dir
        for dir in os.listdir(path)
        if os.path.isdir(path + dir) and dir != TODAY_DATE_STR
    ]
    return dirs


def get_h5_files(path: str) -> list:
    """Returns h5 files for processing

    Args:
        path (str): Path to directory with h5 files

    Returns:
        list: List of h5 files in directory
    """
    file_names = sorted([name for name in os.listdir(path) if name.endswith(".h5")])
    return file_names


def require_h5(working_dir: str, chunk_time: float) -> h5py.Dataset:
    """Creates h5 file with attrs (if necessary)

    Args:
        working_dir (str): Name of the directory files are located at (for name of the new file)
        chunk_time (float): time of the necessary chunk

    Returns:
        h5py.Dataset: Returns dataset of the created h5 file
    """

    file = h5py.File(SAVE_PATH + working_dir + "_" + str(chunk_time) + ".h5", "a")
    dset = file.require_dataset(
        "data_down",
        (0, SpaceSamples),
        maxshape=(None, SpaceSamples),
        chunks=True,
        dtype=np.float32,
    )
    # Add attrs from reference h5 file
    for key in [
        key
        for key in referenceFile.attrs.keys()
        if key not in ["packet_time", "save_time"]
    ]:
        file.attrs[key] = referenceFile.attrs[key]
    return dset


def calculate_chunk_offset(total_unit_size: int):
    return (total_unit_size // CONCAT_TIME) * CONCAT_TIME


def concat_to_chunk_by_time(
    file: H5_FILE,
    total_unit_size: int,
    start_chunk_time: float,
    curr_dir: str,
    concat_unit_size: int,
):
    def concat_h5(dset_origin: h5py.Dataset, dset_destination: h5py.Dataset):
        dset_destination.resize(dset_destination.shape[0] + dset_origin.shape[0], axis=0)
        dset_destination[-dset_origin.shape[0] :] = dset_origin[()]

        return dset_destination

    chunk_time = start_chunk_time + calculate_chunk_offset(total_unit_size)
    file_concat = h5py.File(SAVE_PATH + curr_dir + "_" + str(chunk_time) + ".h5", "a")
    dset_concat = file_concat["data_down"]

    log.debug(f"Concatenating {file.file_name}")
    if file.dset_split is not None:
        dset_concat = concat_h5(
            dset_origin=file.dset_split, dset_destination=dset_concat
        )
    else:
        dset_concat = concat_h5(dset_origin=file.dset, dset_destination=dset_concat)

    total_unit_size += int(concat_unit_size)

    log.debug(f"Concat has shape:  {dset_concat.shape}")

    # Flip to next chunk
    if total_unit_size % CONCAT_TIME == 0:
        log.info(
            f"{curr_dir} | Final shape: {h5py.File(SAVE_PATH + curr_dir + '_' + str(chunk_time) + '.h5')['data_down'].shape}"
        )
        # Recalculate new chunk time
        chunk_time = start_chunk_time + calculate_chunk_offset(total_unit_size)
        # Create new h5 chunk file
        dset_concat = require_h5(curr_dir, chunk_time)
        if file.dset_carry is not None:
            log.info("Carry has been created and used in the next chunk")
            dset_concat = concat_h5(
                dset_origin=file.dset_carry, dset_destination=dset_concat
            )
            total_unit_size += int(file.attrs.unit_size / 2)

    return total_unit_size


def concat_files(curr_dir: str) -> tuple[bool, Exception | None]:
    # TODO: add annotation for function
    path_dir: str = PATH + curr_dir + "/"
    file_names: list = get_h5_files(path_dir)
    # Staring from the last saved
    if os.path.isfile(path_dir + ".last"):
        start_chunk_time, last_file, total_unit_size = (
            open(path_dir + ".last", "r").read().split(";")
        )
        start_chunk_time = float(start_chunk_time)
        total_unit_size = int(total_unit_size)

        file_names_tbd = file_names[file_names.index(last_file) + 1 :].copy()
        last_timestamp = h5py.File(path_dir + last_file).attrs["packet_time"]
    else:
        file_names_tbd: list[str] = file_names.copy()
        # Init values
        last_timestamp: int = 0
        total_unit_size: int = 0
        start_chunk_time: float = float(
            file_names_tbd[0].split("_")[-1].rsplit(".", 1)[0]
        )

    chunk_time = start_chunk_time + calculate_chunk_offset(total_unit_size)
    last_major_status = None

    major_file_names_tbd = file_names_tbd[::2][::-1]
    minor_file_names_tbd = file_names_tbd[1::2][::-1]
    # Create empty file for concat
    require_h5(curr_dir, chunk_time)

    while len(major_file_names_tbd) > 0 or len(minor_file_names_tbd) > 0:
        if len(major_file_names_tbd) > 0:
            major_file_name = major_file_names_tbd[-1]
            file = H5_FILE(file_dir=curr_dir, file_name=major_file_name)
            major, reason = file.check_h5(last_timestamp=last_timestamp)
        else:
            major = False

        if major is False:
            minor_file_name = minor_file_names_tbd[-1]

            msg = f"{curr_dir} | Using minor file: {minor_file_name}"
            log.info(msg)

            file = H5_FILE(file_dir=curr_dir, file_name=minor_file_name)
            minor, reason = file.check_h5(last_timestamp=last_timestamp)

            # We tested both major and minor files. Both corrupted in some way, so we raise the exception!
            if minor is False:
                raise Exception("DATA IS CORRUPTED IN THE UNRECOVERABLE WAY")
        elif major is True:
            log.info(f"{curr_dir} | Using major file: {major_file_name}")


        # if end of the chunk is half of the packet and is major or minor after major was skipped:
        # Split and take first half of the packet
        if (major or reason == "missing") and CONCAT_TIME - (
            (CONCAT_TIME + total_unit_size) % CONCAT_TIME
        ) < TIME_DIFF_THRESHOLD:
            split_offset = int(file.dset.shape[0] / 2)

            file.dset_split = file.dset[:split_offset, :]
            # Creating carry to use in the next chunk
            file.dset_carry = file.dset[split_offset:, :]

            concat_unit_size = file.attrs.unit_size / 2  # 2
        else:
            if file.attrs.packet_time - last_timestamp < TIME_DIFF_THRESHOLD:
                file.dset_split = file.dset[int(file.dset.shape[0] / 2) :, :]
                concat_unit_size = file.attrs.unit_size / 2  # 2
            else:
                concat_unit_size = file.attrs.unit_size  # 4

        # Concatenation if OK
        total_unit_size = concat_to_chunk_by_time(
            file=file,
            total_unit_size=total_unit_size,
            start_chunk_time=start_chunk_time,
            curr_dir=curr_dir,
            concat_unit_size=concat_unit_size,
        )
        # Cleaning the queue
        if major:
            major_file_names_tbd.pop()
            if last_major_status is True:
                minor_file_names_tbd.pop()
        elif major is False:
            minor_file_names_tbd.pop()
            if last_major_status is False:
                major_file_names_tbd.pop()

        last_timestamp = file.attrs.packet_time
        last_major_status = major

        with open(path_dir + ".last", "w") as status_file:
            status_file.write(
                str(start_chunk_time)
                + ";"
                + file.file_name
                + ";"
                + str(total_unit_size)
            )

    return True


def main():
    # Global logger
    set_file_logger(log=log, log_level="WARNING", log_file=SAVE_PATH + "log")

    set_console_logger(log=log, log_level="INFO")
    dirs = get_dirs(path=PATH)
    for dir in dirs:
        # Local logger
        set_file_logger(log=log, log_level="DEBUG", log_file=PATH + dir + "/log")
        status = concat_files(curr_dir=dir)
        if status:
            log.info(f"{dir} | Saving finished with success")
        else:
            # unused
            log.critical(f"{dir} | Concatenation was not finished due to error")

if __name__ == "__main__":
    main()
