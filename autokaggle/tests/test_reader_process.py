import json
import subprocess
from types import SimpleNamespace
from autokaggle import reader_process


def test_isolated_reader_can_use_the_pinned_runtime_without_pythonpath(tmp_path,monkeypatch):
    runtime=tmp_path/'pinned-runtime';library=runtime/'pypdf';library.mkdir(parents=True)
    (library/'__init__.py').write_text("MARKER='pinned reader'\n")
    monkeypatch.setattr(reader_process.importlib.util,'find_spec',lambda name:SimpleNamespace(origin=str(library/'__init__.py')))
    reader=tmp_path/'reader.py';reader.write_text('import pypdf,sys,json; print(json.dumps([pypdf.MARKER,sys.argv[1]]))')
    filename="notes'; raise SystemExit(99); #.txt"
    cmd=reader_process.command(reader,filename)
    assert '-I' in cmd and filename not in cmd[3]
    result=subprocess.run(cmd,capture_output=True,text=True,check=True,env={'PYTHONPATH':'/untrusted'})
    assert json.loads(result.stdout)==['pinned reader',filename]
