"""Launch a bounded document reader with only the application's pinned PDF library.

Python isolated mode ignores PYTHONPATH. Hosted dependencies live in a read-only
runtime mount, so pass that known dependency location explicitly. File content,
file names, and user environment values never become Python source.
"""
import importlib.util
from pathlib import Path
import sys


def command(reader, *arguments):
    spec=importlib.util.find_spec('pypdf')
    if spec is None or not spec.origin:
        raise ValueError('The PDF reader dependency is not installed on this server.')
    dependencies=str(Path(spec.origin).resolve().parent.parent)
    bootstrap=("import runpy,sys; sys.path.insert(0,"+repr(dependencies)+"); "
               "reader=sys.argv.pop(1); runpy.run_path(reader,run_name='__main__')")
    return [sys.executable,'-I','-c',bootstrap,str(Path(reader).resolve()),*arguments]
