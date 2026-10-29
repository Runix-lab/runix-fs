"""Fresh cached Casdoor fixture, using an isolated network/loopback HTTP client.

All state is disposable and independent from existing identities. No host port,
cloud resource, image pull, browser cookie, real account or production provider.
"""
import json
import os
import secrets
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from local_s3_smoke import SDK_IMAGE

IMAGE = 'casbin/casdoor@sha256:eb7a478c9d74494ebb5fd6ef3cfc7a6d40ea07d03bc24678bbd42fd3a9d00bdf'
BROKER = r'''
import base64,json,sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler,ProxyHandler,Request,build_opener
class NoRedirect(HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs): return None
packet=json.load(sys.stdin)
url=packet['url']
p=urlsplit(url)
assert p.scheme=='http' and p.hostname=='127.0.0.1' and p.port==8000 and not p.username and not p.password
request=Request(url,data=base64.b64decode(packet['data']) if packet['data'] is not None else None,
                headers=packet['headers'],method=packet['method'])
try:
 response=build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=5)
except HTTPError as error:
 response=error
except Exception as error:
 print(json.dumps({'status':599,'category':type(error).__name__,'headers':{},'body':''}));sys.exit(0)
with response:
 body=response.read(65537)
 assert len(body)<=65536
 print(json.dumps({'status':response.status,'headers':dict(response.headers),'body':base64.b64encode(body).decode()}))
'''


@dataclass(frozen=True)
class OidcFixture:
    runtime: Path
    origin: str
    client_container: str
    client_id: str
    client_secret: str = field(repr=False)
    organization: str
    application: str
    username: str
    password: str = field(repr=False)
    redirect_uri: str

    def request(self, url, *, data=None, headers=None, method='GET'):
        import base64
        packet = {'url': url, 'data': base64.b64encode(data).decode() if data is not None else None,
                  'headers': headers or {}, 'method': method}
        completed = subprocess.run(['docker', 'exec', '-i', self.client_container, 'python', '-c', BROKER],
            input=json.dumps(packet), capture_output=True, text=True, check=True, timeout=15)
        response = json.loads(completed.stdout)
        return response['status'], response['headers'], base64.b64decode(response['body'])


@contextmanager
def provider():
    def docker(*args, check=True, **kwargs):
        return subprocess.run(['docker', *args], timeout=30, check=check, text=True, **kwargs)
    for image in (IMAGE, SDK_IMAGE):
        docker('image', 'inspect', image, stdout=subprocess.DEVNULL)
    runtime = Path(tempfile.mkdtemp(prefix='runix-oidc-smoke-'))
    runtime.chmod(0o700)
    print('Local synthetic provider directory:', runtime, flush=True)
    name = 'runix-oidc-smoke-' + uuid.uuid4().hex[:12]
    client, network = name + '-client', name + '-network'
    fixture = OidcFixture(runtime, 'http://127.0.0.1:8000', client,
        secrets.token_urlsafe(24), secrets.token_urlsafe(32), 'runix-local-test', 'runix-fs-local-test',
        'runix-test-user', secrets.token_urlsafe(24), 'http://127.0.0.1:8000/test-only-callback')
    seed = {
        'organizations': [{'owner': 'admin', 'name': fixture.organization, 'displayName': 'Local synthetic OIDC test',
                           'passwordType': 'bcrypt', 'languages': ['en'], 'defaultApplication': fixture.application}],
        'applications': [{'owner': 'admin', 'name': fixture.application, 'displayName': 'Runix FS local protocol test',
                          'organization': fixture.organization, 'cert': 'cert-built-in', 'enablePassword': True,
                          'enableSignUp': False, 'clientId': fixture.client_id, 'clientSecret': fixture.client_secret,
                          'redirectUris': [fixture.redirect_uri], 'grantTypes': ['authorization_code'],
                          'tokenFormat': 'JWT', 'expireInHours': 1, 'providers': [],
                          'signinMethods': [{'name': 'Password', 'displayName': 'Password', 'rule': 'All'}]}],
        'users': [{'owner': fixture.organization, 'name': fixture.username, 'type': 'normal-user',
                   'password': fixture.password, 'displayName': 'Synthetic integration user',
                   'isAdmin': False, 'signupApplication': fixture.application}],
    }
    envfile = runtime / 'fixture.env'
    try:
        descriptor = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            values = {'driverName': 'sqlite', 'dataSourceName': '/conf/runix_test.db', 'dbName': 'casdoor',
                      'runmode': 'prod', 'origin': fixture.origin, 'originFrontend': fixture.origin,
                      'initDataFile': '/conf/runix-init-data.json', 'initAdminPassword': secrets.token_urlsafe(32),
                      'disableVersionCheck': 'true', 'RUNIX_TEST_INIT_DATA': json.dumps(seed, separators=(',', ':'))}
            output.write(''.join(key + '=' + value + '\n' for key, value in values.items()))
        docker('network', 'create', '--internal', network, stdout=subprocess.DEVNULL)
        docker('run', '-d', '--pull', 'never', '--name', name, '--network', network,
               '--env-file', str(envfile), '--cpus', '1', '--memory', '768m', '--entrypoint', '/bin/sh', IMAGE, '-c',
               'umask 077; printf "%s" "$RUNIX_TEST_INIT_DATA" > /conf/runix-init-data.json; '
               'unset RUNIX_TEST_INIT_DATA; exec /server', stdout=subprocess.DEVNULL)
        # The client shares only this new provider's network namespace. Keys and
        # signed tokens stay on the host test process; HTTP bytes cross stdin/stdout.
        docker('run', '-d', '--pull', 'never', '--name', client, '--network', 'container:' + name,
               '--cpus', '1', '--memory', '256m', SDK_IMAGE, 'python', '-c',
               'import time; time.sleep(900)', stdout=subprocess.DEVNULL)
        for attempt in range(45):
            status, _, body = fixture.request(fixture.origin + '/.well-known/openid-configuration')
            if status == 200:
                metadata = json.loads(body)
                if metadata.get('issuer') != fixture.origin:
                    raise RuntimeError('Fixture issuer differs from its actual loopback origin')
                break
            if attempt == 44:
                raise RuntimeError('Local identity provider did not become ready; HTTP status ' + str(status))
            time.sleep(1)
        for container in (name, client):
            state = json.loads(docker('inspect', container, capture_output=True).stdout)[0]
            if state['HostConfig'].get('PortBindings') or state['HostConfig']['Privileged'] or state['Mounts']:
                raise RuntimeError('Unexpected identity fixture privilege, ports or mounts')
            if container == name and (state['Config']['User'] != '1000'
                    or set(state['NetworkSettings']['Networks']) != {network}):
                raise RuntimeError('Unexpected provider identity/network')
            if container == client and state['HostConfig']['NetworkMode'] != 'container:' + state_for_provider:
                raise RuntimeError('Unexpected HTTP-client namespace')
            if container == name:
                state_for_provider = state['Id']
        if not json.loads(docker('network', 'inspect', network, capture_output=True).stdout)[0]['Internal']:
            raise RuntimeError('Fixture network is not internal')
        (runtime / 'provider-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        yield fixture
    finally:
        cleanup_owned(docker, runtime, envfile, name, client, network)


def cleanup_owned(docker, runtime, envfile, name, client, network):
    """Attempt every owned cleanup even if log capture/removal fails."""
    failures = []
    try:
        try:
            with (runtime / 'provider-private.log').open('w') as log:
                docker('logs', name, check=False, stdout=log, stderr=subprocess.STDOUT)
        except Exception:
            # Logs are diagnostics; inability to capture must not retain resources.
            pass
        try:
            docker('rm', '-fv', client, name, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            failures.append('containers')
        try:
            docker('network', 'rm', network, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            failures.append('network')
    finally:
        envfile.unlink(missing_ok=True)
    try:
        containers = docker('ps', '-a', '--format', '{{.Names}}', capture_output=True).stdout.splitlines()
        networks = docker('network', 'ls', '--format', '{{.Name}}', capture_output=True).stdout.splitlines()
        if name in containers or client in containers or network in networks:
            failures.append('inventory')
    except Exception:
        failures.append('inventory')
    if failures:
        raise RuntimeError('Identity fixture cleanup could not be confirmed') from None
    (runtime / 'cleanup-result.json').write_text(json.dumps({
        'owned_containers_remaining': 0, 'owned_networks_remaining': 0,
        'secret_env_file_removed': not envfile.exists()}) + '\n')


if __name__ == '__main__':
    with provider() as fixture:
        metadata = json.loads((fixture.runtime / 'provider-metadata.json').read_text())
        print(json.dumps({'runtime': str(fixture.runtime), 'issuer': metadata['issuer'],
                          'grant_types_supported': metadata.get('grant_types_supported'),
                          'code_challenge_methods_supported': metadata.get('code_challenge_methods_supported')}))
