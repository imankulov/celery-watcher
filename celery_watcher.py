#!/usr/bin/env python
import logging
import datetime

from fnmatch import fnmatch
from xmlrpclib import ServerProxy, Fault
from celery.app import app_or_default

logger = logging.getLogger(__name__)


class CelerydManager(object):

    def __init__(self, manageable_queues='*', queue_lifespan=None):
        self.manageable_queues = manageable_queues
        self.queue_lifespan = queue_lifespan or datetime.timedelta(seconds=600)
        self.queue_invocations = {}
        self.update_queue_invocations()

    def on_task_sent(self, event):
        queue = event.get('queue', '')
        logger.debug('Received event %r to queue %s', event, queue)
        if self.is_queue_manageable(queue):
            if not self.is_queue_active(queue):
                self.start_queue(queue)
                logger.info('Queue %r started', queue)
            self.queue_invocations[queue] = datetime.datetime.now()
            logger.debug('Last invocation of queue %r is now', queue)
        self.stop_outdated_queues()

    def is_queue_matches(self, queue):
        matches = fnmatch(queue, self.manageable_queues)
        if matches:
            logger.debug('Queue %r matches %r', queue, self.manageable_queues)
        else:
            logger.debug('Queue %r DOES NOT match %r', queue, self.manageable_queues)
        return matches

    def is_queue_manageable(self, queue):
        return self.is_queue_matches(queue)

    def is_queue_active(self, queue):
        raise NotImplementedError('Method must be implemented in subclass')

    def start_queue(self, queue):
        raise NotImplementedError('Method must be implemented in subclass')

    def stop_queue(self, queue):
        raise NotImplementedError('Method must be implemented in subclass')

    def update_queue_invocations(self):
        raise NotImplementedError('Method must be implemented in subclass')

    def stop_outdated_queues(self):
        for queue, last_invocation in self.queue_invocations.items():
            if last_invocation and \
                    last_invocation < datetime.datetime.now() - self.queue_lifespan:
                if self.is_queue_active(queue):
                    self.stop_queue(queue)
                    logger.info('Queue %r stopped', queue)


DEFAULT_SUPERVISOR_ADDRESS = 'http://127.0.0.1:9001'


class SupervisorCelerydManager(CelerydManager):

    def __init__(self,
                 supervisor_address=None,
                 queue_to_process=None,
                 process_to_queue=None,
                 *args,
                 **kwargs):
        """
        Celeryd manager which uses supervisor to startup/shutdown extra services

        :param queue_to_process: a callable which converts name of the queue to
                                 the name of the process. By default is None,
                                 which means that the name of the queue is the
                                 same as the name of the process.
        :param process_to_queue: a callable which converts name of the queue to
                                 the name of the process. By default is None,
                                 which means that the name of the queue is the
                                 same as the name of the process. If process to
                                 queue returns None, then there is no queue
                                 corresponding to that process and we must not
                                 manage (start or stop) this process.
        """
        default_map = lambda x: x
        self.queue_to_process = queue_to_process or default_map
        self.process_to_queue = process_to_queue or default_map
        self.supervisor_address = supervisor_address or DEFAULT_SUPERVISOR_ADDRESS
        self.server = ServerProxy('{0}/RPC2'.format(self.supervisor_address))
        self.supervisor = self.server.supervisor
        self.queue_state_cache = {}
        self.queue_state_cache_last_update = None
        self.queue_state_cache_timeout = datetime.timedelta(seconds=60)
        super(SupervisorCelerydManager, self).__init__(*args, **kwargs)

    def is_queue_manageable(self, queue):
        matches = self.is_queue_matches(queue)
        if not matches:
            return False
        self.update_queue_state_cache()
        manageable = queue in self.queue_state_cache
        if not manageable:
            logger.debug(('Queue %r is not known by the supervisor. '
                           'Hopefully, it will be started by someone else.'), queue)
        return manageable

    def is_queue_active(self, queue):
        self.update_queue_state_cache()
        if queue in self.queue_state_cache:
            queue_state = self.queue_state_cache[queue]
            logger.debug('State of %r: %r', queue, queue_state)
            return queue_state
        else:
            raise RuntimeError('Queue %r is not known by the supervisor', queue)


    def update_queue_state_cache(self):
        now = datetime.datetime.now()
        threshold = datetime.datetime.now() - self.queue_state_cache_timeout
        if not self.queue_state_cache_last_update or \
                self.queue_state_cache_last_update < threshold:
            try:
                processes = self.supervisor.getAllProcessInfo()
            except Fault, e:
                raise RuntimeError(e)
            self.queue_state_cache = {}
            for process_info in processes:
                process = process_info['name']
                state = process_info['state'] in (10, 20, 30)
                queue = self.process_to_queue(process)
                if queue and self.is_queue_matches(queue):
                    self.queue_state_cache[queue] = state
                    logger.debug('Queue %r is marked in cache as %r', queue, state)
            self.queue_state_cache_last_update = now


    def start_queue(self, queue):
        process_name = self.queue_to_process(queue)
        try:
            logger.debug('Send supervisor.startProcess(%r) command to supervisor',
                         process_name)
            self.supervisor.startProcess(process_name)
        except Fault, e:
            if e.faultCode != 60:  # ALREADY STARTED
                raise RuntimeError(str(e))
        self.queue_state_cache[queue] = True
        self.queue_invocations[queue] = datetime.datetime.now()


    def stop_queue(self, queue):
        process_name = self.queue_to_process(queue)
        try:
            logger.debug('Send supervisor.stopProcess(%r) command to supervisor',
                         process_name)
            self.supervisor.stopProcess(process_name)
        except Fault, e:
            if e.faultCode != 70:  # NOT RUNNING
                raise RuntimeError(str(e))
        if queue in self.queue_state_cache:
            self.queue_state_cache[queue] = False

    def update_queue_invocations(self):
        """
        Update self.queue_invocations dict.

        For every running queue not in dict set last invocation time to now,
        don't touch existing records.
        """
        self.update_queue_state_cache()
        now = datetime.datetime.now()
        for queue, state in self.queue_state_cache.iteritems():
            if not state:
                continue
            if queue not in self.queue_invocations:
                self.queue_invocations[queue] = now
                logger.debug('Last invocation of queue %r is now', queue)


def watch(manager, app=None):
    app = app_or_default(app)
    conn = app.broker_connection()
    handlers={
        'task-sent': manager.on_task_sent,
    }
    recv = app.events.Receiver(conn, handlers=handlers)
    try:
        recv.capture()
    except (KeyboardInterrupt, SystemExit):
        conn and conn.close()
