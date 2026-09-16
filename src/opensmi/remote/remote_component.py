# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from asyncua.common.subscription import Subscription
from opensmi.client import BaseRemoteComponent as ClientRemoteComponent
from opensmi.client.remote_component import BaseRemoteComponent, NotificationEvent
from opensmi.core import MachineryItemState
from opensmi.server import BaseComponent
from opensmi.server.mixins import NotificationForwarderMixin, ParentMixin
from typing_extensions import override

from opensmi.remote.remote_method import RemoteMethod
from opensmi.remote.remote_mirror import (
    RemoteAttributeUpdateMixin,
    RemoteMonitoringUpdateMixin,
    RemoteParameterMirrorMixin,
)
from opensmi.remote.remote_skill import RemoteSkill

# TODO add support requirements, resources, etc.


class RemoteComponent(
    ParentMixin,
    RemoteAttributeUpdateMixin,
    RemoteParameterMirrorMixin,
    RemoteMonitoringUpdateMixin,
    NotificationForwarderMixin,
    BaseComponent,
):

    _subscription: Subscription

    def __init__(self, *,
        name: str | None = None,
        client_remote_component: ClientRemoteComponent,
        recursive: bool = False,
        minimum_access_level: int = 1
    ) -> None:
        """Create new instance.

        :param client_remote_component: Reference of the client remote component that should be mirrored.
        :param recursive: If True, recursively add all subcomponents as well.
        :param minimum_access_level: (Local) Minimum access level for all remote methods and skills.
        """
        super().__init__(name=name)
        self._client_remote_object = client_remote_component  # named like this because of mixin use
        self._recursive = recursive
        self._minimum_access_level = minimum_access_level

    @override
    async def _write_identification(self) -> None:
        serial_number = await self._client_remote_object.identification["SerialNumber"].read_value()
        await self.identification.SerialNumber.write(serial_number)

        manufacturer = await self._client_remote_object.identification["Manufacturer"].read_value()
        await self.identification.Manufacturer.write(manufacturer)

        if self.identification.AssetId is not None:
            asset_id = await self._client_remote_object.identification["AssetId"].read_value()
            await self.identification.AssetId.write(asset_id)

        if self.identification.ComponentName is not None:
            component_name = await self._client_remote_object.identification["ComponentName"].read_value()
            await self.identification.ComponentName.write(component_name)


    @override
    async def _init(self) -> None:
        await super()._init()

        await self._init_remote_components()
        await self._init_remote_skills()
        await self._init_remote_methods()

        await self._init_attributes_mirror()
        await self._init_monitoring_mirror()
        await self._init_parameter_set_mirror()

        self._client_remote_object.status_changed.connect(self._on_state_change)
        self._client_remote_object.notification_received.connect(self._on_notification_event)

    async def _init_remote_components(self) -> None:
        if len(self._client_remote_object.components) <= 0 or not self._recursive:
            return

        for component in self._client_remote_object.components.values():
            await self.add_component(RemoteComponent(
                name=component.name,
                client_remote_component=component,  # type: ignore
                recursive=True,
                minimum_access_level=self._minimum_access_level
            ))

    async def _init_remote_skills(self) -> None:
        if len(self._client_remote_object.skill_set) <= 0:
            return

        for skill in self._client_remote_object.skill_set.values():
            await self.add_skill(RemoteSkill(
                name=skill.name,
                client_remote_skill=skill,
                minimum_access_level=self._minimum_access_level
            ))

    async def _init_remote_methods(self) -> None:
        if (not isinstance(self._client_remote_object, ClientRemoteComponent)
                or len(self._client_remote_object.method_set) <= 0):
            return

        for method in self._client_remote_object.method_set.values():
            await self.add_method(RemoteMethod(
                name=method.name,
                client_remote_method=method,
                minimum_access_level=self._minimum_access_level
            ))

    ###########################################################
    # Subscription callbacks

    async def _on_state_change(self, _component: BaseRemoteComponent, new_state: str) -> None:
        """Mirror all remote component state changes."""
        try:
            await self.set_current_state(MachineryItemState[new_state])
        except KeyError:
            self.logger.warning("Received unknown machinery item state!", state=new_state)

    async def _on_notification_event(self, _component: BaseRemoteComponent, event: NotificationEvent) -> None:
        """Handle remote notification events by logging them accordingly locally."""
        if event.severity < 555:
            await self.ua_log_info(msg=event.message, severity=event.severity)
        elif event.severity < 999:
            await self.ua_log_warning(msg=event.message, severity=event.severity)
        else:
            await self.ua_log_error(msg=event.message, severity=event.severity, code=event.error_code)
