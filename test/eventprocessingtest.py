# ============================================================
#
# Copyright (C) 2010 by Johannes Wienke <jwienke at techfak dot uni-bielefeld dot de>
#
# This program is free software you can redistribute it
# and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation
# either version 2, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# ============================================================

import unittest
from rsb.eventprocessing import EventProcessor, Router
from threading import Condition
from rsb.filter import RecordingTrueFilter, RecordingFalseFilter
from rsb import Subscription, Event
import rsb

class EventProcessorTest(unittest.TestCase):

    def testProcess(self):

        ep = EventProcessor(5)

        mc1Cond = Condition()
        matchingCalls1 = []
        mc2Cond = Condition()
        matchingCalls2 = []

        def matchingAction1(event):
            with mc1Cond:
                matchingCalls1.append(event)
                mc1Cond.notifyAll()
        def matchingAction2(event):
            with mc2Cond:
                matchingCalls2.append(event)
                mc2Cond.notifyAll()

        matchingRecordingFilter1 = RecordingTrueFilter()
        matchingRecordingFilter2 = RecordingTrueFilter()
        matching = Subscription()
        matching.appendFilter(matchingRecordingFilter1)
        matching.appendFilter(matchingRecordingFilter2)
        matching.appendAction(matchingAction1)
        matching.appendAction(matchingAction2)

        noMatchCalls = []
        def noMatchAction(event):
            noMatchCalls.append(event)

        noMatch = Subscription()
        noMatchRecordingFilter = RecordingFalseFilter()
        noMatch.appendFilter(noMatchRecordingFilter)
        noMatch.appendAction(noMatchAction)

        event1 = Event()
        event2 = Event()
        event3 = Event()

        ep.subscribe(matching)
        ep.subscribe(noMatch)

        ep.process(event1)
        ep.process(event2)

        # both filters must have been called
        with matchingRecordingFilter1.condition:
            while len(matchingRecordingFilter1.events) < 2:
                matchingRecordingFilter1.condition.wait()

            self.assertEqual(2, len(matchingRecordingFilter1.events))
            self.assertTrue(event1 in matchingRecordingFilter1.events)
            self.assertTrue(event2 in matchingRecordingFilter1.events)

        with matchingRecordingFilter2.condition:
            while len(matchingRecordingFilter2.events) < 2:
                matchingRecordingFilter2.condition.wait()

            self.assertEqual(2, len(matchingRecordingFilter2.events))
            self.assertTrue(event1 in matchingRecordingFilter2.events)
            self.assertTrue(event2 in matchingRecordingFilter2.events)

        # both actions must have been called
        with mc1Cond:
            while len(matchingCalls1) < 2:
                mc1Cond.wait()
            self.assertEqual(2, len(matchingCalls1))
            self.assertTrue(event1 in matchingCalls1)
            self.assertTrue(event2 in matchingCalls1)

        with mc2Cond:
            while len(matchingCalls2) < 2:
                mc2Cond.wait()
            self.assertEqual(2, len(matchingCalls2))
            self.assertTrue(event1 in matchingCalls2)
            self.assertTrue(event2 in matchingCalls2)

        ep.unsubscribe(matching)
        ep.process(event3)

        # noMatch listener must not have been called
        with noMatchRecordingFilter.condition:
            while len(noMatchRecordingFilter.events) < 3:
                noMatchRecordingFilter.condition.wait()
            self.assertEqual(3, len(noMatchRecordingFilter.events))
            self.assertTrue(event1 in noMatchRecordingFilter.events)
            self.assertTrue(event2 in noMatchRecordingFilter.events)
            self.assertTrue(event3 in noMatchRecordingFilter.events)

class RouterTest(unittest.TestCase):

    def testActivate(self):

        class ActivateCountingPort(object):

            activations = 0

            def activate(self):
                ActivateCountingPort.activations = ActivateCountingPort.activations + 1

            def deactivate(self):
                pass

            def setObserverAction(self, action):
                pass

        router = Router(ActivateCountingPort(), ActivateCountingPort())
        self.assertEqual(0, ActivateCountingPort.activations)

        router.activate()
        self.assertEqual(2, ActivateCountingPort.activations)
        router.activate()
        self.assertEqual(2, ActivateCountingPort.activations)

    def testDeactivate(self):

        class DeactivateCountingPort(object):

            deactivations = 0

            def activate(self):
                pass

            def deactivate(self):
                DeactivateCountingPort.deactivations = DeactivateCountingPort.deactivations + 1

            def setObserverAction(self, action):
                pass

        router = Router(DeactivateCountingPort(), DeactivateCountingPort())
        self.assertEqual(0, DeactivateCountingPort.deactivations)

        router.deactivate()
        self.assertEqual(0, DeactivateCountingPort.deactivations)

        router.activate()
        self.assertEqual(0, DeactivateCountingPort.deactivations)
        router.deactivate()
        self.assertEqual(2, DeactivateCountingPort.deactivations)
        router.deactivate()
        self.assertEqual(2, DeactivateCountingPort.deactivations)

    def testPublish(self):

        class PublishCheckRouter(object):

            lastEvent = None

            def activate(self):
                pass
            def deactivate(self):
                pass

            def push(self, event):
                PublishCheckRouter.lastEvent = event

            def setObserverAction(self, action):
                pass

        router = Router(PublishCheckRouter(), PublishCheckRouter())

        event = 42
        router.publish(event)
        self.assertEqual(None, PublishCheckRouter.lastEvent)
        router.activate()
        router.publish(event)
        self.assertEqual(event, PublishCheckRouter.lastEvent)
        event = 34
        router.publish(event)
        self.assertEqual(event, PublishCheckRouter.lastEvent)

        PublishCheckRouter.lastEvent = None
        router.deactivate()
        router.publish(event)
        self.assertEqual(None, PublishCheckRouter.lastEvent)

    def testNotifyInPort(self):

        class SubscriptionTestPort(object):

            def __init__(self):
                self.activated = False
                self.deactivated = False
                self.filterCalls = []

            def activate(self):
                self.activated = True
            def deactivate(self):
                self.deactivated = True
            def filterNotify(self, filter, action):
                self.filterCalls.append((filter, action))
            def setObserverAction(self, action):
                pass

        ip = SubscriptionTestPort()
        op = SubscriptionTestPort()
        router = Router(ip, op)

        f1 = 12
        f2 = 24
        f3 = 36
        f4 = 48
        subscription = rsb.Subscription()
        subscription.appendFilter(f1)
        subscription.appendFilter(f2)

        router.subscribe(subscription)
        self.assertEqual(2, len(ip.filterCalls))
        self.assertTrue((f1, rsb.filter.FilterAction.ADD) in ip.filterCalls)
        self.assertTrue((f2, rsb.filter.FilterAction.ADD) in ip.filterCalls)

        subscription = rsb.Subscription()
        subscription.appendFilter(f3)
        subscription.appendFilter(f4)

        router.subscribe(subscription)
        self.assertEqual(4, len(ip.filterCalls))
        self.assertTrue((f3, rsb.filter.FilterAction.ADD) in ip.filterCalls)
        self.assertTrue((f4, rsb.filter.FilterAction.ADD) in ip.filterCalls)

        router.unsubscribe(subscription)
        self.assertEqual(6, len(ip.filterCalls))
        self.assertTrue((f3, rsb.filter.FilterAction.REMOVE) in ip.filterCalls)
        self.assertTrue((f4, rsb.filter.FilterAction.REMOVE) in ip.filterCalls)

def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(EventProcessorTest))
    suite.addTest(unittest.TestLoader().loadTestsFromTestCase(RouterTest))
    return suite
