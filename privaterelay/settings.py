"""
Django settings for privaterelay project.

Generated by 'django-admin startproject' using Django 2.2.2.

For more information on this file, see
https://docs.djangoproject.com/en/2.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/2.2/ref/settings/
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, TYPE_CHECKING, cast, get_args
import ipaddress
import os
import sys


from decouple import config, Choices, Csv
import django_stubs_ext
import markus
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import ignore_logger
from hashlib import sha256
import base64

from django.conf.global_settings import LANGUAGES as DEFAULT_LANGUAGES

import dj_database_url

from .types import RELAY_CHANNEL_NAME

if TYPE_CHECKING:
    import wsgiref.headers

try:
    # Silk is a live profiling and inspection tool for the Django framework
    # https://github.com/jazzband/django-silk
    import silk

    assert silk  # Suppress "imported but unused" warning

    HAS_SILK = True
except ImportError:
    HAS_SILK = False

try:
    from privaterelay.glean.server_events import GLEAN_EVENT_MOZLOG_TYPE
except ImportError:
    # File may not be generated yet. Will be checked at initialization
    GLEAN_EVENT_MOZLOG_TYPE = "glean-server-event"

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP_DIR = os.path.join(BASE_DIR, "tmp")
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/

# defaulting to blank to be production-broken by default
SECRET_KEY = config("SECRET_KEY", None)
SECRET_KEY_FALLBACKS = config("SECRET_KEY_FALLBACKS", "", cast=Csv())
SITE_ORIGIN: str | None = config("SITE_ORIGIN", None)

ORIGIN_CHANNEL_MAP: dict[str, RELAY_CHANNEL_NAME] = {
    "http://127.0.0.1:8000": "local",
    "https://dev.fxprivaterelay.nonprod.cloudops.mozgcp.net": "dev",
    "https://stage.fxprivaterelay.nonprod.cloudops.mozgcp.net": "stage",
    "https://relay.firefox.com": "prod",
}
RELAY_CHANNEL: RELAY_CHANNEL_NAME = cast(
    RELAY_CHANNEL_NAME,
    config(
        "RELAY_CHANNEL",
        default=ORIGIN_CHANNEL_MAP.get(SITE_ORIGIN or "", "local"),
        cast=Choices(get_args(RELAY_CHANNEL_NAME), cast=str),
    ),
)

DEBUG = config("DEBUG", False, cast=bool)
if DEBUG:
    INTERNAL_IPS = config("DJANGO_INTERNAL_IPS", default="", cast=Csv())
IN_PYTEST: bool = "pytest" in sys.modules
USE_SILK = DEBUG and HAS_SILK and not IN_PYTEST

# Honor the 'X-Forwarded-Proto' header for request.is_secure()
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_HOST = config("DJANGO_SECURE_SSL_HOST", None)
SECURE_SSL_REDIRECT = config("DJANGO_SECURE_SSL_REDIRECT", False, cast=bool)
SECURE_REDIRECT_EXEMPT = [
    r"^__version__",
    r"^__heartbeat__",
    r"^__lbheartbeat__",
]
SECURE_HSTS_INCLUDE_SUBDOMAINS = config(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False, cast=bool
)
SECURE_HSTS_PRELOAD = config("DJANGO_SECURE_HSTS_PRELOAD", False, cast=bool)
SECURE_HSTS_SECONDS = config("DJANGO_SECURE_HSTS_SECONDS", None)
SECURE_BROWSER_XSS_FILTER = config("DJANGO_SECURE_BROWSER_XSS_FILTER", True)
SESSION_COOKIE_SECURE = config("DJANGO_SESSION_COOKIE_SECURE", False, cast=bool)
CSRF_COOKIE_SECURE = config("DJANGO_CSRF_COOKIE_SECURE", False, cast=bool)

#
# Setup CSP
#

BASKET_ORIGIN = config("BASKET_ORIGIN", "https://basket.mozilla.org")

# maps FxA / Mozilla account profile hosts to respective hosts for CSP
FXA_BASE_ORIGIN: str = config("FXA_BASE_ORIGIN", "https://accounts.firefox.com")
if FXA_BASE_ORIGIN == "https://accounts.firefox.com":
    _AVATAR_IMG_SRC = [
        "firefoxusercontent.com",
        "https://profile.accounts.firefox.com",
    ]
    _ACCOUNT_CONNECT_SRC = [FXA_BASE_ORIGIN]
else:
    assert FXA_BASE_ORIGIN == "https://accounts.stage.mozaws.net"
    _AVATAR_IMG_SRC = [
        "mozillausercontent.com",
        "https://profile.stage.mozaws.net",
    ]
    _ACCOUNT_CONNECT_SRC = [
        FXA_BASE_ORIGIN,
        # fxaFlowTracker.ts will try this if runtimeData is slow
        "https://accounts.firefox.com",
    ]

API_DOCS_ENABLED = config("API_DOCS_ENABLED", False, cast=bool) or DEBUG
_CSP_SCRIPT_INLINE = API_DOCS_ENABLED or USE_SILK

# When running locally, styles might get refreshed while the server is running, so their
# hashes would get oudated. Hence, we just allow all of them.
_CSP_STYLE_INLINE = API_DOCS_ENABLED or RELAY_CHANNEL == "local"

if API_DOCS_ENABLED:
    _API_DOCS_CSP_IMG_SRC = ["data:", "https://cdn.redoc.ly"]
    _API_DOCS_CSP_STYLE_SRC = ["https://fonts.googleapis.com"]
    _API_DOCS_CSP_FONT_SRC = ["https://fonts.gstatic.com"]
    _API_DOCS_CSP_WORKER_SRC = ["blob:"]
else:
    _API_DOCS_CSP_IMG_SRC = []
    _API_DOCS_CSP_STYLE_SRC = []
    _API_DOCS_CSP_FONT_SRC = []
    _API_DOCS_CSP_WORKER_SRC = []

# Next.js dynamically inserts the relevant styles when switching pages,
# by injecting them as inline styles. We need to explicitly allow those styles
# in our Content Security Policy.
_CSP_STYLE_HASHES: list[str] = []
if _CSP_STYLE_INLINE:
    # 'unsafe-inline' is not compatible with hash sources
    _CSP_STYLE_HASHES = []
else:
    # When running in production, we want to disallow inline styles that are
    # not set by us, so we use an explicit allowlist with the hashes of the
    # styles generated by Next.js.
    _next_css_path = Path(STATIC_ROOT) / "_next" / "static" / "css"
    for path in _next_css_path.glob("*.css"):
        # Use sha256 hashes, to keep in sync with Chrome.
        # When CSP rules fail in Chrome, it provides the sha256 hash that would
        # have matched, useful for debugging.
        content = open(path, "rb").read()
        the_hash = base64.b64encode(sha256(content).digest()).decode()
        _CSP_STYLE_HASHES.append(f"'sha256-{the_hash}'")
    _CSP_STYLE_HASHES.sort()

    # Add the hash for an empty string (sha256-47DEQp...)
    # next,js injects an empty style element and then adds the content.
    # This hash avoids a spurious CSP error.
    empty_hash = base64.b64encode(sha256().digest()).decode()
    _CSP_STYLE_HASHES.append(f"'sha256-{empty_hash}'")

CSP_DEFAULT_SRC = ["'self'"]
CSP_CONNECT_SRC = [
    "'self'",
    "https://www.google-analytics.com/",
    "https://location.services.mozilla.com",
    "https://api.stripe.com",
    BASKET_ORIGIN,
] + _ACCOUNT_CONNECT_SRC
CSP_FONT_SRC = ["'self'"] + _API_DOCS_CSP_FONT_SRC + ["https://relay.firefox.com/"]
CSP_IMG_SRC = ["'self'"] + _AVATAR_IMG_SRC + _API_DOCS_CSP_IMG_SRC
CSP_SCRIPT_SRC = (
    ["'self'"]
    + (["'unsafe-inline'"] if _CSP_SCRIPT_INLINE else [])
    + [
        "https://www.google-analytics.com/",
        "https://js.stripe.com/",
    ]
)
CSP_WORKER_SRC = _API_DOCS_CSP_WORKER_SRC or None
CSP_OBJECT_SRC = ["'none'"]
CSP_FRAME_SRC = ["https://js.stripe.com", "https://hooks.stripe.com"]
CSP_STYLE_SRC = (
    ["'self'"]
    + (["'unsafe-inline'"] if _CSP_STYLE_INLINE else [])
    + _API_DOCS_CSP_STYLE_SRC
    + _CSP_STYLE_HASHES
)

REFERRER_POLICY = "strict-origin-when-cross-origin"

ALLOWED_HOSTS: list[str] = []
DJANGO_ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOST", "", cast=Csv())
if DJANGO_ALLOWED_HOSTS:
    ALLOWED_HOSTS += DJANGO_ALLOWED_HOSTS
DJANGO_ALLOWED_SUBNET = config("DJANGO_ALLOWED_SUBNET", None)
if DJANGO_ALLOWED_SUBNET:
    ALLOWED_HOSTS += [str(ip) for ip in ipaddress.IPv4Network(DJANGO_ALLOWED_SUBNET)]


# Get our backing resource configs to check if we should install the app
ADMIN_ENABLED = config("ADMIN_ENABLED", False, cast=bool)


AWS_REGION: str | None = config("AWS_REGION", None)
AWS_ACCESS_KEY_ID = config("AWS_ACCESS_KEY_ID", None)
AWS_SECRET_ACCESS_KEY = config("AWS_SECRET_ACCESS_KEY", None)
AWS_SNS_TOPIC = set(config("AWS_SNS_TOPIC", "", cast=Csv()))
AWS_SNS_KEY_CACHE = config("AWS_SNS_KEY_CACHE", "default")
AWS_SES_CONFIGSET: str | None = config("AWS_SES_CONFIGSET", None)
AWS_SQS_EMAIL_QUEUE_URL = config("AWS_SQS_EMAIL_QUEUE_URL", None)
AWS_SQS_EMAIL_DLQ_URL = config("AWS_SQS_EMAIL_DLQ_URL", None)

# Dead-Letter Queue (DLQ) for SNS push subscription
AWS_SQS_QUEUE_URL = config("AWS_SQS_QUEUE_URL", None)

RELAY_FROM_ADDRESS: str | None = config("RELAY_FROM_ADDRESS", None)
GOOGLE_ANALYTICS_ID = config("GOOGLE_ANALYTICS_ID", None)
GOOGLE_APPLICATION_CREDENTIALS: str = config("GOOGLE_APPLICATION_CREDENTIALS", "")
GOOGLE_CLOUD_PROFILER_CREDENTIALS_B64: str = config(
    "GOOGLE_CLOUD_PROFILER_CREDENTIALS_B64", ""
)
INCLUDE_VPN_BANNER = config("INCLUDE_VPN_BANNER", False, cast=bool)
RECRUITMENT_BANNER_LINK = config("RECRUITMENT_BANNER_LINK", None)
RECRUITMENT_BANNER_TEXT = config("RECRUITMENT_BANNER_TEXT", None)
RECRUITMENT_EMAIL_BANNER_TEXT = config("RECRUITMENT_EMAIL_BANNER_TEXT", None)
RECRUITMENT_EMAIL_BANNER_LINK = config("RECRUITMENT_EMAIL_BANNER_LINK", None)

PHONES_ENABLED: bool = config("PHONES_ENABLED", False, cast=bool)
PHONES_NO_CLIENT_CALLS_IN_TEST = False  # Override in tests that do not test clients
TWILIO_ACCOUNT_SID: str | None = config("TWILIO_ACCOUNT_SID", None)
TWILIO_AUTH_TOKEN: str | None = config("TWILIO_AUTH_TOKEN", None)
TWILIO_MAIN_NUMBER: str | None = config("TWILIO_MAIN_NUMBER", None)
TWILIO_SMS_APPLICATION_SID: str | None = config("TWILIO_SMS_APPLICATION_SID", None)
TWILIO_MESSAGING_SERVICE_SID: list[str] = config(
    "TWILIO_MESSAGING_SERVICE_SID", "", cast=Csv()
)
TWILIO_TEST_ACCOUNT_SID: str | None = config("TWILIO_TEST_ACCOUNT_SID", None)
TWILIO_TEST_AUTH_TOKEN: str | None = config("TWILIO_TEST_AUTH_TOKEN", None)
TWILIO_ALLOWED_COUNTRY_CODES = {
    code.upper() for code in config("TWILIO_ALLOWED_COUNTRY_CODES", "US,CA", cast=Csv())
}
MAX_MINUTES_TO_VERIFY_REAL_PHONE: int = config(
    "MAX_MINUTES_TO_VERIFY_REAL_PHONE", 5, cast=int
)
MAX_TEXTS_PER_BILLING_CYCLE: int = config("MAX_TEXTS_PER_BILLING_CYCLE", 75, cast=int)
MAX_MINUTES_PER_BILLING_CYCLE: int = config(
    "MAX_MINUTES_PER_BILLING_CYCLE", 50, cast=int
)
DAYS_PER_BILLING_CYCLE = config("DAYS_PER_BILLING_CYCLE", 30, cast=int)
MAX_DAYS_IN_MONTH = 31
IQ_ENABLED = config("IQ_ENABLED", False, cast=bool)
IQ_FOR_VERIFICATION: bool = config("IQ_FOR_VERIFICATION", False, cast=bool)
IQ_FOR_NEW_NUMBERS = config("IQ_FOR_NEW_NUMBERS", False, cast=bool)
IQ_MAIN_NUMBER: str = config("IQ_MAIN_NUMBER", "")
IQ_OUTBOUND_API_KEY: str = config("IQ_OUTBOUND_API_KEY", "")
IQ_INBOUND_API_KEY = config("IQ_INBOUND_API_KEY", "")
IQ_MESSAGE_API_ORIGIN = config(
    "IQ_MESSAGE_API_ORIGIN", "https://messagebroker.inteliquent.com"
)
IQ_MESSAGE_PATH = "/msgbroker/rest/publishMessages"
IQ_PUBLISH_MESSAGE_URL: str = f"{IQ_MESSAGE_API_ORIGIN}{IQ_MESSAGE_PATH}"

DJANGO_STATSD_ENABLED = config("DJANGO_STATSD_ENABLED", False, cast=bool)
STATSD_DEBUG = config("STATSD_DEBUG", False, cast=bool)
STATSD_ENABLED: bool = DJANGO_STATSD_ENABLED or STATSD_DEBUG
STATSD_HOST = config("DJANGO_STATSD_HOST", "127.0.0.1")
STATSD_PORT = config("DJANGO_STATSD_PORT", "8125")
STATSD_PREFIX = config("DJANGO_STATSD_PREFIX", "fx.private.relay")

SERVE_ADDON = config("SERVE_ADDON", None)

# Application definition
INSTALLED_APPS = [
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.sites",
    "django_filters",
    "django_ftl.apps.DjangoFtlConfig",
    "dockerflow.django",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.fxa",
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    "waffle",
    "privaterelay.apps.PrivateRelayConfig",
    "api.apps.ApiConfig",
]

if API_DOCS_ENABLED:
    INSTALLED_APPS += [
        "drf_spectacular",
        "drf_spectacular_sidecar",
    ]

if DEBUG:
    INSTALLED_APPS += [
        "debug_toolbar",
    ]

if USE_SILK:
    INSTALLED_APPS.append("silk")

if ADMIN_ENABLED:
    INSTALLED_APPS += [
        "django.contrib.admin",
    ]

if AWS_SES_CONFIGSET and AWS_SNS_TOPIC:
    INSTALLED_APPS += [
        "emails.apps.EmailsConfig",
    ]

if PHONES_ENABLED:
    INSTALLED_APPS += [
        "phones.apps.PhonesConfig",
    ]


# statsd middleware has to be first to catch errors in everything else
def _get_initial_middleware() -> list[str]:
    if STATSD_ENABLED:
        return [
            "privaterelay.middleware.ResponseMetrics",
        ]
    return []


MIDDLEWARE = _get_initial_middleware()

if USE_SILK:
    MIDDLEWARE.append("silk.middleware.SilkyMiddleware")
if DEBUG:
    MIDDLEWARE.append("debug_toolbar.middleware.DebugToolbarMiddleware")

MIDDLEWARE += [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "privaterelay.middleware.RedirectRootIfLoggedIn",
    "privaterelay.middleware.RelayStaticFilesMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django_ftl.middleware.activate_from_request_language_code",
    "django_referrer_policy.middleware.ReferrerPolicyMiddleware",
    "dockerflow.django.middleware.DockerflowMiddleware",
    "waffle.middleware.WaffleMiddleware",
    "privaterelay.middleware.AddDetectedCountryToRequestAndResponseHeaders",
    "privaterelay.middleware.StoreFirstVisit",
]

ROOT_URLCONF = "privaterelay.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            os.path.join(BASE_DIR, "privaterelay", "templates"),
        ],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

RELAY_FIREFOX_DOMAIN: str = config("RELAY_FIREFOX_DOMAIN", "relay.firefox.com")
MOZMAIL_DOMAIN: str = config("MOZMAIL_DOMAIN", "mozmail.com")
MAX_NUM_FREE_ALIASES: int = config("MAX_NUM_FREE_ALIASES", 5, cast=int)
PERIODICAL_PREMIUM_PROD_ID: str = config("PERIODICAL_PREMIUM_PROD_ID", "")
PREMIUM_PLAN_ID_US_MONTHLY: str = config(
    "PREMIUM_PLAN_ID_US_MONTHLY", "price_1LXUcnJNcmPzuWtRpbNOajYS"
)
PREMIUM_PLAN_ID_US_YEARLY: str = config(
    "PREMIUM_PLAN_ID_US_YEARLY", "price_1LXUdlJNcmPzuWtRKTYg7mpZ"
)
PHONE_PROD_ID = config("PHONE_PROD_ID", "")
PHONE_PLAN_ID_US_MONTHLY: str = config(
    "PHONE_PLAN_ID_US_MONTHLY", "price_1Li0w8JNcmPzuWtR2rGU80P3"
)
PHONE_PLAN_ID_US_YEARLY: str = config(
    "PHONE_PLAN_ID_US_YEARLY", "price_1Li15WJNcmPzuWtRIh0F4VwP"
)
BUNDLE_PROD_ID = config("BUNDLE_PROD_ID", "")
BUNDLE_PLAN_ID_US: str = config("BUNDLE_PLAN_ID_US", "price_1LwoSDJNcmPzuWtR6wPJZeoh")

SUBSCRIPTIONS_WITH_UNLIMITED: list[str] = config(
    "SUBSCRIPTIONS_WITH_UNLIMITED", default="", cast=Csv()
)
SUBSCRIPTIONS_WITH_PHONE: list[str] = config(
    "SUBSCRIPTIONS_WITH_PHONE", default="", cast=Csv()
)
SUBSCRIPTIONS_WITH_VPN: list[str] = config(
    "SUBSCRIPTIONS_WITH_VPN", default="", cast=Csv()
)

MAX_ONBOARDING_AVAILABLE = config("MAX_ONBOARDING_AVAILABLE", 0, cast=int)
MAX_ONBOARDING_FREE_AVAILABLE = config("MAX_ONBOARDING_FREE_AVAILABLE", 3, cast=int)

MAX_ADDRESS_CREATION_PER_DAY = config("MAX_ADDRESS_CREATION_PER_DAY", 100, cast=int)
MAX_REPLIES_PER_DAY = config("MAX_REPLIES_PER_DAY", 100, cast=int)
MAX_FORWARDED_PER_DAY = config("MAX_FORWARDED_PER_DAY", 1000, cast=int)
MAX_FORWARDED_EMAIL_SIZE_PER_DAY = config(
    "MAX_FORWARDED_EMAIL_SIZE_PER_DAY", 1_000_000_000, cast=int
)
PREMIUM_FEATURE_PAUSED_DAYS: int = config(
    "ACCOUNT_PREMIUM_FEATURE_PAUSED_DAYS", 1, cast=int
)

SOFT_BOUNCE_ALLOWED_DAYS: int = config("SOFT_BOUNCE_ALLOWED_DAYS", 1, cast=int)
HARD_BOUNCE_ALLOWED_DAYS: int = config("HARD_BOUNCE_ALLOWED_DAYS", 30, cast=int)

WSGI_APPLICATION = "privaterelay.wsgi.application"

# Database
# https://docs.djangoproject.com/en/2.2/ref/settings/#databases

DATABASES = {
    "default": dj_database_url.config(
        default="sqlite:///%s" % os.path.join(BASE_DIR, "db.sqlite3")
    )
}
# Optionally set a test database name.
# This is useful for forcing an on-disk database for SQLite.
TEST_DB_NAME = config("TEST_DB_NAME", "")
if TEST_DB_NAME:
    DATABASES["default"]["TEST"] = {"NAME": TEST_DB_NAME}

REDIS_URL = config("REDIS_URL", "")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        }
    }
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"
elif RELAY_CHANNEL == "local":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }

# Password validation
# https://docs.djangoproject.com/en/2.2/ref/settings/#auth-password-validators
# only needed when admin UI is enabled
if ADMIN_ENABLED:
    _DJANGO_PWD_VALIDATION = "django.contrib.auth.password_validation"
    AUTH_PASSWORD_VALIDATORS = [
        {"NAME": _DJANGO_PWD_VALIDATION + ".UserAttributeSimilarityValidator"},
        {"NAME": _DJANGO_PWD_VALIDATION + ".MinimumLengthValidator"},
        {"NAME": _DJANGO_PWD_VALIDATION + ".CommonPasswordValidator"},
        {"NAME": _DJANGO_PWD_VALIDATION + ".NumericPasswordValidator"},
    ]


# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = "en"

# Mozilla l10n directories use lang-locale language codes,
# so we need to add those to LANGUAGES so Django's LocaleMiddleware
# can find them.
LANGUAGES = DEFAULT_LANGUAGES + [
    ("zh-tw", "Chinese"),
    ("zh-cn", "Chinese"),
    ("es-es", "Spanish"),
    ("pt-pt", "Portuguese"),
    ("skr", "Saraiki"),
]

TIME_ZONE = "UTC"

USE_I18N = True


USE_TZ = True

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "frontend/out"),
]
# Static files (the front-end in /frontend/)
# https://whitenoise.evans.io/en/stable/django.html#using-whitenoise-with-webpack-browserify-latest-js-thing
STATIC_URL = "/"
if DEBUG:
    # In production, we run collectstatic to index all static files.
    # However, when running locally, we want to automatically pick up
    # all files spewed out by `npm run watch` in /frontend/out,
    # and we're fine with the performance impact of that.
    WHITENOISE_ROOT = os.path.join(BASE_DIR, "frontend/out")
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "privaterelay.storage.RelayStaticFilesStorage",
    },
}

# Relay does not support user-uploaded files
MEDIA_ROOT = None
MEDIA_URL = None

WHITENOISE_INDEX_FILE = True


# See
# https://whitenoise.evans.io/en/stable/django.html#WHITENOISE_ADD_HEADERS_FUNCTION
# Intended to ensure that the homepage does not get cached in our CDN,
# so that the `RedirectRootIfLoggedIn` middleware can kick in for logged-in
# users.
def set_index_cache_control_headers(
    headers: wsgiref.headers.Headers, path: str, url: str
) -> None:
    if DEBUG:
        home_path = os.path.join(BASE_DIR, "frontend/out", "index.html")
    else:
        home_path = os.path.join(STATIC_ROOT, "index.html")
    if path == home_path:
        headers["Cache-Control"] = "no-cache, public"


WHITENOISE_ADD_HEADERS_FUNCTION = set_index_cache_control_headers

SITE_ID = 1

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

SOCIALACCOUNT_PROVIDERS = {
    "fxa": {
        # Note: to request "profile" scope, must be a trusted Mozilla client
        "SCOPE": ["profile", "https://identity.mozilla.com/account/subscriptions"],
        "AUTH_PARAMS": {"access_type": "offline"},
        "OAUTH_ENDPOINT": config(
            "FXA_OAUTH_ENDPOINT", "https://oauth.accounts.firefox.com/v1"
        ),
        "PROFILE_ENDPOINT": config(
            "FXA_PROFILE_ENDPOINT", "https://profile.accounts.firefox.com/v1"
        ),
        "VERIFIED_EMAIL": True,  # Assume FxA primary email is verified
    }
}

SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_AUTO_SIGNUP = True
SOCIALACCOUNT_LOGIN_ON_GET = True
SOCIALACCOUNT_STORE_TOKENS = True

ACCOUNT_ADAPTER = "privaterelay.allauth.AccountAdapter"
ACCOUNT_PRESERVE_USERNAME_CASING = False
ACCOUNT_USERNAME_REQUIRED = False

FXA_SETTINGS_URL = config("FXA_SETTINGS_URL", f"{FXA_BASE_ORIGIN}/settings")
FXA_SUBSCRIPTIONS_URL = config(
    "FXA_SUBSCRIPTIONS_URL", f"{FXA_BASE_ORIGIN}/subscriptions"
)
# check https://mozilla.github.io/ecosystem-platform/api#tag/Subscriptions/operation/getOauthMozillasubscriptionsCustomerBillingandsubscriptions  # noqa: E501 (line too long)
FXA_ACCOUNTS_ENDPOINT = config(
    "FXA_ACCOUNTS_ENDPOINT",
    "https://api.accounts.firefox.com/v1",
)
FXA_SUPPORT_URL = config("FXA_SUPPORT_URL", f"{FXA_BASE_ORIGIN}/support/")

LOGGING = {
    "version": 1,
    "filters": {
        "request_id": {
            "()": "dockerflow.logging.RequestIdLogFilter",
        },
    },
    "formatters": {
        "json": {
            "()": "dockerflow.logging.JsonLogFormatter",
            "logger_name": "fx-private-relay",
        }
    },
    "handlers": {
        "console_out": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "json",
            "filters": ["request_id"],
        },
        "console_err": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "json",
            "filters": ["request_id"],
        },
    },
    "loggers": {
        "root": {
            "handlers": ["console_err"],
            "level": "WARNING",
        },
        "request.summary": {
            "handlers": ["console_out"],
            "level": "DEBUG",
            # pytest's caplog fixture requires propagate=True
            # outside of pytest, use propagate=False to avoid double logs
            "propagate": IN_PYTEST,
        },
        "events": {
            "handlers": ["console_err"],
            "level": "ERROR",
            "propagate": IN_PYTEST,
        },
        "eventsinfo": {
            "handlers": ["console_out"],
            "level": "INFO",
            "propagate": IN_PYTEST,
        },
        "abusemetrics": {
            "handlers": ["console_out"],
            "level": "INFO",
            "propagate": IN_PYTEST,
        },
        "studymetrics": {
            "handlers": ["console_out"],
            "level": "INFO",
            "propagate": IN_PYTEST,
        },
        "markus": {
            "handlers": ["console_out"],
            "level": "DEBUG",
            "propagate": IN_PYTEST,
        },
        GLEAN_EVENT_MOZLOG_TYPE: {
            "handlers": ["console_out"],
            "level": "DEBUG",
            "propagate": IN_PYTEST,
        },
        "dockerflow": {
            "handlers": ["console_err"],
            "level": "WARNING",
            "propagate": IN_PYTEST,
        },
    },
}

DRF_RENDERERS = ["rest_framework.renderers.JSONRenderer"]
if DEBUG and not IN_PYTEST:
    DRF_RENDERERS += [
        "rest_framework.renderers.BrowsableAPIRenderer",
    ]

FIRST_EMAIL_RATE_LIMIT = config("FIRST_EMAIL_RATE_LIMIT", "5/minute")
if IN_PYTEST or RELAY_CHANNEL in ["local", "dev"]:
    FIRST_EMAIL_RATE_LIMIT = "1000/minute"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "api.authentication.FxaTokenAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": DRF_RENDERERS,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "EXCEPTION_HANDLER": "api.views.relay_exception_handler",
}
if API_DOCS_ENABLED:
    REST_FRAMEWORK["DEFAULT_SCHEMA_CLASS"] = "drf_spectacular.openapi.AutoSchema"

SPECTACULAR_SETTINGS = {
    "SWAGGER_UI_DIST": "SIDECAR",
    "SWAGGER_UI_FAVICON_HREF": "SIDECAR",
    "REDOC_DIST": "SIDECAR",
    "TITLE": "Firefox Relay API",
    "DESCRIPTION": (
        "Keep your email safe from hackers and trackers. This API is built with"
        " Django REST Framework and powers the Relay website UI, add-on,"
        " Firefox browser, and 3rd-party app integrations."
    ),
    "VERSION": "1.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

if IN_PYTEST or RELAY_CHANNEL in ["local", "dev"]:
    _DEFAULT_PHONE_RATE_LIMIT = "1000/minute"
else:
    _DEFAULT_PHONE_RATE_LIMIT = "5/minute"
PHONE_RATE_LIMIT = config("PHONE_RATE_LIMIT", _DEFAULT_PHONE_RATE_LIMIT)

# Turn on logging out on GET in development.
# This allows `/mock/logout/` in the front-end to clear the
# session cookie. Without this, after switching accounts in dev mode,
# then logging out again, API requests continue succeeding even without
# an auth token:
ACCOUNT_LOGOUT_ON_GET = DEBUG

# TODO: introduce an environment variable to control CORS_ALLOWED_ORIGINS
# https://mozilla-hub.atlassian.net/browse/MPP-3468
CORS_URLS_REGEX = r"^/api/"
CORS_ALLOWED_ORIGINS = [
    "https://vault.bitwarden.com",
    "https://vault.bitwarden.eu",
]
if RELAY_CHANNEL in ["dev", "stage"]:
    CORS_ALLOWED_ORIGINS += [
        "https://vault.qa.bitwarden.pw",
        "https://vault.euqa.bitwarden.pw",
    ]
# Allow origins for each environment to help debug cors headers
if RELAY_CHANNEL == "local":
    # In local dev, next runs on localhost and makes requests to /accounts/
    CORS_ALLOWED_ORIGINS += [
        "http://localhost:3000",
        "http://0.0.0.0:3000",
        "http://127.0.0.1:8000",
    ]
    CORS_URLS_REGEX = r"^/(api|accounts)/"
if RELAY_CHANNEL == "dev":
    CORS_ALLOWED_ORIGINS += [
        "https://dev.fxprivaterelay.nonprod.cloudops.mozgcp.net",
    ]
if RELAY_CHANNEL == "stage":
    CORS_ALLOWED_ORIGINS += [
        "https://stage.fxprivaterelay.nonprod.cloudops.mozgcp.net",
    ]

CSRF_TRUSTED_ORIGINS = []
if RELAY_CHANNEL == "local":
    # In local development, the React UI can be served up from a different server
    # that needs to be allowed to make requests.
    # In production, the frontend is served by Django, is therefore on the same
    # origin and thus has access to the same cookies.
    CORS_ALLOW_CREDENTIALS = True
    SESSION_COOKIE_SAMESITE = None
    CSRF_TRUSTED_ORIGINS += [
        "http://localhost:3000",
        "http://0.0.0.0:3000",
    ]

SENTRY_RELEASE = config("SENTRY_RELEASE", "")
CIRCLE_SHA1 = config("CIRCLE_SHA1", "")
CIRCLE_TAG = config("CIRCLE_TAG", "")
CIRCLE_BRANCH = config("CIRCLE_BRANCH", "")

sentry_release: str | None = None
if SENTRY_RELEASE:
    sentry_release = SENTRY_RELEASE
elif CIRCLE_TAG and CIRCLE_TAG != "unknown":
    sentry_release = CIRCLE_TAG
elif (
    CIRCLE_SHA1
    and CIRCLE_SHA1 != "unknown"
    and CIRCLE_BRANCH
    and CIRCLE_BRANCH != "unknown"
):
    sentry_release = f"{CIRCLE_BRANCH}:{CIRCLE_SHA1}"

SENTRY_DEBUG = config("SENTRY_DEBUG", DEBUG, cast=bool)

SENTRY_ENVIRONMENT = config("SENTRY_ENVIRONMENT", RELAY_CHANNEL)
# Use "local" as default rather than "prod", to catch ngrok.io URLs
if SENTRY_ENVIRONMENT == "prod" and SITE_ORIGIN != "https://relay.firefox.com":
    SENTRY_ENVIRONMENT = "local"

sentry_sdk.init(
    dsn=config("SENTRY_DSN", None),
    integrations=[DjangoIntegration(cache_spans=not DEBUG)],
    debug=SENTRY_DEBUG,
    include_local_variables=DEBUG,
    release=sentry_release,
    environment=SENTRY_ENVIRONMENT,
)
# Duplicates events for unhandled exceptions, but without useful tracebacks
ignore_logger("request.summary")
# Security scanner attempts, no action required
# Can be re-enabled when hostname allow list implemented at the load balancer
ignore_logger("django.security.DisallowedHost")
# Fluent errors, mostly when a translation is unavailable for the locale.
# It is more effective to process these from logs using BigQuery than to track
# as events in Sentry.
ignore_logger("django_ftl.message_errors")
# Security scanner attempts on Heroku dev, no action required
if RELAY_CHANNEL == "dev":
    ignore_logger("django.security.SuspiciousFileOperation")


_MARKUS_BACKENDS: list[dict[str, Any]] = []
if DJANGO_STATSD_ENABLED:
    _MARKUS_BACKENDS.append(
        {
            "class": "markus.backends.datadog.DatadogMetrics",
            "options": {
                "statsd_host": STATSD_HOST,
                "statsd_port": STATSD_PORT,
                "statsd_prefix": STATSD_PREFIX,
            },
        }
    )
if STATSD_DEBUG:
    _MARKUS_BACKENDS.append(
        {
            "class": "markus.backends.logging.LoggingMetrics",
            "options": {
                "logger_name": "markus",
                "leader": "METRICS",
            },
        }
    )
markus.configure(backends=_MARKUS_BACKENDS)

if USE_SILK:
    SILKY_PYTHON_PROFILER = True
    SILKY_PYTHON_PROFILER_BINARY = True
    SILKY_PYTHON_PROFILER_RESULT_PATH = ".silk-profiler"

# Settings for manage.py process_emails_from_sqs
PROCESS_EMAIL_BATCH_SIZE = config(
    "PROCESS_EMAIL_BATCH_SIZE", 10, cast=Choices(range(1, 11), cast=int)
)
PROCESS_EMAIL_DELETE_FAILED_MESSAGES = config(
    "PROCESS_EMAIL_DELETE_FAILED_MESSAGES", False, cast=bool
)
PROCESS_EMAIL_HEALTHCHECK_PATH = config(
    "PROCESS_EMAIL_HEALTHCHECK_PATH", os.path.join(TMP_DIR, "healthcheck.json")
)
PROCESS_EMAIL_MAX_SECONDS = config("PROCESS_EMAIL_MAX_SECONDS", 0, cast=int) or None
PROCESS_EMAIL_VERBOSITY = config(
    "PROCESS_EMAIL_VERBOSITY", 1, cast=Choices(range(0, 4), cast=int)
)
PROCESS_EMAIL_VISIBILITY_SECONDS = config(
    "PROCESS_EMAIL_VISIBILITY_SECONDS", 120, cast=int
)
PROCESS_EMAIL_WAIT_SECONDS = config("PROCESS_EMAIL_WAIT_SECONDS", 5, cast=int)
PROCESS_EMAIL_HEALTHCHECK_MAX_AGE = config(
    "PROCESS_EMAIL_HEALTHCHECK_MAX_AGE", 120, cast=int
)

# Django 3.2 switches default to BigAutoField
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# python-dockerflow settings
DOCKERFLOW_VERSION_CALLBACK = "privaterelay.utils.get_version_info"
DOCKERFLOW_CHECKS = [
    "dockerflow.django.checks.check_database_connected",
    "dockerflow.django.checks.check_migrations_applied",
]
if REDIS_URL:
    DOCKERFLOW_CHECKS.append("dockerflow.django.checks.check_redis_connected")
DOCKERFLOW_REQUEST_ID_HEADER_NAME = config("DOCKERFLOW_REQUEST_ID_HEADER_NAME", None)
SILENCED_SYSTEM_CHECKS = sorted(
    set(config("DJANGO_SILENCED_SYSTEM_CHECKS", default="", cast=Csv()))
    | {
        # (models.W040) SQLite does not support indexes with non-key columns.
        # RelayAddress index idx_ra_created_by_addon uses this for PostgreSQL.
        "models.W040",
    }
)

# django-ftl settings
AUTO_RELOAD_BUNDLES = False  # Requires pyinotify

# Patching for django-types
django_stubs_ext.monkeypatch()
