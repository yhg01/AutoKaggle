"""Private Lite request records. Recording does not change the scientific contract."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import threading
import time
import uuid
import weakref

from . import observability as obs
from .store import now

_STORES = weakref.WeakValueDictionary()
_GUARD = threading.Lock()


def bind(store):
    with _GUARD:
        _STORES[str(store.root)] = store


def save(state, trace):
    directory = state.get('_repository_directory')
    if not directory:
        return
    directory = Path(directory).resolve()
    with _GUARD:
        store = _STORES.get(str(directory.parent))
    if store is None or directory != store.directory(directory.name).resolve():
        return
    with store.lock(directory.name):
        with store.connection() as con:
            row = con.execute('SELECT body FROM projects WHERE id=?', (directory.name,)).fetchone()
        if not row:
            return  # Erasure must not restore a record from an in-flight request.
        item = json.loads(row[0])
        if item.get('lite', {}).get('job_id') != state.get('job_id'):
            return
        records = item.setdefault('_model_traces', [])
        existing = next((i for i, r in enumerate(records) if r['id'] == trace['id']), None)
        if existing is None:
            item.setdefault('_lite_trace_started_at', now())
            item.setdefault('_lite_untraced_turns', max(0, item['lite'].get('model_calls', 0) - 1))
            item['_lite_model_requests'] = item.get('_lite_model_requests', 0) + 1
            records.append(copy.deepcopy(trace))
        else:
            records[existing] = copy.deepcopy(trace)
        del records[:-obs.LIMIT]
        store.save(item)


def capture(trace, key, value):
    raw = obs.scrub(value if isinstance(value, str) else json.dumps(obs.scrub(value), ensure_ascii=False, default=str))
    trace[key] = obs.bounded(raw)
    trace.setdefault('capture', {})[key] = {'original_chars': len(raw), 'limit_chars': obs.TEXT_LIMIT, 'truncated': len(raw) > obs.TEXT_LIMIT}


class InterviewRecords:
    """Keep validation linked to its request without changing interview input state."""
    def __init__(self, state):
        self.state = state
        self.trace = None

    def request(self, client, **kwargs):
        return request(self.state, client, _record=self, **kwargs)

    def parse(self, lite, response):
        return parse(lite, self.state, response, self.trace)


def request(state, client, *, kind='lite interview', _record=None, **kwargs):
    """Record each provider request, including source lookups and schema repairs."""
    message = next((m for m in reversed(state.get('messages', [])) if m.get('role') == 'user'), {})
    trace = {'id': uuid.uuid4().hex, 'kind': kind, 'status': 'running', 'started_at': now(), 'model': kwargs.get('model'),
             'effort': (kwargs.get('extra_body') or {}).get('reasoning_effort', 'medium'),
             'trigger': {'message_id': message.get('id'), 'interview_round': state.get('round')},
             'reasoning': '', 'reasoning_available': False}
    capture(trace, 'instructions', '\n\n'.join(m.get('content', '') for m in kwargs.get('messages', []) if m.get('role') == 'system'))
    capture(trace, 'input', kwargs)
    save(state, trace)
    started = time.monotonic()
    try:
        response = client.chat.completions.create(**kwargs)
        choices = getattr(response, 'choices', []) or []
        choice = choices[0] if choices else None
        finish = getattr(choice, 'finish_reason', None)
        msg = getattr(choice, 'message', None)
        capture(trace, 'output', getattr(msg, 'content', '') or '')
        calls = getattr(msg, 'tool_calls', None) or []
        if calls:
            capture(trace, 'tool_calls', [c.model_dump(exclude_none=True) for c in calls])
        usage = getattr(response, 'usage', None)
        details = getattr(usage, 'completion_tokens_details', None)
        trace.update(status='completed' if finish in {'stop', 'tool_calls'} else 'incomplete', provider_status=finish,
                     model=getattr(response, 'model', None) or kwargs.get('model'),
                     usage={'input_tokens': getattr(usage, 'prompt_tokens', None), 'output_tokens': getattr(usage, 'completion_tokens', None),
                            'reasoning_tokens': getattr(details, 'reasoning_tokens', None)})
        return response
    except Exception as exc:
        trace.update(status='failed', error_type=type(exc).__name__)
        # Raw exceptions can contain request headers. Store only a status and type.
        if isinstance(getattr(exc, 'status_code', None), int):
            trace['http_status'] = exc.status_code
        raise
    finally:
        trace.update(finished_at=now(), duration_ms=round((time.monotonic() - started) * 1000))
        save(state, trace)
        if _record is not None:
            _record.trace = trace


def parse(lite, state, response, trace=None):
    status = 'rejected'
    try:
        result = lite.parse_proposal(state, response)
        status = 'accepted'
        return result
    finally:
        if trace:
            trace['validation'] = {'status': status, 'at': now()}
            save(state, trace)
