# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from asyncua import ua
from asyncua.common.methods import uamethod
from asyncua.ua import NodeId
from opensmi.client.remote_skill import RemoteSkill as ClientRemoteSkill
from opensmi.client.sample import Sample
from opensmi.core import SkillState
from opensmi.core.nodesets import SmartFactoryMachineSetNodeIds as MachineSetNodeIds
from opensmi.server.base_machinery_item import BaseMachineryItem
from opensmi.server.base_skill import BaseSkill
from opensmi.server.mixins.parent_mixin import ParentMixin
from opensmi.server.protocols import SessionProtocol
from opensmi.server.ua_object import UaObjectDefinition
from typing_extensions import override

from opensmi.remote.remote_mirror import (
    RemoteFinalResultUpdateMixin,
    RemoteMonitoringUpdateMixin,
    RemoteParameterMirrorMixin,
)


class RemoteSkill(
    ParentMixin[BaseMachineryItem],
    RemoteParameterMirrorMixin,
    RemoteMonitoringUpdateMixin,
    RemoteFinalResultUpdateMixin,
    BaseSkill,
):
    def __init__(
        self,
        *,
        name: str,
        client_remote_skill: ClientRemoteSkill,
        minimum_access_level: int = 1,
    ):
        assert client_remote_skill, "No RemoteSkill from Client given!"
        self._client_remote_object: ClientRemoteSkill = client_remote_skill

        super().__init__(
            name=name,
            suspendable=client_remote_skill.suspendable,
            minimum_access_level=minimum_access_level,
        )

    @override
    async def _get_definition(self) -> UaObjectDefinition:
        object_type = MachineSetNodeIds.FiniteSkillType if self.is_finite else MachineSetNodeIds.ContinuousSkillType
        return UaObjectDefinition(
            object_type=object_type,
            instantiate_optional=True,  # TODO(CaHa): instantiate only what is actually needed
        )

    @override
    async def _init(self) -> None:
        await super()._init()

        await self._init_monitoring_mirror()
        await self._init_parameter_set_mirror()
        await self._init_final_result_data_mirror()

        current_state = await self._client_remote_object.read_current_state()
        await self._write_current_state(current_state)
        self._client_remote_object.state_changed.connect(self._on_skill_state_change)


    @property
    @override
    def is_finite(self) -> bool:
        return self._client_remote_object.ua_type == "FiniteSkillType"

    @override
    @uamethod
    async def _ua_start(self, _parent: NodeId, session: SessionProtocol) -> ua.StatusCode | None:
        try:
            await self._condition_access_allowed(session.user)
            await self.start()
        except ua.UaStatusCodeError as e:
            return ua.StatusCode(e.code)

    @override
    @uamethod
    async def _ua_suspend(self, _parent: NodeId, session: SessionProtocol) -> ua.StatusCode | None:
        try:
            await self._condition_access_allowed(session.user)
            await self.suspend()
        except ua.UaStatusCodeError as e:
            return ua.StatusCode(e.code)

    @override
    @uamethod
    async def _ua_reset(self, _parent: NodeId, session: SessionProtocol) -> ua.StatusCode | None:
        try:
            await self._condition_access_allowed(session.user)
            await self.reset()
        except ua.UaStatusCodeError as e:
            return ua.StatusCode(e.code)

    @override
    @uamethod
    async def _ua_halt(self, _parent: NodeId, session: SessionProtocol) -> ua.StatusCode | None:
        try:
            await self._condition_access_allowed(session.user)
            await self.halt()
        except ua.UaStatusCodeError as e:
            return ua.StatusCode(e.code)

    @override
    async def start(self) -> None:
        # subscription based copying is too slow
        # copy local parameters to remote parameters to ensure they are immediately available @ remote server
        self.logger.info("Copying local parameters before starting skill...")
        await self._copy_parameter_set_to_remote()
        await self._client_remote_object.start()

    @override
    async def suspend(self) -> None:
        await self._client_remote_object.suspend()

    @override
    async def reset(self) -> None:
        await self._client_remote_object.reset()

    @override
    async def halt(self) -> None:
        await self._client_remote_object.halt()

    async def _on_skill_state_change(self, remote_skill: ClientRemoteSkill, new_state: Sample[SkillState]) -> None:
        assert self._client_remote_object == remote_skill
        await self._write_current_state(remote_skill.current_state)  # never None, unlike new_state.value
