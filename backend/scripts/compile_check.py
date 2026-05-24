import py_compile
import pathlib
import sys

base = pathlib.Path(__file__).resolve().parent.parent
errors = []
count = 0
for p in base.rglob('*.py'):
    # Ensure file is actually inside backend (avoid following symlinks outside)
    try:
        resolved = p.resolve()
    except Exception:
        resolved = p
    if not str(resolved).startswith(str(base)):
        continue
    # skip site-packages or other env libs
    if 'site-packages' in str(resolved).lower():
        continue
    count += 1
    try:
        py_compile.compile(str(p), doraise=True)
    except Exception as e:
        errors.append((str(p), str(e)))
        print(f"COMPILE_ERROR {p}: {e}")

print('FILES_CHECKED', count)
print('ERROR_COUNT', len(errors))
if errors:
    for p,e in errors[:50]:
        print('---', p)
        print(e)
    sys.exit(2)
else:
    sys.exit(0)
