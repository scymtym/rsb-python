# ============================================================
#
# Copyright (C) 2010 by Johannes Wienke <jwienke at techfak dot uni-bielefeld dot de>
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
# The development of this software was supported by:
#   CoR-Lab, Research Institute for Cognition and Robotics
#     Bielefeld University
#
# ============================================================

from threading import Condition
import time
import unittest
import uuid

import rsb
from rsb import Event, EventId
import rsb.eventprocessing
from rsb.eventprocessing import FullyParallelEventReceivingStrategy
from rsb.filter import RecordingFalseFilter, RecordingTrueFilter


class ScopeDispatcherTest(unittest.TestCase):

    def test_sinks(self):
        dispatcher = rsb.eventprocessing.ScopeDispatcher()
        dispatcher.add_sink(rsb.Scope('/foo'), 1)
        dispatcher.add_sink(rsb.Scope('/foo'), 2)
        dispatcher.add_sink(rsb.Scope('/bar'), 3)
        self.assertEqual(set((1, 2, 3)), set(dispatcher.sinks))

    def test_matching_sinks(self):
        dispatcher = rsb.eventprocessing.ScopeDispatcher()
        dispatcher.add_sink(rsb.Scope('/foo'), 1)
        dispatcher.add_sink(rsb.Scope('/foo'), 2)
        dispatcher.add_sink(rsb.Scope('/bar'), 3)

        def check(scope, expected):
            self.assertEqual(set(expected),
                             set(dispatcher.matching_sinks(rsb.Scope(scope))))
        check("/", ())
        check("/foo", (1, 2))
        check("/foo/baz", (1, 2))
        check("/bar", (3,))
        check("/bar/fez", (3,))


class ParallelEventReceivingStrategyTest(unittest.TestCase):

    def test_matching_process(self):
        ep = rsb.eventprocessing.ParallelEventReceivingStrategy(5)

        mc1_cond = Condition()
        matching_calls1 = []
        mc2_cond = Condition()
        matching_calls2 = []

        def matching_action1(event):
            with mc1_cond:
                matching_calls1.append(event)
                mc1_cond.notifyAll()

        def matching_action2(event):
            with mc2_cond:
                matching_calls2.append(event)
                mc2_cond.notifyAll()

        matching_recording_filter_1 = RecordingTrueFilter()
        matching_recording_filter_2 = RecordingTrueFilter()
        ep.add_filter(matching_recording_filter_1)
        ep.add_filter(matching_recording_filter_2)
        ep.add_handler(matching_action1, wait=True)
        ep.add_handler(matching_action2, wait=True)

        event1 = Event(EventId(uuid.uuid4(), 0))
        event2 = Event(EventId(uuid.uuid4(), 1))

        ep.handle(event1)
        ep.handle(event2)

        # both filters must have been called
        with matching_recording_filter_1.condition:
            while len(matching_recording_filter_1.events) < 4:
                matching_recording_filter_1.condition.wait()

            self.assertEqual(4, len(matching_recording_filter_1.events))
            self.assertTrue(event1 in matching_recording_filter_1.events)
            self.assertTrue(event2 in matching_recording_filter_1.events)

        with matching_recording_filter_2.condition:
            while len(matching_recording_filter_2.events) < 4:
                matching_recording_filter_2.condition.wait()

            self.assertEqual(4, len(matching_recording_filter_2.events))
            self.assertTrue(event1 in matching_recording_filter_2.events)
            self.assertTrue(event2 in matching_recording_filter_2.events)

        # both actions must have been called
        with mc1_cond:
            while len(matching_calls1) < 2:
                mc1_cond.wait()
            self.assertEqual(2, len(matching_calls1))
            self.assertTrue(event1 in matching_calls1)
            self.assertTrue(event2 in matching_calls1)

        with mc2_cond:
            while len(matching_calls2) < 2:
                mc2_cond.wait()
            self.assertEqual(2, len(matching_calls2))
            self.assertTrue(event1 in matching_calls2)
            self.assertTrue(event2 in matching_calls2)

        ep.remove_filter(matching_recording_filter_2)
        ep.remove_filter(matching_recording_filter_1)

    def test_not_matching_process(self):

        ep = rsb.eventprocessing.ParallelEventReceivingStrategy(5)

        no_matching_calls = []

        def no_matching_action(event):
            no_matching_calls.append(event)

        no_match_recording_filter = RecordingFalseFilter()
        ep.add_filter(no_match_recording_filter)
        ep.add_handler(no_matching_action, wait=True)

        event1 = Event(EventId(uuid.uuid4(), 0))
        event2 = Event(EventId(uuid.uuid4(), 1))
        event3 = Event(EventId(uuid.uuid4(), 2))

        ep.handle(event1)
        ep.handle(event2)
        ep.handle(event3)

        # no Match listener must not have been called
        with no_match_recording_filter.condition:
            while len(no_match_recording_filter.events) < 3:
                no_match_recording_filter.condition.wait()
            self.assertEqual(3, len(no_match_recording_filter.events))
            self.assertTrue(event1 in no_match_recording_filter.events)
            self.assertTrue(event2 in no_match_recording_filter.events)
            self.assertTrue(event3 in no_match_recording_filter.events)

        self.assertEqual(0, len(no_matching_calls))

        ep.remove_filter(no_match_recording_filter)

    def test_add_remove(self):
        for size in range(2, 10):
            ep = rsb.eventprocessing.ParallelEventReceivingStrategy(size)

            def h1(e): return e

            def h2(e): return e
            ep.add_handler(h1, wait=True)
            ep.add_handler(h2, wait=True)
            ep.add_handler(h1, wait=True)

            ep.handle(Event(EventId(uuid.uuid4(), 0)))
            ep.handle(Event(EventId(uuid.uuid4(), 1)))
            ep.handle(Event(EventId(uuid.uuid4(), 2)))

            ep.remove_handler(h1, wait=True)
            ep.remove_handler(h2, wait=True)
            ep.remove_handler(h1, wait=True)


class MockConnector(object):
    def activate(self):
        pass

    def deactivate(self):
        pass

    def push(self, event):
        pass

    def filter_notify(self, filter, action):
        pass

    def set_observer_action(self, action):
        pass


# TODO(jmoringe): could be useful in all tests for active objects
class ActivateCountingMockConnector(MockConnector):
    def __init__(self, case):
        self.__case = case
        self.activations = 0
        self.deactivations = 0

    def activate(self):
        self.activations += 1

    def deactivate(self):
        self.deactivations += 1

    def expect(self, activations, deactivations):
        self.__case.assertEqual(activations, self.activations)
        self.__case.assertEqual(deactivations, self.deactivations)


class OutRouteConfiguratorTest(unittest.TestCase):

    def test_activation(self):
        connector = ActivateCountingMockConnector(self)
        configurator = rsb.eventprocessing.OutRouteConfigurator(
            connectors=[connector])

        # Cannot deactivate inactive configurator
        self.assertRaises(RuntimeError, configurator.deactivate)
        connector.expect(0, 0)

        configurator.activate()
        connector.expect(1, 0)

        # Cannot activate already activated configurator
        self.assertRaises(RuntimeError, configurator.activate)
        connector.expect(1, 0)

        configurator.deactivate()
        connector.expect(1, 1)

        # Cannot deactivate twice
        self.assertRaises(RuntimeError, configurator.deactivate)
        connector.expect(1, 1)

    def test_publish(self):
        class RecordingOutConnector(MockConnector):
            last_event = None

            def handle(self, event):
                RecordingOutConnector.last_event = event

        configurator = rsb.eventprocessing.OutRouteConfigurator(
            connectors=[RecordingOutConnector()])

        event = 42

        # Cannot publish while inactive
        self.assertRaises(RuntimeError, configurator.handle, event)
        self.assertEqual(None, RecordingOutConnector.last_event)

        configurator.activate()
        configurator.handle(event)
        self.assertEqual(event, RecordingOutConnector.last_event)

        event = 34
        configurator.handle(event)
        self.assertEqual(event, RecordingOutConnector.last_event)

        # Deactivate and check exception, again
        RecordingOutConnector.last_event = None
        configurator.deactivate()
        self.assertRaises(RuntimeError, configurator.handle, event)
        self.assertEqual(None, RecordingOutConnector.last_event)


class InPushRouteConfiguratorTest(unittest.TestCase):

    def test_activation(self):
        connector = ActivateCountingMockConnector(self)
        configurator = rsb.eventprocessing.InPushRouteConfigurator(
            connectors=[connector])

        # Cannot deactivate inactive configurator
        self.assertRaises(RuntimeError, configurator.deactivate)
        connector.expect(0, 0)

        configurator.activate()
        connector.expect(1, 0)

        # Cannot activate already activated configurator
        self.assertRaises(RuntimeError, configurator.activate)
        connector.expect(1, 0)

        configurator.deactivate()
        connector.expect(1, 1)

        # Cannot deactivate twice
        self.assertRaises(RuntimeError, configurator.deactivate)
        connector.expect(1, 1)

    def test_notify_connector(self):
        class RecordingMockConnector(MockConnector):
            def __init__(self):
                self.calls = []

            def filter_notify(self, filter, action):
                self.calls.append((filter, action))

            def expect(self1, calls):  # noqa: N805
                self.assertEqual(len(calls), len(self1.calls))
                for (exp_filter, expAction), (filter, action) in \
                        zip(calls, self1.calls):
                    self.assertEqual(exp_filter, filter)
                    if expAction == 'add':
                        self.assertEqual(action, rsb.filter.FilterAction.ADD)

        connector = RecordingMockConnector()
        configurator = rsb.eventprocessing.InPushRouteConfigurator(
            connectors=[connector])
        configurator.activate()
        connector.expect(())

        f1, f2, f3 = 12, 24, 36
        configurator.filter_added(f1)
        connector.expect(((f1, 'add'),))

        configurator.filter_added(f2)
        connector.expect(((f1, 'add'), (f2, 'add')))

        configurator.filter_added(f3)
        connector.expect(((f1, 'add'), (f2, 'add'), (f3, 'add')))

        configurator.filter_removed(f3)
        connector.expect(((f1, 'add'), (f2, 'add'), (f3, 'add'),
                          (f3, 'remove')))


class FullyParallelEventReceivingStrategyTest(unittest.TestCase):

    class CollectingHandler(object):

        def __init__(self):
            self.condition = Condition()
            self.event = None

        def __call__(self, event):
            with self.condition:
                self.event = event
                self.condition.notifyAll()

    def test_smoke(self):

        strategy = FullyParallelEventReceivingStrategy()

        h1 = self.CollectingHandler()
        h2 = self.CollectingHandler()
        strategy.add_handler(h1, True)
        strategy.add_handler(h2, True)

        event = Event(id=42)
        strategy.handle(event)

        with h1.condition:
            while h1.event is None:
                h1.condition.wait()
            self.assertEqual(event, h1.event)

        with h2.condition:
            while h2.event is None:
                h2.condition.wait()
            self.assertEqual(event, h2.event)

    def test_filtering(self):

        strategy = FullyParallelEventReceivingStrategy()

        false_filter = RecordingFalseFilter()
        strategy.add_filter(false_filter)

        handler = self.CollectingHandler()
        strategy.add_handler(handler, True)

        event = Event(id=42)
        strategy.handle(event)

        with false_filter.condition:
            while len(false_filter.events) == 0:
                false_filter.condition.wait(timeout=5)
                if len(false_filter.events) == 0:
                    self.fail("Filter not called")

        time.sleep(1)

        with handler.condition:
            self.assertEqual(None, handler.event)

        strategy.remove_filter(false_filter)

    def test_parallel_call_of_one_handler(self):

        class Counter(object):
            def __init__(self):
                self.value = 0
        max_parallel_calls = Counter()
        current_calls = []
        call_lock = Condition()

        class Receiver(object):

            def __init__(self, counter):
                self.counter = counter

            def __call__(self, message):
                with call_lock:
                    current_calls.append(message)
                    self.counter.value = max(self.counter.value,
                                             len(current_calls))
                    call_lock.notifyAll()
                time.sleep(2)
                with call_lock:
                    current_calls.remove(message)
                    call_lock.notifyAll()

        strategy = FullyParallelEventReceivingStrategy()
        strategy.add_handler(Receiver(max_parallel_calls), True)

        event = Event(id=42)
        strategy.handle(event)
        event = Event(id=43)
        strategy.handle(event)
        event = Event(id=44)
        strategy.handle(event)

        num_called = 0
        with call_lock:
            while max_parallel_calls.value < 3 and num_called < 5:
                num_called = num_called + 1
                call_lock.wait()
            if num_called == 5:
                self.fail("Impossible to be called in parallel again")
            else:
                self.assertEqual(3, max_parallel_calls.value)
