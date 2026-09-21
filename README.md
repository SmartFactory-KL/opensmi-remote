![OpenSMI Logo](https://smartfactory.de/wp-content/uploads/2026/09/Logo_OpenSMI.png)

# OpenSMI-Remote

`OpenSMI-Remote` is an [OpenSMI-Server](https://github.com/SmartFactory-KL/opensmi-server) extension for seamlessly
using remote Components, Skills, and other resources as if they were local.

The Remote machine's components and skills are wrapped in local proxy objects attached to your own machine,
so callers interacting with *your* server can't tell the difference between resources you implemented directly
and ones actually running on another server entirely.

This is useful for composing machines out of capabilities that live elsewhere — e.g. aggregating several
independent OpenSMI servers behind one unified machine, or building a higher-level orchestrating machine on top of
lower-level ones without re-implementing their skills.

## Requirements

- Python 3.11+
- An SMI-compliant OPC UA server to connect to (e.g. one built with
  [**OpenSMI-Server**](https://github.com/SmartFactory-KL/opensmi-server))

## Installation

```bash
pip install opensmi-remote
```

## Quick Start

```python
import asyncio

from asyncua import ua
from opensmi.client.auto_lock import AutoLock
from opensmi.client.remote_server import RemoteServer
from opensmi.server import BaseMachine, Server
from typing_extensions import override

from opensmi.remote import RemoteComponent, RemoteSkill

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
                name="RemoteComponent",
                client_remote_component=machine.components["DummyComponent"],
                recursive=False,  # change to True to recursively add all subcomponents and their skills
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
```

This connects `ExampleMachine` to a remote server's [
`DummyMachine`](https://github.com/SmartFactory-KL/opensmi-server/tree/main/examples/dummy)
, locks it, and wraps its `DummyComponent` as a local `RemoteComponent` — any client talking to *this* server can
browse and call into `RemoteComponent` exactly as if it were implemented locally.

## Project Status

`OpenSMI-Remote` is in beta: usable as-is, but API changes are still expected, and not all planned features are
implemented yet. It will not reach a 1.0 release before `OpenSMI-Server` itself reaches 1.0, since it builds
directly on the server's API.

## License

The library itself is licensed under the [MIT License](LICENSES/MIT.txt).

Example code contained in the [examples](examples) directory is dedicated to the public domain under
the [CC0 1.0 Universal license](LICENSES/CC0-1.0.txt).

---

*This text was drafted with AI assistance (Claude, Anthropic) and reviewed/edited by the author before
publication.*
