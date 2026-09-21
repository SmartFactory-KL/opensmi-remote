# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: CC0-1.0

"""Demonstrates how a complete remote machine can be wrapped into a RemoteComponent."""

import asyncio

from asyncua import ua
from opensmi.client.auto_lock import AutoLock
from opensmi.client.remote_server import RemoteServer
from opensmi.server import BaseMachine, Server
from typing_extensions import override

from opensmi.remote import RemoteComponent

REMOTE_SERVER_URL = "opc.tcp://localhost:4843/"
REMOTE_USERNAME = "remote"
REMOTE_PASSWORD = "remote"


class ExampleMachine(BaseMachine):
    def __init__(self) -> None:
        super().__init__()
        self._auto_lock: AutoLock | None = None
        self._remote_server = RemoteServer(url=REMOTE_SERVER_URL, username=REMOTE_USERNAME, password=REMOTE_PASSWORD)

    @override
    async def _write_identification(self) -> None:
        # These identification variables must be set for machines
        await self.identification.SerialNumber.write("1234-56789-abc")
        await self.identification.ProductInstanceUri.write("urn:smartfactory.de-model:snr-1234-56789-abc")
        await self.identification.Manufacturer.write(
            ua.LocalizedText("Technologie-Initiative SmartFactory KL e. V.", "de-DE")
        )

    @override
    async def _init(self) -> None:
        await super()._init()

        await self._remote_server.connect(max_retries=None)  # unlimited retries
        machine = self._remote_server.machines["DummyMachine"]
        self._auto_lock = AutoLock(machine.lock)
        await self._auto_lock.lock()

        await self.add_component(
            RemoteComponent(
                name="RemoteMachine",
                client_remote_component=machine,  # remember, every machine is also a component!
                recursive=True,  # also recursively add all subcomponents and their skills
            )
        )

    @override
    async def _shutdown(self) -> None:
        await super()._shutdown()

        await self._remote_server.disconnect()


async def main() -> None:
    async with Server() as server:
        await server.add_machine(ExampleMachine())  # add machine(s)
        await server.start(blocking=True)  # start the server and block while it is running


if __name__ == "__main__":
    asyncio.run(main())
