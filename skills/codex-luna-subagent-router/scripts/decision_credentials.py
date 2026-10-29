"""Optional OS-protected Decision provider credentials; no plaintext files.

Native macOS Keychain and Windows Credential Manager calls keep secrets out of
command-line arguments, JSON configuration, Router ledgers and process env.
An explicit environment-variable mode remains available for headless hosts.
"""
from __future__ import annotations

import ctypes
import hashlib
import os
import re
import sys
from ctypes import wintypes

SERVICE = "ai.openai.codex-luna-subagent-router.decisions"
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
PROVIDERS = frozenset(("openai_decisions", "jev", "jev_ask", "http"))
MAX_SECRET_BYTES = 2048


class CredentialError(ValueError):
    pass


def supported():
    return sys.platform in ("darwin", "win32")


def account(provider: str, scope: str) -> str:
    if provider not in PROVIDERS or not isinstance(scope, str) or not scope:
        raise CredentialError("invalid credential provider or scope")
    # Project paths are never stored as cleartext keychain account metadata.
    fingerprint = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]
    return provider + ":" + fingerprint


def _secret(value: str) -> bytes:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise CredentialError("invalid credential")
    raw = value.encode("utf-8")
    if len(raw) > MAX_SECRET_BYTES:
        raise CredentialError("credential exceeds vault limit")
    return raw


def _mac_library():
    from ctypes.util import find_library
    return ctypes.CDLL(find_library("Security") or
                       "/System/Library/Frameworks/Security.framework/Security")


def _mac_find(lib, acct):
    service = SERVICE.encode("ascii")
    name = acct.encode("ascii")
    size = ctypes.c_uint32()
    data = ctypes.c_void_p()
    item = ctypes.c_void_p()
    fn = lib.SecKeychainFindGenericPassword
    fn.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
        ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
    ]
    fn.restype = ctypes.c_int32
    status = fn(None, len(service), service, len(name), name,
                ctypes.byref(size), ctypes.byref(data), ctypes.byref(item))
    return status, size, data, item


def _mac_release_find_result(lib, status, data, item):
    """Release the Security-framework data buffer and item in their own ABIs.

    SecKeychainItemFreeContent(attrList, data): attrList must be NULL here.
    SecKeychainFindGenericPassword's itemRef is released separately via CFRelease.
    """
    try:
        if status == 0 and data.value:
            free = lib.SecKeychainItemFreeContent
            free.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            free.restype = ctypes.c_int32
            if free(None, data) != 0:
                raise CredentialError("macOS Keychain buffer cleanup failed")
    finally:
        if item.value:
            cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            cf.CFRelease.argtypes = [ctypes.c_void_p]
            cf.CFRelease.restype = None
            cf.CFRelease(item)


def _mac_save(acct, secret):
    lib = _mac_library()
    status, size, data, item = _mac_find(lib, acct)
    try:
        if status == 0:
            modify = lib.SecKeychainItemModifyContent
            modify.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_uint32, ctypes.c_void_p]
            modify.restype = ctypes.c_int32
            buffer = ctypes.create_string_buffer(secret)
            result = modify(item, None, len(secret), buffer)
        elif status == -25300:  # errSecItemNotFound
            add = lib.SecKeychainAddGenericPassword
            add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                            ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
                            ctypes.c_void_p, ctypes.c_void_p]
            add.restype = ctypes.c_int32
            service = SERVICE.encode("ascii")
            name = acct.encode("ascii")
            buffer = ctypes.create_string_buffer(secret)
            result = add(None, len(service), service, len(name), name,
                         len(secret), buffer, None)
        else:
            raise CredentialError("macOS Keychain lookup was denied or unavailable")
        if result != 0:
            raise CredentialError("macOS Keychain save was denied or unavailable")
    finally:
        _mac_release_find_result(lib, status, data, item)


def _mac_load(acct):
    lib = _mac_library()
    status, size, data, item = _mac_find(lib, acct)
    try:
        if status != 0:
            return None
        if not data.value or size.value == 0 or size.value > MAX_SECRET_BYTES:
            return None
        return ctypes.string_at(data, size.value).decode("utf-8")
    finally:
        _mac_release_find_result(lib, status, data, item)


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR),
    ]


def _win_save(acct, secret):
    library = ctypes.WinDLL("Advapi32", use_last_error=True)
    target = SERVICE + "/" + acct
    buf = ctypes.create_string_buffer(secret)
    value = _CREDENTIALW()
    value.Type = 1                  # CRED_TYPE_GENERIC
    value.TargetName = target
    value.UserName = "Agent Router"
    value.CredentialBlobSize = len(secret)
    value.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    value.Persist = 2               # CRED_PERSIST_LOCAL_MACHINE, user-protected
    fn = library.CredWriteW
    fn.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(value), 0):
        raise CredentialError("Windows Credential Manager save was denied or unavailable")


def _win_load(acct):
    library = ctypes.WinDLL("Advapi32", use_last_error=True)
    target = SERVICE + "/" + acct
    result = ctypes.POINTER(_CREDENTIALW)()
    read = library.CredReadW
    read.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                     ctypes.POINTER(ctypes.POINTER(_CREDENTIALW))]
    read.restype = wintypes.BOOL
    if not read(target, 1, 0, ctypes.byref(result)):
        return None
    try:
        size = result.contents.CredentialBlobSize
        if not size or size > MAX_SECRET_BYTES:
            return None
        return ctypes.string_at(result.contents.CredentialBlob, size).decode("utf-8")
    finally:
        free = library.CredFree
        free.argtypes = [ctypes.c_void_p]
        free(ctypes.cast(result, ctypes.c_void_p))


def save(provider, scope, password):
    acct = account(provider, scope)
    secret = _secret(password)
    if sys.platform == "darwin":
        _mac_save(acct, secret)
    elif sys.platform == "win32":
        _win_save(acct, secret)
    else:
        raise CredentialError("no supported OS credential vault; use environment mode")


def read(provider, scope):
    acct = account(provider, scope)
    try:
        if sys.platform == "darwin":
            return _mac_load(acct)
        if sys.platform == "win32":
            return _win_load(acct)
    except (OSError, UnicodeError, ValueError, AttributeError):
        return None
    return None


def resolve(config, provider):
    source = config.get("credential_source", "env")
    if source == "none":
        return None
    if source == "keychain":
        scope = config.get("credential_scope")
        if not isinstance(scope, str) or not scope:
            return None
        return read(provider, scope)
    if source == "env":
        name = config.get("api_key_env")
        if name is None:
            name = "OPENAI_API_KEY" if provider == "openai_decisions" else (
                "TYPESAFE_API_KEY" if provider == "jev" else None
            )
        if name is not None and isinstance(name, str) and ENV_NAME.fullmatch(name):
            return os.environ.get(name) or None
        return None
    raise CredentialError("unsupported credential source")
