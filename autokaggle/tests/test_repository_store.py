import io
import json
import tarfile
from pathlib import Path
import pytest
from autokaggle import repository_store as repo


def archive(path, files):
    with tarfile.open(path, 'w:gz') as out:
        for name, value in files:
            item = tarfile.TarInfo(name)
            if isinstance(value, bytes):
                item.size = len(value)
                out.addfile(item, io.BytesIO(value))
            else:
                item.type = tarfile.SYMTYPE
                item.linkname = value
                out.addfile(item)


@pytest.mark.parametrize('name', ['root/../escape.py', '/root/escape.py', 'root/.git/config', 'root/snapshot.json', 'root/a\\b.py'])
def test_bad_paths_rejected(tmp_path, name):
    a=tmp_path/'a.tgz';archive(a, [(name,b'bad')]);dest=tmp_path/'out';dest.mkdir()
    with pytest.raises(ValueError): repo.extract(a,dest)


def test_links_not_followed_and_bytes_hashed(tmp_path):
    a=tmp_path/'a.tgz';archive(a,[('root/metrics.py',b'def score(): return 3'),('root/leak','/etc/passwd')]);dest=tmp_path/'out';dest.mkdir()
    index=repo.extract(a,dest)
    assert not (dest/'leak').exists()
    assert index['files'][1]['omitted']
    assert len(index['files'][0]['sha256'])==64


def test_limits_duplicates_and_multiple_roots(tmp_path,monkeypatch):
    dest=tmp_path/'out';dest.mkdir();a=tmp_path/'a.tgz'
    for files in [[('r/a.py',b'a'),('r/a.py',b'b')],[('r/a.py',b'a'),('s/b.py',b'b')]]:
        archive(a,files)
        with pytest.raises((ValueError, FileExistsError)): repo.extract(a,dest)
        for p in dest.iterdir(): p.unlink()
    monkeypatch.setattr(repo,'MAX_EXPANDED',3)
    archive(a,[('r/a.py',b'1234')])
    with pytest.raises(ValueError,match='limit'): repo.extract(a,dest)


def test_local_read_and_search_are_scoped(tmp_path):
    identity='a'*64;root=tmp_path/'repositories'/identity;root.mkdir(parents=True)
    text='def score():\n    return 42\n';(root/'metrics.py').write_text(text)
    (root/'snapshot.json').write_text(json.dumps({'commit':'b'*40,'index':[{'path':'metrics.py','bytes':len(text),'sha256':'hash'}]}))
    assert repo.read(tmp_path,identity,query='return')['matches'][0]['path']=='metrics.py'
    assert repo.read(tmp_path,identity,'metrics.py',4,5)['text']=='score'
    with pytest.raises(ValueError): repo.read(tmp_path,identity,'../secret')
    with pytest.raises(ValueError): repo.read(tmp_path,'../secret')


def test_snapshot_reuses_commit_and_cleans_partial_import(tmp_path,monkeypatch):
    from autokaggle import sources
    calls=[]
    def fetch(url,*args,**kwargs):
        calls.append(url)
        if 'codeload' in url:
            archive(kwargs['destination'],[('root/metrics.py',b'def score(): return 4')]);return b'','gzip',url
        return json.dumps({'sha':'b'*40} if '/commits/' in url else {'default_branch':'main'}).encode(),'json',url
    monkeypatch.setattr(sources,'fetch',fetch)
    a=repo.snapshot('https://github.com/test/benchmark',tmp_path)
    b=repo.snapshot('https://github.com/test/benchmark',tmp_path)
    assert a['snapshot']==b['snapshot']
    assert sum('codeload' in c for c in calls)==1
    assert not list((tmp_path/'repositories').glob('.import-*'))
