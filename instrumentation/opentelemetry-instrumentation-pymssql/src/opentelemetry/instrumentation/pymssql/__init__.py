# Copyright The OpenTelemetry Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
The integration with pymssql supports the `pymssql`_ library and can be enabled
by using ``PyMSSQLInstrumentor``.

.. _pymssql: https://pypi.org/project/pymssql/

Usage
-----

.. code:: python

    import pymssql
    from opentelemetry.instrumentation.pymssql import PyMSSQLInstrumentor

    PyMSSQLInstrumentor().instrument()

    cnx = pymssql.connect(database="MSSQL_Database")
    cursor = cnx.cursor()
    cursor.execute("INSERT INTO test (testField) VALUES (123)"
    cnx.commit()
    cursor.close()
    cnx.close()

API
---
"""
import typing

import pymssql

from opentelemetry.instrumentation import dbapi
from opentelemetry.instrumentation.instrumentor import BaseInstrumentor
from opentelemetry.instrumentation.pymssql.version import __version__


class PyMSSQLConnectMethodArgsTuple(typing.NamedTuple):
    server: str = None
    user: str = None
    password: str = None
    database: str = None
    timeout: int = None
    login_timeout: int = None
    charset: str = None
    as_dict: bool = None
    host: str = None
    appname: str = None
    port: str = None
    conn_properties: str = None
    autocommit: bool = None
    tds_version: str = None


class PyMSSQLDatabaseApiIntegration(dbapi.DatabaseApiIntegration):
    def wrapped_connection(
        self,
        connect_method: typing.Callable[..., typing.Any],
        args: typing.Tuple[typing.Any, typing.Any],
        kwargs: typing.Dict[typing.Any, typing.Any],
    ):
        """Add object proxy to connection object."""
        connection = connect_method(*args, **kwargs)
        connect_method_args = PyMSSQLConnectMethodArgsTuple(*args)

        self.name = self.database_system
        self.database = kwargs.get("database") or connect_method_args.database

        user = kwargs.get("user") or connect_method_args.user
        if user is not None:
            self.span_attributes["db.user"] = user

        port = kwargs.get("port") or connect_method_args.port
        host = kwargs.get("server") or connect_method_args.server
        if host is None:
            host = kwargs.get("host") or connect_method_args.host
            if host is not None:
                # The host string can include the port, separated by either a coma or
                # a column
                for sep in (":", ","):
                    if sep in host:
                        tokens = host.rsplit(sep)
                        host = tokens[0]
                        if len(tokens) > 1:
                            port = tokens[1]
        if host is not None:
            self.span_attributes["net.peer.name"] = host
        if port is not None:
            self.span_attributes["net.peer.port"] = port

        charset = kwargs.get("charset") or connect_method_args.charset
        if charset is not None:
            self.span_attributes["db.charset"] = charset

        tds_version = (
            kwargs.get("tds_version") or connect_method_args.tds_version
        )
        if tds_version is not None:
            self.span_attributes["db.protocol.tds.version"] = tds_version

        return dbapi.get_traced_connection_proxy(connection, self)


class PyMSSQLInstrumentor(BaseInstrumentor):
    _DATABASE_SYSTEM = "mssql"

    def _instrument(self, **kwargs):
        """Integrate with the pymssql library.
        https://github.com/pymssql/pymssql/
        """
        tracer_provider = kwargs.get("tracer_provider")

        dbapi.wrap_connect(
            __name__,
            pymssql,
            "connect",
            self._DATABASE_SYSTEM,
            version=__version__,
            tracer_provider=tracer_provider,
            db_api_integration_factory=PyMSSQLDatabaseApiIntegration,
        )

    def _uninstrument(self, **kwargs):
        """"Disable pymssql instrumentation"""
        dbapi.unwrap_connect(pymssql, "connect")

    # pylint:disable=no-self-use
    def instrument_connection(self, connection):
        """Enable instrumentation in a pymssql connection.

        Args:
            connection: The connection to instrument.

        Returns:
            An instrumented connection.
        """

        return dbapi.instrument_connection(
            __name__,
            connection,
            self._DATABASE_SYSTEM,
            self._CONNECTION_ATTRIBUTES,
            version=__version__,
        )

    def uninstrument_connection(self, connection):
        """Disable instrumentation in a pymssql connection.

        Args:
            connection: The connection to uninstrument.

        Returns:
            An uninstrumented connection.
        """
        return dbapi.uninstrument_connection(connection)
