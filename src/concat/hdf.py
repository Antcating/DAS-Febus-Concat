"""
This module contains the H5File class which is the main class for h5 processing.
It reads an h5 file and unpacks the packet time and actual data from the packet.
It also checks if the h5 file fits the requirements to be concatenated.
"""
from datetime import datetime
import pytz
import h5py
from os.path import join

from config import LOCAL_PATH, DATA_LOSE_THRESHOLD
from log.main_logger import logger as log


class H5File:
    """Main class for h5 processing"""

    def __init__(
        self, file_dir: str, file_name: str, space_samples: int, time_samples: int
    ) -> None:
        try:
            self.file = h5py.File(
                join(LOCAL_PATH, file_dir, file_name), "r", rdcc_nbytes=2 * 1024 * 4
            )
        except OSError as err:
            raise Exception(f"{file_dir + '/' + file_name} file is corrupted:", err)

        self.file_name: str = file_name
        self.file_dir: str = file_dir

        self.space_samples: int = space_samples
        self.time_samples: int = time_samples

        # Values to be calculated
        self.packet_time: float = None
        self.packet_datetime: datetime = None
        self.dset: h5py.Dataset = None
        # Used if needed
        self.is_chunk_end = False
        self.is_day_end = False
        self.dset_split: h5py.Dataset = None
        self.dset_carry: h5py.Dataset = None
        # If chunk splitted, time of split will be written here
        self.split_time: int | float = None

        self.unpack_stat = True

        self.unpack_h5_data()

    def unpack_h5_data(self) -> None:
        """Unpacks at and data from h5"""

        def unpack_date():
            """Unpacking packet time (as UNIX timestamp)

            Returns:
                bool: Status bool
            """
            try:
                self.packet_time = float(
                    self.file_name.split("_")[-1].rsplit(".", maxsplit=1)[0]
                )
                self.packet_datetime = datetime.fromtimestamp(
                    self.packet_time, tz=pytz.UTC
                )
                return True
            except ValueError:
                log.exception(
                    f"Unable to read file's packet_time, unable to use it: "
                    f"{self.file_name}"
                )
                return False

        def unpack_data():
            """Unpacks actual data from packet

            Returns:
                bool: Status bool
            """
            try:
                self.dset = self.file["data_down"]
                return True
            except KeyError:
                log.exception(
                    f"Unable to unpack data from h5 file, dataset missing: "
                    f"{self.file_name}"
                )
                return False

        self.unpack_stat = unpack_date()
        self.unpack_stat = unpack_data()

    def check_h5(self, last_timestamp: float) -> bool:
        """Checks h5 file if it fits the requirements to be concatenated

        Args:
            last_timestamp (float): Timestamp from previous file.
                Used to calculate time difference between adjoint packets

        Returns:
            bool: Status boolean. True if everything OK, False otherwise
        """
        try:
            # DATA lost warning
            packet_diff = self.packet_time - last_timestamp
            if last_timestamp != 0 and packet_diff > DATA_LOSE_THRESHOLD:
                log.warning(
                    f"Possible data lost: {last_timestamp+4}->{self.packet_time-2}"
                )
                self.unpack_stat = False
                return self.unpack_stat, "missing"

            # Shape check
            if (
                self.dset.shape[0] != self.time_samples
                or self.dset.shape[1] != self.space_samples
            ):
                log.warning(
                    f"Packet {self.file_name} has unexpected shape: "
                    f"{self.dset.shape}"
                )
                self.unpack_stat = False
                return self.unpack_stat, "downsampling"

            return self.unpack_stat, None
        except AttributeError:
            self.unpack_stat = False
            return self.unpack_stat, "key"
