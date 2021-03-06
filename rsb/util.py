# ============================================================
#
# Copyright (C) 2010 by Johannes Wienke
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
Various helper classes and methods.

.. codeauthor:: jwienke
"""

import logging
from queue import Queue
from threading import Condition, Lock, Thread


class _InterruptedError(RuntimeError):
    """
    Internal exception used by pool implementation.

    .. codeauthor:: jwienke
    """

    pass


class OrderedQueueDispatcherPool:
    """
    A thread pool that dispatches messages to a list of receivers.

    The number of threads is usually smaller than the number of receivers and
    for each receiver it is guaranteed that messages arrive in the order they
    were published. No guarantees are given between different receivers.  All
    methods except #start and #stop are reentrant.

    The pool can be stopped and restarted at any time during the processing but
    these calls must be single-threaded.

    Assumptions:
     - same subscriptions for multiple receivers unlikely, hence filtering done
       per receiver thread

    .. codeauthor:: jwienke
    """

    class _Receiver:

        def __init__(self, receiver):
            self.receiver = receiver
            self.queue = Queue()
            self.processing = False
            self.processing_mutex = Lock()
            self.processing_condition = Condition()

    def _true_filter(self, receiver, message):
        return True

    def __init__(self, thread_pool_size, del_func, filter_func=None):
        """
        Construct a new pool.

        Args:
            thread_pool_size (int >= 1):
                number of threads for this pool
            del_func (callable):
                the strategy used to deliver messages of type M to receivers of
                type R. This will most likely be a simple delegate function
                mapping to a concrete method call.  Must be reentrant. callable
                with two arguments. First is the receiver of a message, second
                is the message to deliver
            filter_func (callable):
                Reentrant function used to filter messages per receiver.
                Default accepts every message. callable with two arguments.
                First is the receiver of a message, second is the message to
                filter. Must return a bool, true means to deliver the message,
                false rejects it.
        """

        self._logger = get_logger_by_class(self.__class__)

        if thread_pool_size < 1:
            raise ValueError("Thread pool size must be at least 1,"
                             "{} was given.".format(thread_pool_size))
        self._thread_pool_size = int(thread_pool_size)

        self._del_func = del_func
        if filter_func is not None:
            self._filter_func = filter_func
        else:
            self._filter_func = self._true_filter

        self._condition = Condition()
        self._receivers = []

        self._jobsAvailable = False

        self._started = False
        self._interrupted = False

        self._threadPool = []

        self._currentPosition = 0

    def __del__(self):
        self.stop()

    def register_receiver(self, receiver):
        """
        Register a new receiver at the pool.

        Multiple registrations of the same receiver are possible resulting in
        being called multiple times for the same message (but effectively this
        destroys the guarantee about ordering given above because multiple
        message queues are used for every subscription).

        Args:
            receiver:
                new receiver
        """

        with self._condition:
            self._receivers.append(self._Receiver(receiver))

        self._logger.info("Registered receiver %s", receiver)

    def unregister_receiver(self, receiver):
        """
        Unregister all registrations of one receiver.

        Args:
            receiver:
                receiver to unregister

        Returns:
            True if one or more receivers were unregistered, else False
        """

        removed = None
        with self._condition:
            kept = []
            for r in self._receivers:
                if r.receiver == receiver:
                    removed = r
                else:
                    kept.append(r)
            self._receivers = kept
        if removed:
            with removed.processing_condition:
                while removed.processing:
                    self._logger.info("Waiting for receiver %s to finish",
                                      receiver)
                    removed.processing_condition.wait()
        return not (removed is None)

    def push(self, message):
        """
        Push a new message to be dispatched to all receivers in this pool.

        Args:
            message:
                message to dispatch
        """

        with self._condition:
            for receiver in self._receivers:
                receiver.queue.put(message)
            self._jobsAvailable = True
            self._condition.notify()

        # XXX: This is disabled because it can trigger this bug for protocol
        # buffers payloads:
        # http://code.google.com/p/protobuf/issues/detail?id=454
        # See also #1331
        # self._logger.debug("Got new message to dispatch: %s", message)

    def _next_job(self, worker_num):
        """
        Return the next job to process for worker threads.

        Blocks if there is no job.

        Args:
            worker_num:
                number of the worker requesting a new job

        Returns:
            the receiver to work on
        """

        receiver = None
        with self._condition:

            got_job = False
            while not got_job:

                while (not self._jobsAvailable) and (not self._interrupted):
                    self._logger.debug(
                        "Worker %d: no jobs available, waiting", worker_num)
                    self._condition.wait()

                if (self._interrupted):
                    raise _InterruptedError("Processing was interrupted")

                # search the next job
                for _ in range(len(self._receivers)):

                    self._currentPosition = self._currentPosition + 1
                    real_pos = self._currentPosition % len(self._receivers)

                    if (not self._receivers[real_pos].processing) and \
                            (not self._receivers[real_pos].queue.empty()):

                        receiver = self._receivers[real_pos]
                        receiver.processing = True
                        got_job = True
                        break

                if not got_job:
                    self._jobsAvailable = False

            self._condition.notify()
            return receiver

    def _finished_work(self, receiver, worker_num):

        with self._condition:

            with receiver.processing_condition:
                receiver.processing = False
                receiver.processing_condition.notifyAll()
            if not receiver.queue.empty():
                self._jobsAvailable = True
                self._logger.debug("Worker %d: new jobs available, "
                                   "notifying one", worker_num)
                self._condition.notify()

    def _worker(self, worker_num):
        """
        Threaded worker method.

        Args:
            worker_num:
                number of this worker thread
        """

        try:

            while True:

                receiver = self._next_job(worker_num)
                message = receiver.queue.get(True, None)
                self._logger.debug(
                    "Worker %d: got message %s for receiver %s",
                    worker_num, message, receiver.receiver)
                if self._filter_func(receiver.receiver, message):
                    self._logger.debug(
                        "Worker %d: delivering message %s for receiver %s",
                        worker_num, message, receiver.receiver)
                    self._del_func(receiver.receiver, message)
                    self._logger.debug(
                        "Worker %d: delivery for receiver %s finished",
                        worker_num, receiver.receiver)
                self._finished_work(receiver, worker_num)

        except _InterruptedError:
            pass

    def start(self):
        """
        Start processing and return immediately.

        Raises:
            RuntimeError:
                if the pool was already started and is running
        """

        with self._condition:

            if self._started:
                raise RuntimeError("Pool already running")

            self._interrupted = False

            for i in range(self._thread_pool_size):
                worker = Thread(target=self._worker, args=[i])
                worker.setDaemon(True)
                worker.start()
                self._threadPool.append(worker)

            self._started = True

        self._logger.info("Started pool with %d threads",
                          self._thread_pool_size)

    def stop(self):
        """Block until every thread has stopped working."""

        self._logger.info(
            "Starting to stop thread pool by wating for workers")

        with self._condition:
            self._interrupted = True
            self._condition.notifyAll()

        for worker in self._threadPool:
            self._logger.debug("Joining worker %s", worker)
            worker.join()

        self._threadPool = []

        self._started = False

        self._logger.info("Stopped thread pool")


def get_logger_by_class(klass):
    """
    Get a python logger instance based on a class instance.

    The logger name will be a dotted string containing python module and class
    name.

    Args:
        klass:
            class instance

    Returns:
        logger instance
    """
    return logging.getLogger(klass.__module__ + "." + klass.__name__)


def time_to_unix_microseconds(time):
    """
    Convert a floating point, seconds based time to a unix microseconds.

    Args:
        time:
            time since epoch in seconds + fractional part.

    Returns:
        time as integer with microseconds precision.
    """
    return int(time * 1000000)


def unix_microseconds_to_time(value):
    return float(value) / 1000000.0


def prefix():
    """
    Try to return the prefix that this code was installed into.

    This is done by guessing the install location from some rules.

    Adapted from
    http://ttboj.wordpress.com/2012/09/20/finding-your-software-install-prefix-from-inside-python/

    Returns:
        string path with the install prefix or empty string if not known
    """

    import os
    import sys

    path = os.path.abspath(__file__)
    token = "dummy"

    while len(token) > 0:
        (path, token) = os.path.split(path)
        if token in ['site-packages', 'dist-packages']:
            (path, token) = os.path.split(path)
            if token == 'python{}'.format(sys.version[:3]):
                (path, token) = os.path.split(path)
                return path

    return ""
