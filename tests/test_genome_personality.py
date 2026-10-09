"""Regression: Elsa's sadism was compiled as flirting and automatic consent."""
import pathlib
import shutil
import subprocess

def run():
    node = shutil.which('node')
    if not node:
        return [('контекстный геном: нужен Node для проверки JS', False, 'node отсутствует')]
    file = pathlib.Path(__file__).resolve().parent.parent / 'genome/pipeline/test_personality.js'
    result = subprocess.run([node, str(file)], capture_output=True, encoding='utf-8', timeout=30)
    checks = [('геном: ' + line[3:], True, '') for line in result.stdout.splitlines() if line.startswith('ok ')]
    if result.returncode:
        checks.append(('контекстный геном завершает все проверки', False, result.stderr[-900:]))
    return checks
