"""Bounded, immutable source snapshots. Repository files are read, never executed."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile
import threading
import time

LOCK = threading.Lock()
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024
MAX_FILES = 40000
MAX_FILE = 128 * 1024 * 1024
TEXT_SUFFIXES = {'.py', '.md', '.txt', '.rst', '.json', '.yaml', '.yml', '.toml', '.cfg', '.ini', '.r', '.jl', '.js', '.ts', '.sh', '.ipynb'}


def extract(archive, target):
    """Do not use extractall: reject special files, traversal, duplicates and bombs."""
    total, entries, seen = 0, [], set()
    started = time.monotonic()
    with tarfile.open(archive, 'r|gz') as bundle:
        prefix = None
        for member in bundle:
            if time.monotonic() - started > 180:
                raise ValueError('Repository extraction exceeded three minutes.')
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or '\\' in member.name or any(ord(c) < 32 for c in member.name):
                raise ValueError('Repository archive contains an unsafe path.')
            if not path.parts:
                continue
            prefix = prefix or path.parts[0]
            if path.parts[0] != prefix:
                raise ValueError('Repository archive has multiple roots.')
            relative = PurePosixPath(*path.parts[1:])
            if str(relative) == '.':
                continue
            if '.git' in relative.parts or str(relative) == 'snapshot.json' or len(str(relative)) > 1000:
                raise ValueError('Repository archive contains an unsupported path.')
            if member.isdir():
                continue
            if not member.isfile() or member.issparse():
                # Symlinks are omitted, never followed. Keep this visible in the manifest.
                entries.append({'path': str(relative), 'omitted': 'link or special file'})
                if len(entries) > MAX_FILES:
                    raise ValueError('Repository contains too many files.')
                continue
            if str(relative) in seen:
                raise ValueError('Repository archive contains a duplicate file.')
            seen.add(str(relative))
            total += member.size
            if member.size > MAX_FILE or total > MAX_EXPANDED or len(entries) >= MAX_FILES:
                raise ValueError('Repository exceeds the server source-storage limit (1 GiB, 40,000 files, 128 MiB per file).')
            dest = target / str(relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with bundle.extractfile(member) as src, dest.open('xb') as out:
                while chunk := src.read(1024 * 1024):
                    digest.update(chunk)
                    out.write(chunk)
            os.chmod(dest, 0o600)
            entries.append({'path': str(relative), 'bytes': member.size, 'sha256': digest.hexdigest()})
    return {'files': entries, 'bytes': total}


def snapshot(url, directory, progress=None):
    from . import sources
    owner, repo = sources.parse_repository(url)
    # Public imports deliberately do not use the publishing credential.
    api = f'https://api.github.com/repos/{owner}/{repo}'
    metadata = json.loads(sources.fetch(api)[0])
    from urllib.parse import quote
    commit = json.loads(sources.fetch(api + '/commits/' + quote(metadata['default_branch'], safe=''))[0])['sha']
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('GitHub did not return an immutable commit.')
    identity = hashlib.sha256(f'{owner.lower()}/{repo.lower()}@{commit}'.encode()).hexdigest()
    root = Path(directory) / 'repositories'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / identity
    with LOCK:
        if (target / 'snapshot.json').is_file():
            record = json.loads((target / 'snapshot.json').read_text())
        else:
            if sum(1 for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')) >= 6:
                raise ValueError('This session already stores six repository revisions. Start a new session or remove an unused repository.')
            if shutil.disk_usage(root).free < MAX_EXPANDED + MAX_ARCHIVE + 256 * 1024 * 1024:
                raise ValueError('Source storage is nearly full. Ask the administrator to add space, then retry.')
            # Remove interrupted temporary imports. This lock serializes all imports in this process.
            for stale in root.glob('.import-*'):
                if stale.is_dir():
                    shutil.rmtree(stale)
            with tempfile.TemporaryDirectory(prefix='.import-', dir=root) as temp:
                temp = Path(temp)
                archive = temp / 'source.tar.gz'
                if progress:
                    progress('Downloading the pinned repository to server storage')
                sources.fetch(f'https://codeload.github.com/{owner}/{repo}/tar.gz/{commit}', MAX_ARCHIVE,
                              destination=archive, deadline=300)
                tree = temp / 'tree'
                tree.mkdir()
                if progress:
                    progress('Checking and indexing repository files')
                index = extract(archive, tree)
                record = {'kind': 'repository', 'url': f'https://github.com/{owner}/{repo}', 'commit': commit,
                          'snapshot': identity, 'description': metadata.get('description'),
                          'license': (metadata.get('license') or {}).get('spdx_id'),
                          'index': index['files'], 'storage_bytes': index['bytes'],
                          'imported_at': sources.now(), 'source_policy': 'Source snapshot only. No Git history, submodule downloads, LFS downloads, or execution.'}
                (tree / 'snapshot.json').write_text(json.dumps(record))
                tree.rename(target)
    result = {k: v for k, v in record.items() if k != 'index'}
    # Wide local selection includes scorer modules with arbitrary names, rather than 12 fixed file names.
    candidates = [f for f in record['index'] if not f.get('omitted') and Path(f['path']).suffix.lower() in TEXT_SUFFIXES]
    candidates.sort(key=lambda f: (0 if 'readme' in f['path'].lower() else 1 if re.search('eval|score|metric|config|requirements|pyproject', f['path'], re.I) else 2, f['path'].count('/'), f['path']))
    result['file_index'] = [{'path': f['path'], 'bytes': f['bytes']} for f in candidates[:2000]]
    result['file_count'] = len(record['index'])
    result['omitted_files'] = [f for f in record['index'] if f.get('omitted')][:30]
    result['files'] = []
    budget = 90000
    for entry in candidates[:35]:
        if entry['bytes'] > 2 * 1024 * 1024:
            continue
        if budget <= 0:
            break
        found = read(directory, identity, entry['path'], 0, min(6000, budget))
        if found.get('text'):
            result['files'].append({'path': entry['path'], 'sha256': entry['sha256'], 'text': found['text'], 'truncated': found['truncated']})
            budget -= len(found['text'])
    result['truncated'] = True  # Prompt excerpts are bounded; the complete accepted snapshot remains available.
    return result


def read(directory, identity, path='', start=0, count=12000, query=''):
    if not re.fullmatch('[0-9a-f]{64}', identity):
        raise ValueError('Invalid repository snapshot.')
    root = Path(directory) / 'repositories' / identity
    record = json.loads((root / 'snapshot.json').read_text())
    files = {f['path']: f for f in record['index'] if not f.get('omitted')}
    if query:
        if len(query) > 200:
            raise ValueError('Use a search phrase of at most 200 characters.')
        matches, scanned, started = [], 0, time.monotonic()
        for name, entry in files.items():
            if Path(name).suffix.lower() not in TEXT_SUFFIXES or entry['bytes'] > 2 * 1024 * 1024:
                continue
            if scanned > 32 * 1024 * 1024 or time.monotonic() - started > 5:
                break
            text = (root / name).read_text(errors='replace')
            scanned += entry['bytes']
            at = text.lower().find(query.lower())
            if at >= 0:
                matches.append({'path': name, 'at': at, 'excerpt': text[max(0, at-100):at+500]})
                if len(matches) == 15:
                    break
        return {'commit': record['commit'], 'matches': matches, 'bounded_search': True}
    if not path:
        return {'commit': record['commit'], 'files': list(files)[:2000], 'total_files': len(files)}
    if path not in files or Path(path).suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError('Choose a text file from this repository index.')
    if files[path]['bytes'] > 2 * 1024 * 1024:
        raise ValueError('This file exceeds the 2 MiB text-read limit. Read a smaller source file.')
    text = (root / path).read_text(errors='replace')
    start = max(0, int(start))
    count = min(max(1, count), 12000)
    return {'path': path, 'commit': record['commit'], 'sha256': files[path]['sha256'], 'start': start,
            'text': text[start:start+count], 'chars': len(text), 'truncated': start+count < len(text)}
