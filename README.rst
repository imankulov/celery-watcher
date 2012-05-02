Celery Watcher application
==========================

The usecase of this application is quite narrow. The watcher is intended to
manage several celery daemons in a quite specific environment:

- All managed celery daemons are launched by `supervisor <http://supervisord.org/>`_
- Every managed celery daemon serves exactly one queue
- Queue name in celery matches the name of the celery process in supervisor, or
  is a suffix of that process name

Providing these conditions are met, celery-watcher subscribes for events of type
`task-sent <http://ask.github.com/celery/userguide/monitoring.html#task-events>`_,
and then automatically starts queues having received at least one event, and
stops queues which don't receive any events for too long (the threshold is
passed in command line).

The ultimate goal of this approach is to reduce the overall consumption of
memory in the server, when one host supports hundreds of rarely used celery
daemons.

To make things work, following additional configuration must be done:

- celeryconfig must be configured with `CELERY_SEND_TASK_SENT_EVENT` set to `True`
- supervisor daemon must be accessible via XML-RPC network interface

Below is a part of supervisor config which can be considered as a sample::


    [inet_http_server]
    port = 127.0.0.1:9001

    [program:queue1]
    command = <...>/bin/celeryd -Q queue1
    autostart = false
    user = <...>
    directory = <...>

    [program:queue2]
    command = <...>/bin/celeryd -Q queue2
    autostart = false
    user = <...>
    directory = <...>
