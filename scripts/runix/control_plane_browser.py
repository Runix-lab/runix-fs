"""Server-rendered local account frontend; no production provisioner/readiness."""
import hmac
import os
import secrets
import stat
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlencode

from control_plane_errors import HttpError
from control_plane_oidc import CodeTokenClient, IdTokenVerifier, OidcFlow, digest
from control_plane_sessions import BrowserSessions, opaque
from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable
from marketplace_metering import MeteringConflict, MeteringOutbox
from marketplace_registration import RegistrationRegistry


def from_config(api, config):
    """Operator configuration only; read a private file without echoing secrets."""
    required = {'client_id', 'authorization_endpoint', 'token_endpoint', 'redirect_uri', 'jwks', 'client_secret_file'}
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError('Explicit browser provider configuration required')
    from control_plane_oidc import OidcProvider
    provider = OidcProvider(api.verifier.issuer, config['client_id'], config['authorization_endpoint'],
        config['token_endpoint'], config['redirect_uri'], allow_loopback_testing=api.scheme == 'http')
    if not isinstance(config['client_secret_file'], str):
        raise ValueError('Private secret path required')
    secret_path = Path(config['client_secret_file'])
    if not secret_path.is_absolute():
        raise ValueError('Absolute private client secret file required')
    descriptor = os.open(secret_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077 or info.st_size > 4096:
            raise ValueError('Private bounded client secret file required')
        with os.fdopen(descriptor, 'rb', closefd=False) as source:
            raw = source.read(4097)
        if not 1 <= len(raw) <= 4096:
            raise ValueError('Bounded secret required')
        secret = raw.decode('utf-8').removesuffix('\n')
    finally:
        os.close(descriptor)
    return BrowserAccountApp(api, provider, config['jwks'], CodeTokenClient(provider, secret))


class BrowserAccountApp:
    ROUTES = {'/account': 'GET', '/account/signin': 'GET', '/account/login': 'POST', '/account/callback': 'GET',
        '/account/logout': 'POST', '/account/organization': 'POST', '/account/bind': 'POST',
        '/account/style.css': 'GET', '/account/logo.png': 'GET', '/marketplace/register': 'POST'}
    COOKIE_KEYS = {'session', 'csrf', 'prelogin', 'correlation', 'pending'}

    def __init__(self, api, provider, jwks, token_client, clock=None):
        if (provider.issuer != api.verifier.issuer
                or provider.redirect_uri != api.origin + '/account/callback'
                or not isinstance(token_client, CodeTokenClient) or token_client.provider != provider):
            raise ValueError('Browser issuer/client/callback must match fixed control plane')
        self.api, self.provider, self.client = api, provider, token_client
        self.verifier = IdTokenVerifier(provider, jwks)
        self.clock = clock or (lambda: datetime.now(timezone.utc).replace(microsecond=0))
        self.prefix = '__Host-runix-fs-' if api.scheme == 'https' else 'runix-fs-local-'
        self.assets = Path(__file__).resolve().parent / 'static'
        self.logo = Path(__file__).resolve().parents[2] / 'images/marketplace/runix-logo-320.png'

    def cookie(self, key, value='', age=0):
        if key not in self.COOKIE_KEYS or (value and not opaque(value)):
            raise ValueError('Invalid owned cookie')
        value = f'{self.prefix}{key}={value}; Path=/; Max-Age={age}; HttpOnly; SameSite=Lax'
        if self.api.scheme == 'https':
            value += '; Secure'
        return ('Set-Cookie', value)

    def cookies(self, environ):
        raw = environ.get('HTTP_COOKIE', '')
        if not isinstance(raw, str) or len(raw) > 8192:
            raise HttpError(400, 'invalid_cookie')
        result = {}
        for part in raw.split(';'):
            name, separator, value = part.strip().partition('=')
            if not name.startswith(self.prefix):
                continue
            key = name[len(self.prefix):]
            if key not in self.COOKIE_KEYS:
                continue
            if not separator or key in result or not opaque(value):
                raise HttpError(400, 'invalid_cookie')
            result[key] = value
        return result

    def fields(self, environ, names):
        self.post_origin(environ)
        body = self.api._body(environ, 'application/x-www-form-urlencoded', 8192)
        result = self.query(body, names)
        if set(result) != names:
            raise HttpError(400, 'invalid_form')
        return result

    @staticmethod
    def query(raw, names):
        if len(raw) > 32768:
            raise HttpError(413, 'query_too_large')
        fields = parse_qs(raw, strict_parsing=True, keep_blank_values=True,
                          encoding='utf-8', errors='strict', max_num_fields=8)
        if not set(fields) <= names or any(len(value) != 1 for value in fields.values()):
            raise HttpError(400, 'invalid_parameters')
        return {key: value[0] for key, value in fields.items()}

    def post_origin(self, environ):
        if (environ.get('HTTP_ORIGIN') != self.api.origin
                or environ.get('HTTP_SEC_FETCH_SITE', 'same-origin') != 'same-origin'):
            raise HttpError(403, 'csrf_origin_denied')

    @staticmethod
    def page(title, content):
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + escape(title) + ' · Runix FS</title><link rel="stylesheet" href="/account/style.css">'
            '</head><body><header><a href="/account"><img src="/account/logo.png" width="40" height="40" alt="Runix">'
            '<span>Runix FS</span></a><span class="badge">Service setup</span></header><main>' + content +
            '</main><footer>Apache-2.0 software derived from Curvine. Commercial service by Runix.<br>'
            'Resource provisioning is not available in this environment.</footer></body></html>').encode()

    @staticmethod
    def form(action, csrf, label, extra=''):
        return ('<form action="' + action + '" method="post"><input type="hidden" name="csrf" value="'
                + escape(csrf, quote=True) + '">' + extra + '<button type="submit">' + label + '</button></form>')

    def login_page(self):
        csrf = secrets.token_urlsafe(32)
        content = ('<section class="intro"><p class="eyebrow">RUNIX FS CLOUD SERVICE</p><h1>Your files. Your organization.</h1>'
            '<p>Sign in to connect your Marketplace subscription and review its setup status.</p></section>'
            '<section class="card"><h2>Sign in to Runix</h2><p>Your identity provider handles your credentials.</p>'
            + self.form('/account/login', csrf, 'Continue to sign in') + '</section>')
        return 200, self.page('Sign in', content), [self.cookie('prelogin', csrf, 600)], 'text/html; charset=utf-8'

    def handle(self, environ):
        self.api._transport(environ)
        path, method = environ.get('PATH_INFO'), environ.get('REQUEST_METHOD')
        if method != self.ROUTES[path]:
            raise HttpError(405, 'method_not_allowed')
        if environ.get('HTTP_AUTHORIZATION'):
            raise HttpError(400, 'ambiguous_browser_credentials')
        raw_query = environ.get('QUERY_STRING', '')
        if path not in {'/account', '/account/callback'} and raw_query:
            raise HttpError(400, 'unexpected_query')
        if path in {'/account/style.css', '/account/logo.png'}:
            source, mime = ((self.assets / 'account.css', 'text/css; charset=utf-8')
                            if path.endswith('.css') else (self.logo, 'image/png'))
            return 200, source.read_bytes(), [], mime
        cookies, now = self.cookies(environ), self.clock()
        if path == '/account/signin':
            return self.login_page()
        box = MeteringOutbox(self.api.database, self.api.seller_account, self.api.product_code)
        try:
            registry = RegistrationRegistry(box, self.api.gateway, self.provider.issuer)
            sessions = BrowserSessions(box, self.provider.issuer, self.api.origin)
            flow = OidcFlow(box, self.provider, self.verifier, self.client)
            pending = digest(cookies['pending']) if 'pending' in cookies else None
            if path == '/marketplace/register':
                # Deliberate cross-origin AWS form; token resolution is mandatory.
                body = self.api._body(environ, 'application/x-www-form-urlencoded', 32768)
                fields = self.query(body, {'x-amzn-marketplace-token'})
                if set(fields) != {'x-amzn-marketplace-token'} or not fields['x-amzn-marketplace-token'].strip():
                    raise HttpError(400, 'invalid_registration_form')
                claim = registry.register(fields['x-amzn-marketplace-token'], now)
                if 'session' in cookies:
                    sessions.revoke(cookies['session'], now)
                return 303, b'', [self.cookie('pending', claim, 600), self.cookie('session'),
                    self.cookie('csrf'), self.cookie('correlation'), self.cookie('prelogin'),
                    ('Location', '/account')], 'text/html'
            if path == '/account/login':
                fields = self.fields(environ, {'csrf'})
                if (not opaque(fields['csrf']) or not opaque(cookies.get('prelogin'))
                        or not hmac.compare_digest(fields['csrf'], cookies['prelogin'])):
                    raise HttpError(403, 'csrf_denied')
                correlation = secrets.token_urlsafe(32)
                start = flow.begin(correlation, now, context=pending)
                return 303, b'', [self.cookie('correlation', correlation, 600), self.cookie('prelogin'),
                                 ('Location', start.authorization_url)], 'text/html'
            if path == '/account/callback':
                fields = self.query(raw_query, {'state', 'code', 'error', 'error_description', 'error_uri', 'iss'})
                if (not fields.get('state') or (('code' in fields) == ('error' in fields))
                        or ('iss' in fields and fields['iss'] != self.provider.issuer)):
                    raise HttpError(400, 'invalid_callback')
                principal = flow.complete(fields['state'], cookies.get('correlation'), now,
                    code=fields.get('code'), error=fields.get('error'), context=pending, clock=self.clock)
                current = self.clock()
                credentials = sessions.issue(principal, current, pending=pending, previous=cookies.get('session'))
                age = credentials.expires - int(current.timestamp())
                return 303, b'', [self.cookie('session', credentials.token, age), self.cookie('csrf', credentials.csrf, age),
                    self.cookie('correlation'), self.cookie('prelogin'), ('Location', '/account')], 'text/html'
            if path == '/account':
                query = self.query(raw_query, {'organization_id'})
                try:
                    session = sessions.authorize_post(cookies.get('session'), cookies.get('csrf'), cookies.get('csrf'), now)
                except MarketplaceDenied:
                    return self.login_page()
                organizations = registry.list_organizations(session.principal, now)
                content = '<p class="eyebrow">ACCOUNT</p><h1>Your organizations</h1>'
                content += '<p>Choose where to bind your Marketplace subscription. File system provisioning remains pending.</p>'
                if not organizations:
                    content += '<section class="card"><h2>Create your organization</h2><p>This creates an account workspace only.</p>'
                    content += self.form('/account/organization', cookies['csrf'], 'Create my organization') + '</section>'
                for organization in organizations:
                    org = organization['org']
                    link = '/account?' + urlencode({'organization_id': org})
                    content += '<a class="org" href="' + escape(link, quote=True) + '"><strong>' + escape(org) + '</strong><span>' + escape(organization['role']) + '</span></a>'
                if 'organization_id' in query:
                    org = query['organization_id']
                    purchases = registry.list_purchases(session.principal, org, now)
                    content += '<section class="card"><h2>Subscription setup</h2>'
                    if not purchases:
                        content += '<p>No Marketplace purchase is bound to this organization.</p>'
                    for purchase in purchases:
                        content += '<div class="purchase"><span class="badge">' + escape(purchase['state']) + '</span><p>Agreement: ' + escape(purchase['agreement']) + '</p></div>'
                    role = next((item['role'] for item in organizations if item['org'] == org), None)
                    if pending is not None and session.pending == pending and role in {'owner', 'admin'}:
                        content += '<p>A Marketplace registration is waiting to be bound.</p>'
                        content += self.form('/account/bind', cookies['csrf'], 'Bind subscription',
                            '<input type="hidden" name="organization_id" value="' + escape(org, quote=True) + '">')
                    content += '</section>'
                content += '<div class="signout">' + self.form('/account/logout', cookies['csrf'], 'Sign out of this console') + '</div>'
                return 200, self.page('Organizations', content), [], 'text/html; charset=utf-8'
            fields = self.fields(environ, {'csrf', 'organization_id'} if path == '/account/bind' else {'csrf'})
            session = sessions.authorize_post(cookies.get('session'), cookies.get('csrf'), fields['csrf'], now)
            if path == '/account/logout':
                sessions.revoke(cookies['session'], now)
                return 303, b'', [self.cookie(key) for key in sorted(self.COOKIE_KEYS)] + [('Location', '/account')], 'text/html'
            if path == '/account/organization':
                with box.transaction():
                    current_session = sessions.authorize_post(cookies.get('session'), cookies.get('csrf'), fields['csrf'], now)
                    org = registry.create_personal_organization(current_session.principal, now)
                return 303, b'', [('Location', '/account?' + urlencode({'organization_id': org}))], 'text/html'
            if pending is None or session.pending != pending:
                raise HttpError(403, 'pending_purchase_denied')
            with box.transaction():
                registry.bind(session.principal, fields['organization_id'], cookies['pending'], now)
                sessions.clear_pending(cookies['session'], pending, now)
            return 303, b'', [self.cookie('pending'), ('Location', '/account?' + urlencode({'organization_id': fields['organization_id']}))], 'text/html'
        finally:
            box.close()

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        if path not in self.ROUTES:
            return self.api(environ, start_response)
        try:
            status, body, headers, mime = self.handle(environ)
        except HttpError as error:
            status, code = error.status, error.code
        except MarketplaceDenied:
            status, code = 403, 'login_session_or_organization_denied'
        except MarketplaceUnavailable:
            status, code = 503, 'marketplace_unavailable'
        except MeteringConflict:
            status, code = 409, 'identity_or_state_conflict'
        except (ValueError, TypeError, KeyError, UnicodeError):
            status, code = 400, 'invalid_request'
        except Exception:
            status, code = 503, 'account_unavailable'
        else:
            code = None
        if code is not None:
            body, mime, headers = self.page('Request unavailable', '<h1>Request unavailable</h1><p>' + code + '</p><a href="/account">Return to account</a>'), 'text/html; charset=utf-8', []
        headers += [('Content-Type', mime), ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
            ('Referrer-Policy', 'no-referrer'), ('X-Content-Type-Options', 'nosniff'),
            ('Content-Security-Policy', "default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")]
        if self.api.scheme == 'https':
            headers.append(('Strict-Transport-Security', 'max-age=31536000'))
        start_response(f'{status} {HTTPStatus(status).phrase}', headers)
        return [body]
