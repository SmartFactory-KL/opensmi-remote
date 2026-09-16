# SPDX-FileCopyrightText: 2026 OpenSMI Contributors
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from opensmi.client.remote_method import RemoteMethod as ClientRemoteMethod
from opensmi.server.base_method import BaseMethod
from typing_extensions import override

from opensmi.remote.remote_mirror import (
    RemoteFinalResultUpdateMixin,
    RemoteMonitoringUpdateMixin,
    RemoteParameterMirrorMixin,
)


class RemoteMethod(
    BaseMethod,
    RemoteParameterMirrorMixin,
    RemoteMonitoringUpdateMixin,
    RemoteFinalResultUpdateMixin
):

    def __init__(self, *,
                 name: str,
                 client_remote_method: ClientRemoteMethod,
                 minimum_access_level: int = 1,
    )-> None:
        assert client_remote_method is not None, "No RemoteMethod from Client given!"
        self._client_remote_object: ClientRemoteMethod = client_remote_method

        super().__init__(name=name, minimum_access_level=minimum_access_level)


    @override
    async def _init(self) -> None:
        await super()._init()

        await self._init_monitoring_mirror()
        await self._init_parameter_set_mirror()
        await self._init_final_result_data_mirror()


    @override
    async def execute_method(self) -> None:
        # subscription based mirroring is too slow, explicit copying is required!
        await self._copy_parameter_set_to_remote()
        await self._client_remote_object.call()
        await self._copy_final_result_data_from_remote()
