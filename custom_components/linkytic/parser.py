from abc import ABC
import re
from const import (
    DATASET_HISTORIC,
    DATASET_STANDARD,
    FRAME_ENCODING
)

class Dataset(ABC):
    """Object to represent an universal dataset.
    Datasets are the fields of a frame and contains a tag-data pair (and enventually corresponding timestamp).
    Raw bytes (ascii encoded) shall be passed to the constructor, the class will check formatting and verify checksum.
    """
    __slots__ = ('_tag', '_data', '_timestamp')

    _PATTERN: re.Pattern
    _tag: str
    _data: str
    _timestamp: str | None

    def __init__(self, raw_dataset: bytes):
        try:
            str_dataset = raw_dataset.decode(FRAME_ENCODING)
        except UnicodeDecodeError:
            raise Exception
        
        m = self._PATTERN.match(str_dataset)
        if not m:
            # No match = malformed dataset
            raise Exception

        self._tag = m.group('tag')
        self._data = m.group('data')
        self._timestamp = m.group('timestamp')

        checksum = ord(m.group('checksum'))

        checked_zone = m.group('checked')

        if (c := self._compute_checksum(checked_zone)) != checksum:
            raise InvalidChecksumError(raw_dataset, c, checksum)

    def _compute_checksum(self, checked) -> int:
        """Returns the checksum"""
        S1 = sum(checked)
        return (S1 & 0x3F) + 0x20

    def __repr__(self) -> str:
        return "<Dataset: %s, %s, %s>" % (self._tag, self._data, self._timestamp)

    @property
    def tag(self) -> str:
        return self._tag
    
    @property
    def data(self) -> str:
        return self._data
    
    @property
    def timestamp(self) -> str | None:
        return self._timestamp
    

class HistoricDataset(Dataset):
    """Dataset implementing the historic format"""
    _PATTERN = re.compile(DATASET_HISTORIC, re.X)


class StandardDataset(Dataset):
    """Dataset implementing the standard format"""
    _PATTERN = re.compile(DATASET_STANDARD, re.X)


class TICParser(ABC):
    pass

class StandardTICParser(TICParser):
    pass

class HistoricTICParser(TICParser):
    pass


class InvalidChecksumError(Exception):
    pass