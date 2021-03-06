# ============================================================
#
# Copyright (C) 2010 by Johannes Wienke
# Copyright (C) 2011-2017 Jan Moringen
#
# This file may be licensed under the terms of the
# GNU Lesser General Public License Version 3 (the ``LGPL''),
# or (at your option) any later version.
#
# Software distributed under the License is distributed
# on an ``AS IS'' basis, WITHOUT WARRANTY OF ANY KIND, either
# express or implied. See the LGPL for the specific language
# governing rights and limitations.
#
# You should have received a copy of the LGPL along with this
# program. If not, go to http://www.gnu.org/licenses/lgpl.html
# or write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ============================================================

"""
Contains the interface and bases classes for implementing RSB transports.

.. codeauthor:: jmoringe
.. codeauthor:: jwienke
"""

import abc
import threading

from rsb.util import get_logger_by_class


class Connector(metaclass=abc.ABCMeta):
    """
    Superclass for transport-specific connector classes.

    .. codeauthor:: jwienke
    """

    def __init__(self, wire_type=None, **kwargs):
        """
        Create a new connector with a serialization type wire_type.

        Args:
            wire_type (types.TypeType):
                the type of serialized data used by this connector.
        """
        self._logger = get_logger_by_class(self.__class__)

        self._wire_type = None
        self._scope = None

        if wire_type is None:
            raise ValueError("Wire type must be a type object, None given")

        self._logger.debug("Using specified converter map for wire-type %s",
                           wire_type)
        self._wire_type = wire_type

        # fails if still some arguments are left over
        super().__init__(**kwargs)

    @property
    def wire_type(self):
        """
        Return the serialization type used for this connector.

        Returns:
            python serialization type
        """
        return self._wire_type

    @property
    def scope(self):
        return self._scope

    @scope.setter
    def scope(self, new_value):
        """
        Set the scope this connector will receive events from.

        Called before #activate.

        Args:
            new_value (rsb.Scope):
                scope of the connector
        """
        self._scope = new_value

    @abc.abstractmethod
    def activate(self):
        pass

    @abc.abstractmethod
    def deactivate(self):
        pass

    @abc.abstractmethod
    def set_quality_of_service_spec(self, qos):
        pass


class InPushConnector(Connector):
    """
    Superclass for in-direction connectors that use asynchronous notification.

    .. codeauthor:: jmoringe
    """

    @abc.abstractmethod
    def filter_notify(self, filter_, action):
        pass

    @abc.abstractmethod
    def set_observer_action(self, action):
        """
        Set the action used by the connector to notify about incoming events.

        The call to this method must be thread-safe.

        Args:
            action:
                action called if a new message is received from the connector.
                Must accept an :obj:`Event` as parameter.
        """
        pass


class InPullConnector(Connector):
    """
    Superclass for connectors that receive events using a pull style.

    .. codeauthor:: jwienke
    """

    @abc.abstractmethod
    def raise_event(self, block):
        """
        Return the next received event.

        Args:
            block (bool):
                If ``True``, wait for the next event, else immediately return,
                possibly ``None``.
        Returns:
            rsb.Event or ``None``
                The next event or ``None`` if ``block`` is ``False``.
        """
        pass


class OutConnector(Connector):
    """
    Superclass for connectors sending events to the outside world.

    .. codeauthor:: jmoringe
    """

    @abc.abstractmethod
    def handle(self, event):
        """
        Send ``event`` and adapts its meta data with the actual send time.

        Args:
            event:
                event to send
        """
        pass


class ConverterSelectingConnector:
    """
    Base class for connectors that use a map of converters for serialization.

    This class is intended to be used a superclass (or rather mixin class) for
    connector classes which have to store a map of converters and select
    converters for (de)serialization.

    .. codeauthor:: jmoringe
    """

    def __init__(self, converters, **kwargs):
        """
        Create a new connector with the specified converters.

        The new converter uses the converters in ``converters`` to
        deserialize notification and/or serialize events.

        Args:
            converters (rsb.converter.ConverterSelectionStrategy):
                The converter selection strategy that should be used by the
                connector. If ``None``, the global map of converters for the
                wire-type of the connector is used.
        """
        self._converter_map = converters

        assert(self._converter_map.wire_type == self.wire_type)

    def get_converter_for_data_type(self, data_type):
        """
        Return a converter that converts the supplied data to the wire-type.

        Args:
            data_type:
                the type of the object for which a suitable converter should
                returned.

        Returns:
            converter

        Raises:
            KeyError:
                no converter is available for the supplied data.
        """
        return self._converter_map.get_converter_for_data_type(data_type)

    def get_converter_for_wire_schema(self, wire_schema):
        """
        Return a suitable converter for the ``wire_schema``.

        Args:
            wire_schema (str):
                the wire-schema to or from which the returned converter should
                convert

        Returns:
            converter

        Raises:
            KeyError:
                no converter is available for the specified wire-schema.

        """
        return self._converter_map.get_converter_for_wire_schema(wire_schema)

    @property
    def converter_map(self):
        return self._converter_map


class TransportFactory(metaclass=abc.ABCMeta):
    """Creates connectors for a specific transport."""

    @property
    @abc.abstractmethod
    def name(self):
        """
        Return the name representing this transport.

        Returns:
            str:
                name of the transport, non-empty
        """
        pass

    @property
    @abc.abstractmethod
    def remote(self):
        """
        Return ``true`` if the transport performs remote communication.

        Returns:
            bool:
                does the transport perform remote communication?
        """
        pass

    @abc.abstractmethod
    def create_in_push_connector(self, converters, options):
        """
        Create a new :obj:`InPushConnector` for the represented transport.

        Args:
            converters (ConverterSelectionStrategy):
                the converters to use for this type options(dict of str):
                options for the new connector

        Returns:
            rsb.transport.InPushConnector:
                the new connector instance
        """
        pass

    @abc.abstractmethod
    def create_in_pull_connector(self, converters, options):
        """
        Create a new :obj:`InPullConnector` for the represented transport.

        Args:
            converters (ConverterSelectionStrategy):
                the converters to use for this type
            options (dict of str):
                options for the new connector

        Returns:
            rsb.transport.InPullConnector:
                the new connector instance
        """
        pass

    @abc.abstractmethod
    def create_out_connector(self, converters, options):
        """
        Create a new :obj:`OutConnector` for the represented transport.

        Args:
            converters (ConverterSelectionStrategy):
                the converters to use for this type options(dict of str):
                options for the new connector

        Returns:
            rsb.transport.OutConnector:
                the new connector instance
        """
        pass


_factories_by_name = {}
_factory_lock = threading.Lock()


def register_transport(factory):
    """
    Register a new transport.

    Args:
        factory (rsb.transport.TransportFactory):
            the factory for the transport

    Raises:
        ValueError:
            there is already a transport registered with this name or the given
            factory argument is invalid

    """

    if factory is None:
        raise ValueError("None cannot be a TransportFactory")
    with _factory_lock:
        if factory.name in _factories_by_name:
            raise ValueError(
                "There is already a transport with name {name}".format(
                    name=factory.name))
        _factories_by_name[factory.name] = factory


def get_transport_factory(name):
    """
    Return a ``TransportFactory`` for the transport with the given name.

    Args:
        name (str):
            name of the transport

    Returns:
        rsb.transport.TransportFactory:
            the ``TransportFactory`` instance

    Raises:
        KeyError:
            there is not transport with the given name
    """
    with _factory_lock:
        return _factories_by_name[name]
