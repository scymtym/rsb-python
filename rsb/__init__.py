# ============================================================
#
# Copyright (C) 2010 by Johannes Wienke <jwienke at techfak dot uni-bielefeld dot de>
#
# This program is free software; you can redistribute it
# and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation;
# either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# ============================================================

import uuid
import copy
import logging
import threading
import time
from rsb.util import getLoggerByClass, OrderedQueueDispatcherPool, Enum
import re
import os
import ConfigParser
from rsb.filter import ScopeFilter

class QualityOfServiceSpec(object):
    '''
    Specification of desired quality of service settings for sending and
    receiving events. Specification given here are required "at least". This
    means concrete port instances can implement "better" QoS specs without any
    notification to the clients. Better is decided by the integer value of the
    specification enums. Higher values mean better services.

    @author: jwienke
    '''

    Ordering = Enum("Ordering", ["UNORDERED", "ORDERED"], [10, 20])
    Reliability = Enum("Reliability", ["UNRELIABLE", "RELIABLE"], [10, 20])

    def __init__(self, ordering=Ordering.UNORDERED, reliability=Reliability.RELIABLE):
        '''
        Constructs a new QoS specification with desired details. Defaults are
        unordered but reliable.

        @param ordering: desired ordering type
        @param reliability: desired reliability type
        '''
        self.__ordering = ordering
        self.__reliability = reliability

    def getOrdering(self):
        '''
        Returns the desired ordering settings.

        @return: ordering settings
        '''

        return self.__ordering

    def setOrdering(self, ordering):
        '''
        Sets the desired ordering settings

        @param ordering: ordering to set
        '''

        self.__ordering = ordering

    ordering = property(getOrdering, setOrdering)

    def getReliability(self):
        '''
        Returns the desired reliability settings.

        @return: reliability settings
        '''

        return self.__reliability

    def setReliability(self, reliability):
        '''
        Sets the desired reliability settings

        @param reliability: reliability to set
        '''

        self.__reliability = reliability

    reliability = property(getReliability, setReliability)

    def __eq__(self, other):
        try:
            return other.__reliability == self.__reliability and other.__ordering == self.__ordering
        except (AttributeError, TypeError):
            return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def __repr__(self):
        return "%s(%r, %r)" % (self.__class__.__name__, self.__ordering, self.__reliability)

class ParticipantConfig (object):
    '''
    Objects of this class describe desired configurations for newly
    created participants with respect to:
    - Quality of service settings
    - Error handling strategies (not currently used)
    - Employed transport mechanisms
      - Their configurations (e.g. port numbers)
      - Associated converters

    @author: jmoringe
    '''

    class Transport (object):
        '''
        Objects of this class describe configurations of transports
        connectors. These consist of
        - Transport name
        - Enabled vs. Disabled
        - Optional converter selection
        - Transport-specific options

        @author: jmoringe
        '''
        def __init__(self, name, options={}):
            import rsb.transport.converter
            self.__name = name
            self.__enabled = options.get('enabled', '0') in ('1', 'true', 'yes')

            # Obtain a consistent converter set for the wire-type of
            # the transport:
            # 1. Find global converter map for the wire-type
            # 2. Find configuration options that specify converters
            #    for the transport
            # 3. Add converters from the global map to the unambiguous
            #    map of the transport, resolving conflicts based on
            #    configuration options when necessary
            wireType = bytearray
            self.__converters = rsb.transport.converter.UnambiguousConverterMap(wireType)
            # Find and transform configuration options
            converterOptions = dict([ (key[17:], value) for (key, value) in options.items()
                                      if key.startswith('converter.python') ])
            # Try to add converters form global map
            globalMap = rsb.transport.converter.getGlobalConverterMap(wireType)
            for ((wireSchema, dataType), converter) in globalMap.getConverters().items():
                # Converter can be added if converterOptions does not
                # contain a disambiguation that gives precedence to a
                # different converter. map may still raise an
                # exception in case of ambiguity.
                if not wireSchema in converterOptions \
                        or dataType.__name__ == converterOptions[wireSchema]:
                    self.__converters.addConverter(converter)

            # Extract freestyle options for the transport.
            self.__options = dict([ (key, value) for (key, value) in options.items()
                                   if not '.' in key and not key == 'enabled' ])

        def getName(self):
            return self.__name

        def isEnabled(self):
            return self.__enabled

        def getConverters(self):
            return self.__converters

        def getOptions(self):
            return self.__options

        def __str__(self):
            return ('ParticipantConfig.Transport[%s, enabled = %s,  converters = %s, options = %s]'
                    % (self.__name, self.__enabled, self.__converters, self.__options))

        def __repr__(self):
            return str(self)

    def __init__(self, transports={}, options={}, qos=QualityOfServiceSpec()):
        self.__transports = transports
        self.__options = options
        self.__qos = qos

    def getTransports(self, includeDisabled=False):
        return [ t for t in self.__transports.values()
                 if includeDisabled or t.isEnabled() ]

    def getTransport(self, name):
        return self.__transports[name]

    def getQualityOfServiceSpec(self):
        return self.__qos

    def __str__(self):
        return 'ParticipantConfig[%s %s]' % (self.__transports.values(), self.__options)

    def __repr__(self):
        return str(self)

    @classmethod
    def __fromDict(clazz, options):
        def sectionOptions(section):
            return [ (key[len(section) + 1:], value) for (key, value) in options.items()
                     if key.startswith(section) ]
        result = ParticipantConfig()

        # Quality of service
        qosOptions = dict(sectionOptions('qualityofservice'))
        result.__qos.setReliability(QualityOfServiceSpec.Reliability.fromString(qosOptions.get('reliability', QualityOfServiceSpec().getReliability().__str__())))
        result.__qos.setOrdering(QualityOfServiceSpec.Ordering.fromString(qosOptions.get('ordering', QualityOfServiceSpec().getOrdering().__str__())))

        # Transport options
        for transport in [ 'spread' ]:
            options = dict(sectionOptions('transport.%s' % transport))
            result.__transports[transport] = clazz.Transport(transport, options)
        return result

    @classmethod
    def __fromFile(clazz, path, defaults={}):
        parser = ConfigParser.RawConfigParser()
        parser.read(path)
        options = defaults
        for section in parser.sections():
            for (k, v) in parser.items(section):
                options[section + '.' + k] = v.split('#')[0].strip()
        return options

    @classmethod
    def fromDict(clazz, options):
        return clazz.__fromDict(options)

    @classmethod
    def fromFile(clazz, path, defaults={}):
        '''
        Obtain configuration options from the configuration file
        B{path}, store them in a L{ParticipantConfig} object and
        return it.

        A simple configuration file may look like this::

        [transport.spread]
        host = azurit # default type is string
        port = 5301 # types can be specified in angle brackets
        # A comment

        @param path: File of path
        @param defaults:  defaults
        @return: A new ParticipantConfig object containing the options
                 read from B{path}.

        See also L{fromEnvironment}, L{fromDefaultSources}
        '''
        return clazz.__fromDict(clazz.__fromFile(path, defaults))

    @classmethod
    def __fromEnvironment(clazz, defaults={}):
        options = defaults
        for (key, value) in os.environ.items():
            if key.startswith('RSB_'):
                options[key[4:].lower().replace('_', '.')] = value
        return options

    @classmethod
    def fromEnvironment(clazz, defaults={}):
        '''
        Obtain configuration options from environment variables, store
        them in a B{ParticipantConfig} object and return
        it. Environment variable names are mapped to RSB option names
        as illustrated in the following example::

        RSB_TRANSPORT_SPREAD_PORT -> transport spread port

        @param defaults: A L{ParticipantConfig} object that supplies
                         values for configuration options for which no
                         environment variables are found.
        @return: L{ParticipantConfig} object that contains the merged
                 configuration options from B{defaults} and relevant
                 environment variables.

        See also: L{fromFile}, L{fromDefaultSources}
        '''
        return clazz.__fromDict(clazz.__fromEnvironment(defaults))

    @classmethod
    def fromDefaultSources(clazz, defaults={}):
        '''
        Obtain configuration options from multiple sources, store them
        in a L{ParticipantConfig} object and return it. The following
        sources of configuration information will be consulted:

        1. ~/.config/rsb.conf
        2. \$(PWD)/rsb.conf
        3. Environment Variables

        @param defaults: A L{ParticipantConfig} object the options of
                         which should be used as defaults.
        @return: A L{ParticipantConfig} object that contains the
                 merged configuration options from the sources
                 mentioned above.

        @see fromFile, fromEnvironment
        '''
        partial = clazz.__fromFile(os.path.expanduser("~/.config/rsb.conf"))
        partial = clazz.__fromFile("rsb.conf", partial)
        options = clazz.__fromEnvironment(partial)
        return clazz.__fromDict(options)

class Scope(object):
    '''
    A scope defines a channel of the hierarchical unified bus covered by RSB.
    It is defined by a surface syntax like "/a/deep/scope".

    @author: jwienke
    '''

    __COMPONENT_SEPARATOR = "/"
    __COMPONENT_REGEX = re.compile("^[a-zA-Z0-9]+$")

    @classmethod
    def ensureScope(cls, thing):
        if isinstance(thing, cls):
            return thing
        else:
            return Scope(thing)

    def __init__(self, stringRep):
        '''
        Parses a scope from a string representation.

        @param stringRep: string representation of the scope
        @raise ValueError: if B{stringRep} does not have the right
                           syntax
        '''

        if len(stringRep) == 0:
            raise ValueError("Empty scope is invalid.")

        # append missing trailing slash
        if stringRep[-1] != self.__COMPONENT_SEPARATOR:
            stringRep += self.__COMPONENT_SEPARATOR

        rawComponents = stringRep.split(self.__COMPONENT_SEPARATOR)
        if len(rawComponents) < 1:
            raise ValueError("Empty scope is not allowed.")
        if len(rawComponents[0]) != 0:
            raise ValueError("Scope must start with a slash. Given was '%s'." % stringRep)
        if len(rawComponents[-1]) != 0:
            raise ValueError("Scope must end with a slash. Given was '%s'." % stringRep)

        self.__components = rawComponents[1:-1]

        for com in self.__components:
            if not self.__COMPONENT_REGEX.match(com):
                raise ValueError("Invalid character in component %s. Given was scope '%s'." % (com, stringRep))

    def getComponents(self):
        '''
        Returns all components of the scope as an ordered list. Components are
        the names between the separator character '/'. The first entry in the
        list is the highest level of hierarchy. The scope '/' returns an empty
        list.

        @return: components of the represented scope as ordered list with highest
                 level as first entry
        @rtype: list
        '''
        return copy.copy(self.__components)

    def toString(self):
        '''
        Reconstructs a fully formal string representation of the scope with
        leading an trailing slashes.

        @return: string representation of the scope
        @rtype: string
        '''

        string = self.__COMPONENT_SEPARATOR
        for com in self.__components:
            string += com
            string += self.__COMPONENT_SEPARATOR
        return string

    def concat(self, childScope):
        '''
        Creates a new scope that is a sub-scope of this one with the subordinated
        scope described by the given argument. E.g. "/this/is/".concat("/a/test/")
        results in "/this/is/a/test".

        @param childScope: child to concatenate to the current scope for forming a
                           sub-scope
        @type childScope: Scope
        @return: new scope instance representing the created sub-scope
        @rtype: Scope
        '''
        newScope = Scope("/")
        newScope.__components = copy.copy(self.__components)
        newScope.__components += childScope.__components
        return newScope

    def isSubScopeOf(self, other):
        '''
        Tests whether this scope is a sub-scope of the given other scope, which
        means that the other scope is a prefix of this scope. E.g. "/a/b/" is a
        sub-scope of "/a/".

        @param other: other scope to test
        @type other: Scope
        @return: C{True} if this is a sub-scope of the other scope, equality gives
                 C{False}, too
        @rtype: Bool
        '''

        if len(self.__components) <= len(other.__components):
            return False

        return other.__components == self.__components[:len(other.__components)]

    def isSuperScopeOf(self, other):
        '''
        Inverse operation of #isSubScopeOf.

        @param other: other scope to test
        @type other: Scope
        @return: C{True} if this scope is a strict super scope of the other scope.
                 equality also gives C{False}.
        @rtype: Bool
        '''

        if len(self.__components) >= len(other.__components):
            return False

        return self.__components == other.__components[:len(self.__components)]

    def superScopes(self, includeSelf=False):
        '''
        Generates all super scopes of this scope including the root scope "/".
        The returned list of scopes is ordered by hierarchy with "/" being the
        first entry.

        @param includeSelf: if set to C{true}, this scope is also included as last
                            element of the returned list
        @type includeSelf: Bool
        @return: list of all super scopes ordered by hierarchy, "/" being first
        @rtype: list of Scopes
        '''

        supers = []

        maxIndex = len(self.__components)
        if not includeSelf:
            maxIndex -= 1
        for i in range(maxIndex + 1):
            super = Scope("/")
            super.__components = self.__components[:i]
            supers.append(super)

        return supers

    def __eq__(self, other):
        return self.__components == other.__components

    def __ne__(self, other):
        return not self.__eq__(other)

    def __lt__(self, other):
        return self.toString() < other.toString()

    def __le__(self, other):
        return self.toString() <= other.toString()

    def __gt__(self, other):
        return self.toString() > other.toString()

    def __ge__(self, other):
        return self.toString() >= other.toString()

    def __str__(self):
        return "Scope[%s]" % self.toString()

    def __repr__(self):
        return '%s("%s")' % (self.__class__.__name__, self.toString())

class MetaData (object):
    """
    Objects of this class store RSB-specific and user-supplied
    meta-data items such as timing information.

    @author: jmoringe
    """
    def __init__(self,
                 senderId=None,
                 createTime=None, sendTime=None, receiveTime=None, deliverTime=None,
                 userTimes=None, userInfos=None):
        """
        Constructs a new L{MetaData} object.

        @param createTime: A timestamp designating the time at which
                           the associated event was created.
        @param sendTime: A timestamp designating the time at which the
                         associated event was sent onto the bus.
        @param receiveTime: A timestamp designating the time at which
                            the associated event was received from the
                            bus.
        @param deliverTime: A timestamp designating the time at which
                            the associated event was delivered to the
                            user-level handler by RSB.
        @param userTimes: A dictionary of user-supplied timestamps.
        @param userInfos: A dictionary of user-supplied meta-data
                          items.
        """
        if createTime is None:
            self.__createTime = time.time()
        else:
            self.__createTime = createTime
        self.__sendTime = sendTime
        self.__receiveTime = receiveTime
        self.__deliverTime = deliverTime
        if userTimes == None:
            self.__userTimes = {}
        else:
            self.__userTimes = userTimes
        if userInfos == None:
            self.__userInfos = {}
        else:
            self.__userInfos = userInfos

    def getCreateTime(self):
        return self.__createTime

    def setCreateTime(self, createTime=None):
        if createTime == None:
            self.__createTime = time.time()
        else:
            self.__createTime = createTime

    createTime = property(getCreateTime, setCreateTime)

    def getSendTime(self):
        return self.__sendTime

    def setSendTime(self, sendTime=None):
        if sendTime == None:
            self.__sendTime = time.time()
        else:
            self.__sendTime = sendTime

    sendTime = property(getSendTime, setSendTime)

    def getReceiveTime(self):
        return self.__receiveTime

    def setReceiveTime(self, receiveTime=None):
        if receiveTime == None:
            self.__receiveTime = time.time()
        else:
            self.__receiveTime = receiveTime

    receiveTime = property(getReceiveTime, setReceiveTime)

    def getDeliverTime(self):
        return self.__deliverTime

    def setDeliverTime(self, deliverTime=None):
        if deliverTime == None:
            self.__deliverTime = time.time()
        else:
            self.__deliverTime = deliverTime

    deliverTime = property(getDeliverTime, setDeliverTime)

    def getUserTimes(self):
        return self.__userTimes

    def setUserTimes(self, userTimes):
        self.__userTimes = userTimes

    def setUserTime(self, key, timestamp=None):
        if timestamp == None:
            self.__userTimes[key] = time.time()
        else:
            self.__userTimes[key] = timestamp

    userTimes = property(getUserTimes, setUserTimes)

    def getUserInfos(self):
        return self.__userInfos

    def setUserInfos(self, userInfos):
        self.__userInfos = userInfos

    def setUserInfo(self, key, value):
        self.__userInfos[key] = value

    userInfos = property(getUserInfos, setUserInfos)

    def __eq__(self, other):
        try:
            return (self.__createTime == other.__createTime) and (self.__sendTime == other.__sendTime) and (self.__receiveTime == other.__receiveTime) and (self.__deliverTime == other.__deliverTime) and (self.__userInfos == other.__userInfos) and (self.__userTimes == other.__userTimes)
        except (TypeError, AttributeError):
            return False

    def __neq__(self, other):
        return not self.__eq__(other)

    def __str__(self):
        return '%s[create = %s, send = %s, receive = %s, deliver = %s, userTimes = %s, userInfos = %s]' \
            % ('MetaData',
               self.__createTime, self.__sendTime, self.__receiveTime, self.__deliverTime,
               self.__userTimes, self.__userInfos)

    def __repr__(self):
        return self.__str__()

class Event(object):
    '''
    Basic event class.

    @author: jwienke
    '''

    def __init__(self, sequenceNumber = None, scope = Scope("/"), senderId = None,
                 data = None, type = None,
                 metaData=None, userInfos=None, userTimes=None):
        """
        Constructs a new event with undefined type, root scope and no data.

        @param senderId: The id of the participant at which the
                         associated event originated.
        """

        self.__id = None # computed lazily
        self.__sequenceNumber = sequenceNumber
        self.__scope = scope
        self.__senderId = senderId
        self.__data = data
        self.__type = type
        if metaData is None:
            self.__metaData = MetaData()
        else:
            self.__metaData = metaData
        if not userInfos is None:
            for (key, value) in userInfos.items():
                self.__metaData.getUserInfos()[key] = value
        if not userTimes is None:
            for (key, value) in userTimes.items():
                self.__metaData.getUserTimes()[key] = value

    def getSequenceNumber(self):
        """
        Return the sequence number of this event.

        @return: sequence number of the event.
        """
        return self.__sequenceNumber

    def setSequenceNumber(self, sequenceNumber):
        """
        Sets the sequence number of this event.

        @param sequenceNumber: new sequence number of the event.
        """
        self.__sequenceNumber = sequenceNumber

    sequenceNumber = property(getSequenceNumber, setSequenceNumber)

    def getId(self):
        """
        Returns the id of this event.

        @return: id of the event
        """

        if self.__id is None:
            self.__id = uuid.uuid5(self.__senderId,
                                   '%08x' % self.__sequenceNumber)
        return self.__id

    id = property(getId)

    def getScope(self):
        """
        Returns the scope of this event.

        @return: scope
        """

        return self.__scope

    def setScope(self, scope):
        """
        Sets the scope of this event.

        @param scope: scope to set
        """

        self.__scope = scope

    scope = property(getScope, setScope)

    def getSenderId(self):
        """
        Return the sender id of this event.

        @return: sender id
        """
        return self.__senderId

    def setSenderId(self, senderId):
        """
        Sets the sender id of this event.

        @param senderId: sender id to set.
        """
        self.__senderId = senderId

    senderId = property(getSenderId, setSenderId)


    def getData(self):
        """
        Returns the user data of this event.

        @return: user data
        """

        return self.__data

    def setData(self, data):
        """
        Sets the user data of this event

        @param data: user data
        """

        self.__data = data

    data = property(getData, setData)

    def getType(self):
        """
        Returns the type of the user data of this event.

        @return: user data type
        """

        return self.__type

    def setType(self, type):
        """
        Sets the type of the user data of this event

        @param type: user data type
        """

        self.__type = type

    type = property(getType, setType)

    def getMetaData(self):
        return self.__metaData

    def setMetaData(self, metaData):
        self.__metaData = metaData

    metaData = property(getMetaData, setMetaData)

    def __str__(self):
        printData = self.__data
        if isinstance(self.__data, str) and len(self.__data) > 10000:
            printData = "string with length %u" % len(self.__data)
        maybeId = 'N/A'
        if not self.__sequenceNumber is None and not self.__senderId is None:
            maybeId = self.getId()
        return "%s[id = %s, sequenceNumber = %s, scope = '%s', sender = %s, data = '%s', type = '%s', metaData = %s]" \
            % ("Event", maybeId, self.__sequenceNumber, self.__scope, self.__senderId, printData, self.__type, self.__metaData)

    def __repr__(self):
        return self.__str__()

    def __eq__(self, other):
        try:
            return (self.__sequenceNumber == other.__sequenceNumber) and (self.__scope == other.__scope) and (self.__senderId == other.__senderId) and (self.__type == other.__type) and (self.__data == other.__data) and (self.__metaData == other.__metaData)
        except (TypeError, AttributeError):
            return False

    def __neq__(self, other):
        return not self.__eq__(other)

class Participant(object):
    """
    Base class for specialized bus participant classes. Has a unique
    id and a scope.

    @author: jmoringe
    """
    def __init__(self, scope):
        """
        Constructs a new Participant. This should not be done by
        clients.

        @param scope: scope of the bus channel.
        """
        self.__id = uuid.uuid4()
        self.__scope = scope

    def getId(self):
        return self.__id

    def setId(self, id):
        self.__id = id

    id = property(getId, setId)

    def getScope(self):
        return self.__scope

    def setScope(self, scope):
        self.__scope = scope

    scope = property(getScope, setScope)

class Informer(Participant):
    """
    Event-sending part of the communication pattern.

    @author: jwienke
    """

    def __init__(self, scope, type,
                 config=ParticipantConfig.fromDefaultSources(),
                 router=None):
        """
        Constructs a new Informer.

        @param scope: scope of the informer
        @param router: router object with open outgoing port for communication
        @param type: type identifier string
        @todo: maybe provide an automatic type identifier deduction for default
               types?
        """
        super(Informer, self).__init__(scope)

        from rsbspread import SpreadPort
        from eventprocessing import Router

        self.__logger = getLoggerByClass(self.__class__)

        if router:
            self.__router = router
        else:
            transport = config.getTransport('spread')
            port = SpreadPort(converterMap=transport.getConverters(),
                              options=transport.getOptions())
            port.setQualityOfServiceSpec(config.getQualityOfServiceSpec())
            self.__router = Router(outPort=port)
        self.__router.setQualityOfServiceSpec(config.getQualityOfServiceSpec())
        # TODO check that type can be converted
        self.__type = type

        self.__sequenceNumber = 0

        self.__active = False
        self.__mutex = threading.Lock()

        self.__activate()

    def __del__(self):
        self.__logger.debug("Destructing Informer")
        self.deactivate()

    def getType(self):
        """
        Returns the type of data sent by this informer.

        @return: type of sent data
        """
        return self.__type

    def publishData(self, data, userInfos=None, userTimes=None):
        # TODO check activation
        self.__logger.debug("Publishing data '%s'" % data)
        event = Event(userInfos=userInfos, userTimes=userTimes)
        event.setData(data)
        event.setScope(self.getScope())
        event.setType(self.__type)
        return self.publishEvent(event)

    def publishEvent(self, event):
        """
        Publishes a predefined event. The caller must ensure that the event has
        the appropriate scope and type according to the Informer's settings.

        @param event: the event to send
        @type event: Event
        """
        # TODO check activation

        if not event.scope == self.getScope():
            raise ValueError("Scope %s of the event does not match this informer's scope %s." % (event.scope, self.getScope()))
        if not event.type == self.__type:
            raise ValueError("Type %s of the event does not match this informer's type %s." % (event.type, self.__type))

        with self.__mutex:
            event.sequenceNumber = self.__sequenceNumber
            self.__sequenceNumber += 1
        event.senderId = self.id
        self.__logger.debug("Publishing event '%s'" % event)
        self.__router.publish(event)
        return event

    def __activate(self):
        with self.__mutex:
            if not self.__active:
                self.__router.activate()
                self.__active = True
                self.__logger.info("Activated informer")
            else:
                self.__logger.info("Activate called even though informer was already active")

    def deactivate(self):
        with self.__mutex:
            if self.__active:
                self.__router.deactivate()
                self.__active = False
                self.__logger.info("Deactivated informer")
            else:
                self.__logger.info("Deactivate called even though informer was not active")

class Listener(Participant):
    """
    Event-receiving part of the communication pattern

    @author: jwienke
    """

    def __init__(self, scope,
                 config=ParticipantConfig.fromDefaultSources(),
                 router=None):
        """
        Create a new listener for the specified scope.

        @param scope: scope to subscribe one
        @param router: router with existing inport
        """
        super(Listener, self).__init__(scope)

        from rsbspread import SpreadPort
        from eventprocessing import Router

        self.__logger = getLoggerByClass(self.__class__)

        if router:
            self.__router = router
        else:
            transport = config.getTransport('spread')
            port = SpreadPort(converterMap=transport.getConverters(),
                              options=transport.getOptions())
            port.setQualityOfServiceSpec(config.getQualityOfServiceSpec())
            self.__router = Router(inPort=port)

        self.__mutex = threading.Lock()
        self.__active = False

        self.__filters = []
        self.__handlers = []

        self.__activate()
        self.__router.filterAdded(ScopeFilter(self.scope))

    def __del__(self):
        self.deactivate()

    def __activate(self):
        # TODO commonality with Informer... refactor
        with self.__mutex:
            if not self.__active:
                self.__router.activate()
                self.__active = True
                self.__logger.info("Activated listener")
            else:
                self.__logger.info("Activate called even though listener was already active")

    def deactivate(self):
        with self.__mutex:
            if self.__active:
                self.__router.deactivate()
                self.__active = False
                self.__logger.info("Deactivated listener")
            else:
                self.__logger.info("Deactivate called even though listener was not active")

    def addFilter(self, filter):
        """
        Appends a filter to restrict the events received by this listener.

        @param filter: filter to add
        """

        with self.__mutex:
            self.__filters.append(filter)
            self.__router.filterAdded(filter)

    def getFilters(self):
        """
        Returns all registered filters of this listener.

        @return: list of filters
        """

        with self.__mutex:
            return list(self.__filters)

    def addHandler(self, handler, wait=True):
        """
        Adds B{handler} to the list of handlers this listener invokes
        for received events.

        @param handler: Handler to add. callable with one argument,
                        the event.
        @param wait: If set to C{True}, this method will return only
                     after the handler has completely been installed
                     and will receive the next available
                     message. Otherwise it may return earlier.
        """

        with self.__mutex:
            if not handler in self.__handlers:
                self.__handlers.append(handler)
                self.__router.handlerAdded(handler, wait)

    def removeHandler(self, handler, wait=True):
        """
        Removes B{handler} from the list of handlers this listener
        invokes for received events.

        @param handler: Handler to remove.
        @param wait: If set to C{True}, this method will return only
                     after the handler has been completely removed
                     from the event processing and will not be called
                     anymore from this listener.
        """

        with self.__mutex:
            if handler in self.__handlers:
                self.__router.handlerRemoved(handler, wait)
                self.__handlers.remove(handler)

    def getHandlers(self):
        """
        Returns the list of all registered handlers.

        @return: list of handlers to execute on matches
        @rtype: list of callables accepting an Event
        """
        with self.__mutex:
            return list(self.__handlers)

__defaultParticipantConfig = ParticipantConfig.fromDefaultSources()

def getDefaultParticipantConfig():
    """
    Returns the current default configuration for new objects.
    """
    return __defaultParticipantConfig

def setDefaultParticipantConfig(config):
    """
    Replaces the default configuration for new objects.

    @param config: A ParticipantConfig object which contains the new defaults.
    """
    __defaultParticipantConfig = config

def createListener(scope, config=None):
    """
    Creates a new Listener for the specified scope.

    @param scope: the scope of the new Listener. Can be a Scope object or a string.
    @return: a new Listener object.
    """
    if config is None:
        config = __defaultParticipantConfig
    return Listener(Scope.ensureScope(scope), config)

def createInformer(scope, config=None, dataType=object):
    """
    Creates a new Informer in the specified scope.

    @param scope: The scope of the new Informer. Can be a Scope object
                  or a string.
    @param dataType: the string representation of the data type used
                     to select converters
    @return: a new Informer object.
    """
    if config is None:
        config = __defaultParticipantConfig
    return Informer(Scope.ensureScope(scope), dataType, config)

def createService(scope):
    """
    Creates a Service object operating on the given scope.
    @param scope: parent-scope of the new service. Can be a Scope
                  object or a string.
    @return: new Service object
    """
    raise RuntimeError, "not implemented"

def createServer(scope, object = None, expose = None, methods = None):
    """
    Create a new L{LocalServer} object that exposes its methods under
    B{scope}.

    The keyword parameters object, expose and methods can be used to
    associate an initial set of methods with the newly created server
    object.

    @param scope: The scope under which the newly created server
                  should expose its methods.
    @param object: An object the methods of which should be exposed
                   via the newly created server. Has to be supplied in
                   combination with the expose keyword parameter.
    @param expose: A list of names of attributes of object that should
                   be expose as methods of the newly created
                   server. Has to be supplied in combination with the
                   object keyword parameter.
    @param methods: A list or tuple of lists or tuples of the length four:
                    a method name,
                    a callable implementing the method,
                    a type designating the request type of the method and
                    a type designating the reply type of the method.
    @return: A newly created L{LocalServer} object.
    """
    # Check arguments
    if not object is None and not expose is None and not methods is None:
        raise ValueError, 'Supply either object and expose or methods'
    if object is None and not expose is None \
            or not object is None and expose is None:
        raise ValueError, 'object and expose have to supplied together'

    # Create the server object and potentially add methods.
    import rsb.patterns
    server = rsb.patterns.LocalServer(scope)
    if object and expose:
        methods = [ (name, getattr(object, name), requestType, replyType)
                    for (name, requestType, replyType) in expose ]
    if methods:
        for (name, func, requestType, replyType) in methods:
            server.addMethod(name, func, requestType, replyType)
    return server

def createRemoteServer(scope, timeout = 5):
    """
    Create a new L{RemoteServer} object for a remote server that
    provides its methods under B{scope}.

    @param scope: The scope under which the remote server provides its
                  methods.
    @param timeout: The amount of seconds to wait for calls to remote
                    methods to complete.
    @return: A newly created L{RemoteServer} object.
    """
    import rsb.patterns
    return rsb.patterns.RemoteServer(scope, timeout = timeout)
