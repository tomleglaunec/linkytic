"""Entity for linkytic integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import (
    DID_DEFAULT_NAME,
    DOMAIN,
)
from .serial_reader import LinkyTICReader


class LinkyTICEntity(Entity):
    """Base class for all linkytic entities."""

    _serial_controller: LinkyTICReader
    _attr_should_poll = True
    _attr_has_entity_name = True

    def __init__(self, reader: LinkyTICReader):
        """Init Linkytic entity."""
        self._serial_controller = reader

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        did = self._serial_controller.device_identifier
        assert did is not None

        return DeviceInfo(
            identifiers={(DOMAIN, did.registration_number)},
            manufacturer=did.constructor,
            model=did.type,
            name=DID_DEFAULT_NAME,
            serial_number=did.serial_number,
        )
