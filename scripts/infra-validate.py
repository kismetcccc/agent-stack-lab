#!/usr/bin/env python3
"""Offline manifest invariants; not a replacement for Compose/Kind runtime tests."""
from pathlib import Path
import re
import yaml

root = Path(__file__).resolve().parents[1]
compose = yaml.safe_load((root / 'compose.yaml').read_text())
services = compose['services']
for name in ('mysql', 'kafka', 'mongo', 'redis'):
    assert name in services and not services[name].get('ports'), f'{name} must remain private'
for name, service in services.items():
    image = service.get('image', '')
    assert ':' in image and not image.endswith(':latest'), f'{name} image must be version pinned'
    for binding in service.get('ports', []):
        assert str(binding).startswith('127.0.0.1:'), f'{name} must bind loopback'
assert services['api']['depends_on']['migrate']['condition'] == 'service_completed_successfully'
assert services['worker']['depends_on']['migrate']['condition'] == 'service_completed_successfully'
for path in (root / 'infra').rglob('*.yaml'):
    list(yaml.safe_load_all(path.read_text()))
for path in (root / 'infra').rglob('*.yml'):
    list(yaml.safe_load_all(path.read_text()))
for path in (root / 'infra/k8s').glob('*.yaml'):
    for doc in yaml.safe_load_all(path.read_text()):
        if not doc or doc.get('kind') != 'Deployment':
            continue
        spec = doc['spec']['template']['spec']
        for container in spec['containers']:
            assert container.get('resources'), f'{path}: missing resources'
            assert container.get('readinessProbe'), f'{path}: missing readiness'
            assert container.get('livenessProbe'), f'{path}: missing liveness'
for path in [root / 'compose.yaml', *list((root / 'infra/k8s').glob('*.yaml'))]:
    assert not re.search(r'^[ \t]*[A-Z_]*PASSWORD:[ \t]*[A-Za-z0-9]', path.read_text(), re.I | re.M), f'Literal password in {path}'
print('PASS offline YAML, private port, version, migration dependency and probe/resource checks')
print('NOT TESTED here: image pulls, live services, NetworkPolicy enforcement or Kubernetes admission')
