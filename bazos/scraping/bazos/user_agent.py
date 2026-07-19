"""Reproduce the Bazos Android app's User-Agent exactly.

The official app (``cz.ackee.bazos``) does NOT send a hand-written UA string. It
builds one at runtime in a network interceptor and normalises it. Reverse-engineered
from the decompiled app (v2.19.1, versionCode 4630):

* Base string (``i4(yk.a, zk.b)`` ctor,
  ``com/google/android/gms/internal/measurement/i4.java:264``)::

      String.format(Locale.US,
          "%s/%s (%s; build:%d; Android %s; Model:%s)",
          appLabel, versionName, packageName, versionCode,
          Build.VERSION.RELEASE, Build.MODEL)

* Because the interceptor is a *network* interceptor (registered via
  ``OkHttpClient.Builder`` second list == networkInterceptors, see ``zn/g0.java:91``),
  it runs after OkHttp's ``BridgeInterceptor``, so OkHttp's own default UA
  (``okhttp/4.11.0``) is already on the request and gets appended with a leading
  space (``OkHttpClientFactory.createNormalizedUserAgent``).

* The combined string is then, in order
  (``OkHttpClientFactory.createNormalizedUserAgent`` + ``l0/r.java:225`` ``j()``):
    1. NFD-normalised and stripped of combining diacritical marks,
    2. lower-cased,
    3. NFD-normalised + stripped again,
    4. trimmed.

  So ``Bazoš`` -> ``bazos`` and the whole UA ends up lowercase ASCII. Final shape::

      bazos/2.19.1 (cz.ackee.bazos; build:4630; android 13; model:pixel 7) okhttp/4.11.0

Keep the pinned constants below in sync with the APK you are mimicking; if Bazos
ships a new app version, bump ``APP_VERSION_NAME`` / ``APP_VERSION_CODE`` /
``OKHTTP_VERSION`` from the new manifest + bundled okhttp.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# --- Pinned to the decompiled APK (bump when the app updates) ---------------
APP_LABEL = "Bazoš"          # res/values-cs/strings.xml -> app_name (normalises to "bazos")
APP_PACKAGE = "cz.ackee.bazos"
APP_VERSION_NAME = "2.19.1"  # AndroidManifest versionName
APP_VERSION_CODE = 4630      # AndroidManifest versionCode
OKHTTP_VERSION = "4.11.0"    # bundled okhttp (default UA suffix)

_COMBINING_MARKS = re.compile(r"[̀-ͯ]")


@dataclass(frozen=True)
class DeviceProfile:
    """The two device-specific values the app reads from ``android.os.Build``."""

    model: str            # Build.MODEL, e.g. "Pixel 7", "SM-G991B"
    android_release: str  # Build.VERSION.RELEASE, e.g. "13", "14"


# A small set of real, common Android devices. Any single one is a legitimate,
# indistinguishable-from-a-real-install fingerprint. Rotate across them per Tor
# identity if you want the fleet to look like many installs (see build_user_agent).
DEVICE_PROFILES: tuple[DeviceProfile, ...] = (
    DeviceProfile("Pixel 7", "14"),
    DeviceProfile("SM-G991B", "13"),        # Galaxy S21
    DeviceProfile("SM-A528B", "13"),        # Galaxy A52s 5G
    DeviceProfile("2201117TY", "13"),       # Redmi Note 11
    DeviceProfile("Pixel 6a", "14"),
)


def _normalize(s: str) -> str:
    """Replicate the app's normalisation: strip diacritics, lower-case, strip again, trim."""
    def strip_marks(x: str) -> str:
        return _COMBINING_MARKS.sub("", unicodedata.normalize("NFD", x))

    return strip_marks(strip_marks(s).lower()).strip()


def build_user_agent(device: DeviceProfile) -> str:
    """Return the exact UA string the app would emit on ``device``."""
    base = (
        f"{APP_LABEL}/{APP_VERSION_NAME} "
        f"({APP_PACKAGE}; build:{APP_VERSION_CODE}; "
        f"Android {device.android_release}; Model:{device.model})"
    )
    combined = f"{base} okhttp/{OKHTTP_VERSION}"
    return _normalize(combined)


def default_user_agent() -> str:
    """Stable UA for a single-install-style scraper (first profile)."""
    return build_user_agent(DEVICE_PROFILES[0])


if __name__ == "__main__":  # quick manual check
    for p in DEVICE_PROFILES:
        print(build_user_agent(p))
