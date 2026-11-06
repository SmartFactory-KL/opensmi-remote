# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

"""A `RemoteComponent` mirrors a component of a real opensmi-server on a second opensmi-server."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
import pytest_asyncio
from asyncua import ua
from opensmi.client import AutoLock, RemoteServer
from opensmi.core import MachineryItemState, SkillState
from opensmi.server import (
    BaseComponent,
    BaseMachine,
    BaseMachineryItem,
    BaseSkillFinalResultData,
    BaseSkillFinite,
    Monitoring,
    Server,
    UaVariable,
)
from opensmi.server.common import reset_skill_and_wait
from opensmi.server.config import ServerConfiguration
from opensmi.server.mixins import FinalResultDataMixin, MonitoringMixin, NotificationForwarderMixin, ParentMixin
from typing_extensions import override

from opensmi.remote import RemoteComponent

pytestmark = pytest.mark.asyncio(loop_scope="module")


class _Skill(BaseSkillFinite):
    @override
    async def _handle_running(self) -> None:
        pass


class _CountingSkill(FinalResultDataMixin[BaseSkillFinalResultData], BaseSkillFinite):
    """Has SuccessfulExecutionsCount in its result data, like every finite skill of a pyuaadapter server."""

    @override
    async def _handle_running(self) -> None:
        pass


class _GripperMonitoring(Monitoring):
    Position = UaVariable(0.0)


class _Gripper(
    ParentMixin[BaseMachineryItem], MonitoringMixin[_GripperMonitoring], NotificationForwarderMixin, BaseComponent
):
    @override
    async def _write_identification(self) -> None:
        await self.identification.SerialNumber.write("gripper-1")
        await self.identification.Manufacturer.write(ua.LocalizedText("SCHUNK", "en"))

    @override
    async def _init(self) -> None:
        await super()._init()
        await self.add_skill(_Skill(name="Grip"))
        await self.add_skill(_CountingSkill(name="Count"))


class _Machine(BaseMachine):
    def __init__(self, *components: BaseComponent, name: str) -> None:
        super().__init__(name=name)
        self._own_components = components

    @override
    async def _write_identification(self) -> None:
        await self.identification.SerialNumber.write(f"{self.name}-1")
        await self.identification.ProductInstanceUri.write(f"urn:opensmi-remote:tests:{self.name}")
        await self.identification.Manufacturer.write(ua.LocalizedText("SmartFactory KL", "en"))

    @override
    async def _init(self) -> None:
        await super()._init()
        for component in self._own_components:
            await self.add_component(component)


def _config() -> ServerConfiguration:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    config = ServerConfiguration()
    config.ua_server.endpoint_address = f"opc.tcp://127.0.0.1:{port}/server"
    return config


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def setup() -> AsyncGenerator[tuple[_Machine, _Gripper, RemoteComponent, RemoteComponent]]:
    """Machine M1 with a gripper on one server, mirrors of both on another, connected through a client.

    Only machines have a MachineryItemState in opensmi-server, so the state is tested on the machine mirror.
    """
    source_config = _config()
    gripper = _Gripper(name="Gripper")
    machine = _Machine(gripper, name="M1")  # pyright: ignore[reportAbstractUsage]
    async with Server(config=source_config) as source:
        await source.add_machine(machine)
        await source.start(blocking=False)
        url = source_config.ua_server.endpoint_address
        async with RemoteServer(url, username="developer", password="developer", auto_reconnect=False) as remote:
            await AutoLock(remote.machines["M1"].lock).lock()
            mirror = RemoteComponent(
                name="Gripper", client_remote_component=remote.machines["M1"].components["Gripper"]
            )
            machine_mirror = RemoteComponent(name="M1", client_remote_component=remote.machines["M1"])
            async with Server(config=_config()) as server:
                mirror_machine = _Machine(mirror, machine_mirror, name="M2")  # pyright: ignore[reportAbstractUsage]
                await server.add_machine(mirror_machine)
                await server.start(blocking=False)
                yield machine, gripper, mirror, machine_mirror


async def _eventually(check: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(5):
        while not await check():  # noqa: ASYNC110  the mirror offers no event to wait for
            await asyncio.sleep(0.05)


async def test_mirror_copies_the_identification(setup) -> None:
    _, _, mirror, _ = setup
    assert await mirror.identification.SerialNumber.read() == "gripper-1"
    assert (await mirror.identification.Manufacturer.read()).Text == "SCHUNK"


async def test_reset_of_a_halted_mirrored_skill_waits_until_ready(setup) -> None:
    _, gripper, mirror, _ = setup
    assert mirror.skill_set["Grip"].current_state == SkillState.HALTED  # skills start halted
    await reset_skill_and_wait(mirror.skill_set["Grip"], timeout=5)
    assert gripper.skill_set["Grip"].current_state == SkillState.READY


async def test_mirror_follows_the_machinery_item_state(setup) -> None:
    machine, _, _, mirror = setup
    await machine.set_current_state(MachineryItemState.EXECUTING)

    async def is_executing() -> bool:
        return mirror.current_state == MachineryItemState.EXECUTING

    await _eventually(is_executing)


async def test_mirror_follows_monitoring_values(setup) -> None:
    _, gripper, mirror, _ = setup
    await gripper.monitoring.Position.write(5.0)

    async def is_mirrored() -> bool:
        return await mirror.monitoring["Position"].read() == 5.0

    await _eventually(is_mirrored)


async def test_mirrored_skill_follows_the_remote_result_data(setup) -> None:
    _, gripper, mirror, _ = setup
    await gripper.skill_set["Count"].final_result_data.SuccessfulExecutionsCount.write(7)

    async def is_mirrored() -> bool:
        return await mirror.skill_set["Count"].final_result_data["SuccessfulExecutionsCount"].read() == 7

    await _eventually(is_mirrored)
