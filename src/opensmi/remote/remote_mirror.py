# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""Various Mixins mirroring remote variable (containers)."""

from __future__ import annotations

from typing import Any

import structlog
from asyncua.common.node import Node
from asyncua.common.subscription import DataChangeNotif
from asyncua.ua import UaStatusCodeError
from opensmi.client import RemoteVariable
from opensmi.client.remote_callable import RemoteCallable
from opensmi.client.remote_component import BaseRemoteComponent
from opensmi.client.sample import Sample
from opensmi.server import Server
from opensmi.server.mixins import AttributesMixin, FinalResultDataMixin, MonitoringMixin, ParameterSetMixin

_LOGGER = structlog.get_logger(__name__)

# TODO(CaHa): enum support
# async def _get_datatype(var: RemoteVariable, *, server: Server) -> NodeId | None:
#     if var.ua_data_type == "Enumeration":
#         # create new enum based on valid values
#         # TODO actually mirror the enum? with correct namespace etc
#         node = await new_enum(server=server.ua_server, idx=1, name=f"{var.name}Type",  # type: ignore
#                               fields=[var.valid_values[key] for key in sorted(var.valid_values)])
#         return node.nodeid
#     else:
#         return getattr(ua.object_ids.ObjectIds, var.ua_data_type, None)

class RemoteAttributeUpdateMixin(AttributesMixin):
    """Mixin implementing (one-way) attribute updates from the remote server."""

    _client_remote_object: BaseRemoteComponent

    async def _init_attributes_mirror(self, historize: bool = True) -> None:
        if len(self._client_remote_object.attributes) <= 0:
            return

        for remote_attribute in self._client_remote_object.attributes:
            await self.add_attribute_variable(
                remote_attribute.name,
                await remote_attribute.read_raw_value(),
                #datatype=await _get_datatype(remote_attribute), # TODO
                historize=historize,
                unit=remote_attribute.unit.UnitId if remote_attribute.unit else None,
                _range=(remote_attribute.range.Low, remote_attribute.range.High) if remote_attribute.range else None,
            )
            remote_attribute.value_changed.connect(self._on_attribute_update)

    async def _on_attribute_update(self, var: RemoteVariable, sample: Sample[Any]) -> None:
        try:
            await self.attributes[var.name].write(sample.variant)
        except KeyError:
            _LOGGER.warning("Received unknown attribute update from remote component!", variable=var)


class RemoteParameterMirrorMixin(ParameterSetMixin):
    """Mixin implementing bidirectional parameter synchronization for `RemoteComponent` & `RemoteCallable`."""

    _client_remote_object: BaseRemoteComponent | RemoteCallable
    server: Server

    async def _init_parameter_set_mirror(self, historize: bool = True) -> None:
        if len(self._client_remote_object.parameter_set) <= 0:
            return

        nodes = []
        for remote_parameter in self._client_remote_object.parameter_set:
            node = await self.add_parameter_variable(
                remote_parameter.name,
                await remote_parameter.read_raw_value(),
                # datatype=await _get_datatype(remote_parameter),  # TODO
                historize=historize,
                unit=remote_parameter.unit.UnitId if remote_parameter.unit else None,
                _range=(remote_parameter.range.Low, remote_parameter.range.High) if remote_parameter.range else None,
            )
            remote_parameter.value_changed.connect(self._on_parameter_update)
            nodes.append(node)

        # create (local) subscriptions for the parameters so we can transfer changes back to the remote instance.
        # NOTE: This mechanism is usually too slow for remote callables. Copy parameters over immediately before
        # executing remote execution call
        subscription = await self.server.ua_server.create_subscription(period=100, handler=self)
        await subscription.subscribe_data_change(nodes)

    async def _copy_parameter_set_to_remote(self) -> None:
        """Manually copy the remote final result data into the local one."""
        for variable in self.parameter_set:
            local_value = await variable.read()
            await self._client_remote_object.parameter_set[variable.name].write_value(local_value)


    async def _on_parameter_update(self, var: RemoteVariable, sample: Sample[Any]) -> None:
        try:
            await self.parameter_set[var.name].write(sample.variant)
        except KeyError:
            _LOGGER.warning("Received unknown parameter update!", variable=var)

    async def datachange_notification(self, node: Node, val: Any, data: DataChangeNotif) -> None:
        """Handle the internal OPC UA data change notification."""
        # these are (local) server side notifications, and the only thing that clients can change are
        # parameters
        for variable in self.parameter_set:
            if node.nodeid == variable.ua_node.nodeid:
                try:
                    remote_variable = self._client_remote_object.parameter_set[variable.name]
                except KeyError:
                    _LOGGER.warning(
                        "Could not find parameter in client parameter set!",
                        ua_node = node.nodeid.to_string(),
                    )
                    return

                try:
                    await remote_variable.write_value(val)
                except UaStatusCodeError as err:
                    _LOGGER.error("Could not write to remote variable!", remote_variable=remote_variable, err=err)
                return

        _LOGGER.warning("Unmatched data change notification!", ua_node=node.nodeid.to_string())


class RemoteMonitoringUpdateMixin(MonitoringMixin):
    """Mixin implementing (one-way) monitoring updates from the remote server."""

    _client_remote_object: BaseRemoteComponent | RemoteCallable

    async def _init_monitoring_mirror(self, historize: bool = True) -> None:
        if len(self._client_remote_object.monitoring) <= 0:
            return

        for remote_monitoring in self._client_remote_object.monitoring:
            await self.add_monitoring_variable(
                remote_monitoring.name,
                await remote_monitoring.read_raw_value(),
                # datatype=await _get_datatype(remote_monitoring), # TODO
                historize=historize,
                unit=remote_monitoring.unit.UnitId if remote_monitoring.unit else None,
                _range=(remote_monitoring.range.Low, remote_monitoring.range.High) if remote_monitoring.range else None,
            )
            remote_monitoring.value_changed.connect(self._on_monitoring_update)

    async def _on_monitoring_update(self, var: RemoteVariable, sample: Sample[Any]) -> None:
        try:
            await self.monitoring[var.name].write(sample.variant)
        except KeyError:
            _LOGGER.warning("Received unknown monitoring update!", variable=var)


class RemoteFinalResultUpdateMixin(FinalResultDataMixin):
    """Mixin implementing (one-way) final result updates from the remote server."""

    _client_remote_object: RemoteCallable

    async def _init_final_result_data_mirror(self, historize: bool = True) -> None:
        if len(self._client_remote_object.final_result_data) <= 0:
            return

        for remote_result in self._client_remote_object.final_result_data:
            remote_result.value_changed.connect(self._on_final_result_update)
            if remote_result.name in self.final_result_data:  # e.g. SuccessfulExecutionsCount of FiniteSkillType
                continue
            await self.add_result_variable(
                remote_result.name,
                await remote_result.read_raw_value(),
                # datatype=await _get_datatype(remote_result),  # TODO
                historize=historize,
                unit=remote_result.unit.UnitId if remote_result.unit else None,
                _range=(remote_result.range.Low, remote_result.range.High) if remote_result.range else None,
            )

    async def _on_final_result_update(self, var: RemoteVariable, sample: Sample[Any]) -> None:
        try:
            await self.final_result_data[var.name].write(sample.value)  # local type, e.g. UInt32 of a FiniteSkillType
        except KeyError:
            _LOGGER.warning("Received unknown final result data update!", variable=var)

    async def _copy_final_result_data_from_remote(self) -> None:
        """Manually copy the remote final result data into the local one."""
        for remote_variable in self._client_remote_object.final_result_data:
            remote_value = await remote_variable.read_value(update_cache=True)
            await self.final_result_data[remote_variable.name].write(remote_value)
