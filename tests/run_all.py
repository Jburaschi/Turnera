"""Corre todas las pruebas de Turnex.

Uso (desde la carpeta del proyecto):
    pip install -r requirements.txt -r requirements-dev.txt
    python tests/run_all.py            # todas
    python tests/run_all.py feriados   # solo las que contienen "feriados"

Cada prueba arranca la app con una base SQLite temporal nueva (con el negocio
demo "pepito"), así que no toca ninguna base real.
"""
import glob, os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTRA = {
    'test_prep.py': [['web'], ['seed']],
}
ENV_EXTRA = {
    'test_proxy.py': {'SEED_DEMO': '1'},
}


def run(path, args):
    tmp = tempfile.mkdtemp(prefix='turnex_test_')
    env = {k: v for k, v in os.environ.items() if k not in ('FLASK_ENV', 'DATABASE_URL', 'SEED_DEMO', 'REDIS_URL')}
    env.update({'PYTHONPATH': ROOT, 'TZ': 'UTC', 'DATABASE_URL': 'sqlite:///' + os.path.join(tmp, 'test.db')})
    env.update(ENV_EXTRA.get(os.path.basename(path), {}))
    out = subprocess.run([sys.executable, path, *args], cwd=ROOT, env=env, capture_output=True, text=True)
    text = out.stdout + out.stderr
    passed = text.count('\nPASS') + text.startswith('PASS')
    failed = [l for l in text.splitlines() if l.startswith('FAIL')]
    crashed = out.returncode != 0 and 'Traceback' in text and not failed
    return passed, failed, crashed, text


def main():
    flt = sys.argv[1] if len(sys.argv) > 1 else ''
    files = sorted(f for f in glob.glob(os.path.join(ROOT, 'tests', 'test_*.py')) if flt in os.path.basename(f))
    total_ok, total_fail, bad = 0, 0, []
    t0 = time.time()
    for f in files:
        for args in EXTRA.get(os.path.basename(f), [[]]):
            p, fails, crashed, text = run(f, args)
            name = os.path.basename(f) + (' ' + ' '.join(args) if args else '')
            total_ok += p; total_fail += len(fails)
            mark = 'OK ' if not fails and not crashed else 'MAL'
            print(f'{mark} {name}: {p} ok, {len(fails)} fallas' + (' (se cortó)' if crashed else ''))
            for l in fails:
                print('     ' + l)
            if crashed:
                print('     ' + '\n     '.join(text.strip().splitlines()[-6:]))
            if fails or crashed:
                bad.append(name)
    print(f'\n{total_ok} pruebas OK, {total_fail} fallas, en {time.time() - t0:.0f} s')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
