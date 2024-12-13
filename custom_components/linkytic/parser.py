"""Parser for the TIC protocol."""

from __future__ import annotations

import logging
import re
from abc import ABC
from dataclasses import dataclass

from .const import (
    CONSTRUCTORS_CODES,
    DATASET_END,
    DATASET_HISTORIC,
    DATASET_STANDARD,
    DATASET_START,
    DEVICE_TYPES,
    FRAME_ENCODING,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True, init=False)
class LinkyIdentifier:
    """Representation of a Linky device."""

    serial_number: str
    constructor_code: str
    constructor: str
    registration_number: str
    type_code: str
    type: str
    year: str

    def __init__(self, address: str) -> None:
        """Extract information contained in the ADS as EURIDIS."""

        if len(address) != 12:
            raise ValueError(
                f"Linky address must be 12 characters, received {len(address)}."
            )

        # Cannot call self.__setattr__() because of frozen instance
        object.__setattr__(self, "serial_number", address)
        object.__setattr__(self, "constructor_code", address[0:2])
        object.__setattr__(self, "year", address[2:4])
        object.__setattr__(self, "type_code", address[4:6])
        object.__setattr__(self, "registration_number", address[6:])

        object.__setattr__(
            self, "constructor", CONSTRUCTORS_CODES.get(self.constructor_code, None)
        )
        object.__setattr__(self, "type", DEVICE_TYPES.get(self.type_code, None))


class Dataset(ABC):
    """Object to represent an universal dataset.
    Datasets are the fields of a frame and contains a tag-data pair (and eventually corresponding timestamp).
    Raw bytes (ascii encoded) shall be passed to the constructor, the class will check formatting and verify checksum.
    """

    __slots__ = ("_tag", "_data", "_timestamp")

    _PATTERN: re.Pattern
    _tag: str
    _data: str
    _timestamp: str | None

    def __init__(self, raw_dataset: bytes):
        try:
            str_dataset = raw_dataset.decode(FRAME_ENCODING)
        except UnicodeDecodeError as e:
            raise MalformedDatasetError(raw_dataset) from e

        m = self._PATTERN.match(str_dataset)
        if not m:
            # No match = malformed dataset
            raise MalformedDatasetError(raw_dataset)

        self._tag = m.group("tag")
        self._data = m.group("data")
        self._timestamp = m.group("timestamp")

        checksum = ord(m.group("checksum"))

        checked_zone = m.group("checked")

        if (c := self._compute_checksum(checked_zone)) != checksum:
            raise InvalidChecksumError(raw_dataset, c, checksum)

    def _compute_checksum(self, checked) -> int:
        """Returns the checksum"""
        s1 = sum(ord(c) for c in checked)
        return (s1 & 0x3F) + 0x20

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(tag={self._tag},data={self._data},timestamp={self._timestamp})"

    @property
    def tag(self) -> str:
        """Tag of the dataset."""
        return self._tag

    @property
    def data(self) -> str:
        """Data of the dataset."""
        return self._data

    @property
    def timestamp(self) -> str | None:
        """Timestamp of the data, where applicable."""
        return self._timestamp


class HistoricDataset(Dataset):
    """Dataset implementing the historic format"""

    _PATTERN = re.compile(DATASET_HISTORIC, re.X)


class StandardDataset(Dataset):
    """Dataset implementing the standard format"""

    _PATTERN = re.compile(DATASET_STANDARD, re.X)


class TICParser(ABC):
    """Generic TIC parser."""

    DATASET: type[Dataset]

    class PacketIterator:
        """Helper class for iterating packets."""

        GRP_START = ord(DATASET_START)
        GRP_END = ord(DATASET_END)

        def __init__(self, data: bytes):
            self.data = data
            self.len = len(data)
            self.ptr = 0

        def __iter__(self):
            return self

        def __next__(self):
            # Warning: a bytes element returns a int
            while self.ptr < self.len and self.data[self.ptr] != self.GRP_START:
                self.ptr += 1

            if self.ptr >= self.len:
                raise StopIteration

            start = self.ptr
            # Warning: a bytes element returns a int
            while self.ptr < self.len and self.data[self.ptr] != self.GRP_END:
                self.ptr += 1

            if self.ptr >= self.len:
                raise StopIteration

            return self.data[start : self.ptr + 1]

    def __init__(self) -> None:
        self._rx_ok = 0
        self._rx_error = 0

    def parse(self, frame: bytes) -> dict[str, Dataset]:
        """Parses a received frame."""
        datasets = {}

        for group in self.PacketIterator(frame):
            try:
                dataset = self.DATASET(group)
            except (InvalidChecksumError, MalformedDatasetError) as e:
                _LOGGER.debug("Could not parse the following dataset: %s %s", group, e)
                self._rx_error += 1
            else:
                self._rx_ok += 1
                datasets[dataset.tag] = dataset

        _LOGGER.debug("Parsed datasets: %s", datasets)

        return datasets

    @property
    def invalid(self) -> int:
        """Returns the number of bad dataset since startup."""
        return self._rx_error


class StandardTICParser(TICParser):
    """Parser for the Standard TIC."""

    DATASET = StandardDataset


class HistoricTICParser(TICParser):
    """Parser for the Historic TIC."""

    DATASET = HistoricDataset


class InvalidChecksumError(Exception):
    """Invalid dataset checksum error."""

    def __init__(self, raw, expected, computed) -> None:
        super().__init__(
            f"Invalid checksum for dataset {raw} (expected: {expected}, computed: {computed})"
        )
        self.raw = raw
        self.expected = expected
        self.computed = computed


class MalformedDatasetError(Exception):
    """Malformed dataset error."""

    def __init__(self, raw) -> None:
        super().__init__(f"Malformed dataset: {raw}")
        self.raw = raw
