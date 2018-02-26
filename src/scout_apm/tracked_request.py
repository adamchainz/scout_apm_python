from __future__ import absolute_import

import logging
from datetime import datetime
from uuid import uuid4

from scout_apm.context import AgentContext
from scout_apm.request_manager import RequestManager
from scout_apm.thread_local import ThreadLocalSingleton

from .commands import (FinishRequest, StartRequest, StartSpan, StopSpan,
                       TagRequest, TagSpan)

# Logging
logger = logging.getLogger(__name__)


class TrackedRequest(ThreadLocalSingleton):
    """
    This is a container which keeps track of all module instances for a single
    request. For convenience they are made available as attributes based on
    their keyname
    """
    def __init__(self, *args, **kwargs):
        self.req_id = 'req-' + str(uuid4())
        self.start_time = kwargs.get('start_time', datetime.utcnow())
        self.end_time = kwargs.get('end_time', None)
        self.spans = kwargs.get('spans', [])
        self.tags = kwargs.get('tags', {})
        logger.info('Starting request: %s', self.req_id)

    def tag(self, key, value):
        if hasattr(self.tags, key):
            logger.debug('Overwriting previously set tag for request %s: %s' % self.req_id, key)
        self.tags[key] = value

    def start_span(self, operation=None):
        maybe_parent = self.current_span()

        if maybe_parent is not None:
            parent_id = maybe_parent.span_id
        else:
            parent_id = None

        new_span = Span(
            request_id=self.req_id,
            operation=operation,
            parent=parent_id)
        self.spans.append(new_span)
        return new_span

    def stop_span(self):
        stopping_span = self.spans.pop()
        stopping_span.stop()
        if len(self.spans) == 0:
            self.finish()

    def current_span(self):
        if len(self.spans) > 0:
            return self.spans[-1]
        else:
            return None

    # Request is done, release any info we have about it.
    def finish(self):
        logger.info('Stopping request: %s', self.req_id)
        if self.end_time is None:
            self.end_time = datetime.utcnow()
        RequestManager.instance().add_request(self)
        self.release()


class Span:
    def __init__(self, *args, **kwargs):
        self.span_id = kwargs.get('span_id', 'span-' + str(uuid4()))
        self.start_time = kwargs.get('start_time', datetime.utcnow())
        self.end_time = kwargs.get('end_time', None)
        self.request_id = kwargs.get('request_id', None)
        self.operation = kwargs.get('operation', None)
        self.parent = kwargs.get('parent', None)
        self.tags = kwargs.get('tags', {})

    def dump(self):
        if self.end_time is None:
            logger.info(self.operation)
        return 'request=%s operation=%s id=%s parent=%s start_time=%s end_time=%s' % (
                self.request_id,
                self.operation,
                self.span_id,
                self.parent,
                self.start_time.isoformat(),
                self.end_time.isoformat()
            )

    def stop(self):
        self.end_time = datetime.utcnow()

    def tag(self, key, value):
        if hasattr(self.tags, key):
            logger.debug('Overwriting previously set tag for span %s: %s' % self.span_id, key)
        self.tags[key] = value

    # In seconds
    def duration(self):
        if self.end_time is not None:
            (self.end_time - self.start_time).total_seconds()
        else:
            # Current, running duration
            (datetime.utcnow() - self.start_time).total_seconds()
