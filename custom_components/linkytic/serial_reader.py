"""The linkytic integration serial reader."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum

import serial
import serial.serialutil
import serial.threaded
from homeassistant.core import callback

from .const import (
    ADDRESS_TAGS,
    BYTESIZE,
    FRAME_ETX,
    LINKY_IO_ERRORS,
    MODE_HISTORIC_BAUD_RATE,
    MODE_STANDARD_BAUD_RATE,
    PARITY,
    SHORT_FRAME_DETECTION_TAGS,
    STOPBITS,
)
from .parser import (
    Dataset,
    HistoricTICParser,
    LinkyIdentifier,
    StandardTICParser,
)

_LOGGER = logging.getLogger(__name__)


class State(Enum):
    """State of the serial reader."""

    INITIALIZED = 0
    RUNNING = 1
    FAILED = 2
    STOPPED = 3


class LinkyTICReader(threading.Thread):
    """Implements the reading of a serial Linky TIC."""

    def __init__(
        self,
        title: str,
        port,
        std_mode,
        producer_mode,
        three_phase,
        real_time: bool | None = False,
    ) -> None:
        """Init the LinkyTIC thread serial reader."""  # Thread
        self._setup_error: BaseException | None = None
        self._stopsignal = False
        self._title = title
        # Options
        if real_time is None:
            real_time = False
        self._realtime = real_time
        # Build
        self._port = port
        self._baudrate = (
            MODE_STANDARD_BAUD_RATE if std_mode else MODE_HISTORIC_BAUD_RATE
        )
        self._std_mode = std_mode
        self._producer_mode = producer_mode if std_mode else False
        self._three_phase = three_phase
        # Run
        self._reader: serial.Serial | None = None
        self._parser = StandardTICParser() if std_mode else HistoricTICParser()
        self._values: dict[str, Dataset] = {}
        self._frames_read = 0
        self._tags_seen: list[str] = []
        self._device_identifier: LinkyIdentifier | None = None
        self._notif_callbacks: dict[str, Callable[[bool], None]] = {}
        self._state = State.INITIALIZED
        # Init parent thread class
        super().__init__(name=f"LinkyTIC for {title}")

    def get_values(self, tag) -> tuple[str | None, str | None]:
        """Get tag value and timestamp from the thread memory cache."""
        if not self.is_connected:
            return None, None
        try:
            payload = self._values[tag]
            return payload.data, payload.timestamp
        except KeyError:
            return None, None

    @property
    def has_read_full_frame(self) -> bool:
        """Use to known if at least one complete frame has been read on the serial connection."""
        return self._frames_read >= 1

    @property
    def is_connected(self) -> bool:
        """Use to know if the reader is actually connected to a serial connection."""
        if self._reader is None:
            return False
        return self._reader.is_open

    @property
    def device_identifier(self) -> LinkyIdentifier | None:
        """Returns the meter identifier and infos."""
        return self._device_identifier

    @property
    def port(self) -> str:
        """Returns serial port."""
        return self._port

    @property
    def setup_error(self) -> BaseException | None:
        """If the reader thread terminates due to a serial exception, this property will contain the raised exception."""
        return self._setup_error

    def _frame_received(self, frame: bytes) -> None:
        """Handler for frame received."""

        datasets = self._parser.parse(frame)

        # Check for serial number matching.
        # First frame is certainly incomplete, still trying to parse it.
        addresses: list[Dataset] = []
        for tag in ADDRESS_TAGS:
            address = datasets.pop(tag, None)
            if address:
                addresses.append(address)

        if len(addresses) == 0:
            if not self.has_read_full_frame:
                _LOGGER.debug(
                    "First frame received does not contain meter address, ignoring."
                )
            else:
                _LOGGER.warning("Received a frame with no meter address, ignoring.")
            return

        if len(addresses) > 1:
            _LOGGER.warning("Received a frame with multiple meter addresses, ignoring.")
            return

        address = addresses[0]

        if not self.device_identifier:
            # Should only be assigned for first initialization of new entry.
            self._device_identifier = LinkyIdentifier(address.data)

        elif self.device_identifier.serial_number != address.data:
            # Address mismatch.
            _LOGGER.warning(
                "Received a frame with unknown meter address: %s, ignoring.",
                address.data,
            )
            return

        # Historic short frames must be pushed.
        if self._realtime or self._is_short_frame(datasets):
            # Get matching keys.
            for key in datasets.keys() & self._notif_callbacks.keys():
                self._notif_callbacks[key](self._realtime)

        self._frames_read += 1
        self._values.update(datasets)

    def _is_short_frame(self, datasets: dict[str, Dataset]) -> bool:
        """Specific handler for historic short frames. Will return True if function handled a short frame."""
        if not self._std_mode and datasets.keys() & SHORT_FRAME_DETECTION_TAGS:
            _LOGGER.debug("Short frame detected, pushing data.")
            return True
        return False

    def run(self):
        """Continuously read the the serial connection and extract TIC values."""
        self._open_serial()
        if self._reader is None:
            # Serial error, do not start reader thread
            return

        _LOGGER.info("Serial connection established at %s", self._port)
        self._state = State.RUNNING

        while not self._stopsignal:
            if not self._reader.is_open:
                # Retry connection on error
                try:
                    self._reader.open()
                except LINKY_IO_ERRORS as e:
                    if self._state is not State.FAILED:
                        self._state = State.FAILED
                        _LOGGER.warning("Could not connect to %s: (%s)", self._port, e)

                    # Cooldown
                    time.sleep(2)
                    continue

            try:
                # Will block until completion or cancel_read() is called.
                frame = self._reader.read_until(FRAME_ETX)
            except LINKY_IO_ERRORS as exc:
                _LOGGER.error(
                    "Failed to read data from serial connection at %s: %s.",
                    self._port,
                    exc,
                )
                self._reader.close()
                self._reset_state()
            else:
                if not frame:
                    # Nothing was read, try again
                    continue

                self._frame_received(frame)

        self._reader.close()
        self._reset_state()
        self._state = State.STOPPED
        _LOGGER.debug(
            "Last bytes on wire: %s (total frames received: %s)",
            frame,
            self._frames_read,
        )

    def register_push_notif(self, tag: str, notif_callback: Callable[[bool], None]):
        """Call to register a callback notification when a certain tag is parsed."""
        _LOGGER.debug("Registering a callback for %s tag", tag)
        self._notif_callbacks[tag] = notif_callback

    @callback
    def signalstop(self, event):
        """Activate the stop flag in order to stop the thread from within."""
        if self.is_alive():
            _LOGGER.info(
                "Stopping %s serial thread reader (received %s)", self._title, event
            )
            self._stopsignal = True
            # No timeout is configured, we have to cancel any blocking read operation
            if self._reader and self._reader.is_open:
                self._reader.cancel_read()

    def update_options(self, real_time: bool):
        """Setter to update serial reader options."""
        _LOGGER.debug("%s: new real time option value: %s", self._title, real_time)
        self._realtime = real_time

    def _cleanup_cache(self):
        """Call to cleanup the data cache to allow some sensors to get back to undefined/unavailable if they are not present in the last frame."""
        for cached_tag in list(self._values.keys()):  # pylint: disable=consider-using-dict-items,consider-iterating-dictionary
            if cached_tag not in self._tags_seen:
                _LOGGER.debug(
                    "tag %s was present in cache but has not been seen in previous frame: removing from cache",
                    cached_tag,
                )
                # Clean serial controller data cache for this tag
                del self._values[cached_tag]
                # Inform entity of a new value available (None) if in push mode
                try:
                    notif_callback = self._notif_callbacks[cached_tag]
                    notif_callback(self._realtime)
                except KeyError:
                    pass
        self._tags_seen = []

    def _open_serial(self) -> None:
        """Create (and open) the serial connection."""
        self._reset_state()

        # Because we run in the thread context, we need to catch any exceptions and save them to report to the main thread.
        try:
            self._reader = serial.serial_for_url(
                url=self._port,
                baudrate=self._baudrate,
                bytesize=BYTESIZE,
                parity=PARITY,
                stopbits=STOPBITS,
            )
        except LINKY_IO_ERRORS as e:
            self._setup_error = e
            self._stopsignal = True

    def _reset_state(self):
        """Reinitialize the controller."""
        self._values = {}
        # Inform sensor in push mode to come fetch data (will get None and switch to unavailable)
        for notif_callback in self._notif_callbacks.values():
            notif_callback(self._realtime)
        self._state = State.INITIALIZED


def linky_tic_tester(device: str, std_mode: bool) -> None:
    """Before starting the thread, this method can help validate configuration by opening the serial communication and read a line. It returns None if everything went well or a string describing the error."""
    # Open connection
    try:
        serial_reader = serial.serial_for_url(
            url=device,
            baudrate=MODE_STANDARD_BAUD_RATE if std_mode else MODE_HISTORIC_BAUD_RATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=1,
        )
    except serial.serialutil.SerialException as exc:
        raise CannotConnect(
            f"Unable to connect to the serial device {device}: {exc}"
        ) from exc
    # Try to read a line
    try:
        serial_reader.readline()
    except serial.serialutil.SerialException as exc:
        serial_reader.close()
        raise CannotRead(f"Failed to read a line: {exc}") from exc
    # All good
    serial_reader.close()


class CannotConnect(Exception):
    """Error to indicate we cannot connect."""

    def __init__(self, message) -> None:
        """Initialize the CannotConnect error with an explanation message."""
        super().__init__(message)


class CannotRead(Exception):
    """Error to indicate that the serial connection was open successfully but an error occurred while reading a line."""

    def __init__(self, message) -> None:
        """Initialize the CannotRead error with an explanation message."""
        super().__init__(message)
