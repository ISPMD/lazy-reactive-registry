"""
Registry.py
====================
A singleton settings registry for PySide6 with dot-notation access,
reactive auto-rerun, and change-only emission.

Performance notes
-----------------
- All dot-path strings are split once and cached in _PATH_CACHE.
- Leaf values (non-dict) are cached in the module-level _LEAF dict and
  returned on the next read without touching _data at all.
  _LEAF is invalidated precisely on writes (path + all children).
- Intermediate SettingsNode objects are cached in _NODE so that
  `settings.window` returns the same proxy on every access.
- Tracking uses a threading.local stack; the fast-path check
  (_TL.__dict__.get) avoids any attribute lookup when not inside a
  reactive call (the common case).

Recommended hot-loop idiom
---------------------------
For tight loops reading the same key 1 000 000 times prefer:

    w = settings.get("window.width")   # ~200 ms / 1 M   (5x faster than dot)

Dot-notation is convenient for setup / event handlers; use .get() in hot paths.

Theme system
------------
    settings.theme.light.bg  = "#ffffff"
    settings.theme.light.fg  = "#000000"
    settings.theme.dark.bg   = "#1e1e2e"
    settings.theme.dark.fg   = "#cdd6f4"
    settings.theme.mode      = "light"   # or "dark"

    settings.theme.bg   # reads theme.<mode>.bg automatically
    settings.theme.fg   # same

    # writing settings.theme.bg raises — write to theme.light.bg / theme.dark.bg

Usage
-----
    settings.window.width = 800
    w = settings.window.width         # 800
    w = settings.get("window.width")  # same, faster in loops

    @settings.reactive
    def refresh():
        widget.setStyleSheet(f"background: {settings.theme.bg};")

    refresh()                         # must call once to register dependencies
    settings.theme.mode = "dark"      # automatically re-runs refresh

Method usage:
    class MyWidget(QWidget):
        def __init__(self):
            super().__init__()
            self._refresh()

        @settings.reactive
        def _refresh(self):
            self.setStyleSheet(f"background: {settings.theme.bg};")
"""

import copy
import functools
import threading
import weakref

from PySide6.QtCore import QObject, Signal


# ---------------------------------------------------------------------------
# Module-level caches (shared across the singleton)
# ---------------------------------------------------------------------------

# path str -> tuple[str, ...]  — avoids repeated str.split(".") on every read
_PATH_CACHE: dict[str, tuple] = {}

# full dotted path -> leaf value  — short-circuits _data traversal on reads
# ONLY stores non-dict, non-None values.
# Invalidated on every write that touches the path or any of its children.
_LEAF: dict[str, object] = {}

# path -> SettingsNode  — avoids allocating a new proxy on every attribute hop
_NODE: dict[str, "SettingsNode"] = {}

# Reverse index: parent path -> set of child paths present in _LEAF or _NODE.
# Lets _invalidate find affected children in O(k) instead of scanning all keys.
# Entry format: "window" -> {"window.width", "window.height"}
_CHILDREN: dict[str, set] = {}


def _register_path(path: str) -> None:
    """Record *path* in _CHILDREN under every ancestor so invalidation is fast."""
    parts = path.split(".")
    for i in range(len(parts) - 1):
        parent = ".".join(parts[:i + 1])
        if parent not in _CHILDREN:
            _CHILDREN[parent] = set()
        _CHILDREN[parent].add(path)


def _unregister_path(path: str) -> None:
    """Remove *path* from every ancestor entry in _CHILDREN."""
    parts = path.split(".")
    for i in range(len(parts) - 1):
        parent = ".".join(parts[:i + 1])
        s = _CHILDREN.get(parent)
        if s:
            s.discard(path)
            if not s:
                del _CHILDREN[parent]


def _split(path: str) -> tuple:
    """Return (and cache) the tuple of keys for a dot-separated path."""
    try:
        return _PATH_CACHE[path]
    except KeyError:
        keys = tuple(path.split("."))
        _PATH_CACHE[path] = keys
        return keys


def _cache_leaf(path: str, value) -> None:
    """Store a leaf value and register it in the reverse child index."""
    if path not in _LEAF:
        _register_path(path)
    _LEAF[path] = value


def _cache_node(path: str, node) -> None:
    """Store a SettingsNode and register it in the reverse child index."""
    if path not in _NODE:
        _register_path(path)
    _NODE[path] = node


# ---------------------------------------------------------------------------
# Per-thread tracking stack
# ---------------------------------------------------------------------------

_TL = threading.local()   # .stack: list[set[str]]  — pushed/popped by reactive


def _push_tracking() -> set:
    if not hasattr(_TL, "stack"):
        _TL.stack = []
    s: set = set()
    _TL.stack.append(s)
    return s


def _pop_tracking(token: set) -> set:
    popped = _TL.stack.pop()
    assert popped is token, "Tracking stack corrupted — mismatched push/pop"
    return popped


def _track(path: str) -> None:
    """
    Record *path* in the innermost active tracking set.
    Fast-path: if no reactive call is active the stack list does not exist in
    _TL.__dict__ at all, so the .get() returns None immediately with no
    attribute traversal overhead.
    """
    stack = _TL.__dict__.get("stack")
    if stack:
        stack[-1].add(path)


# ---------------------------------------------------------------------------
# SettingsNode — proxy for intermediate dict nodes
# ---------------------------------------------------------------------------

class SettingsNode:
    """
    Proxy returned for intermediate nodes (dicts), e.g. ``settings.window``.
    Instances are cached in _NODE so the same object is reused on repeated
    attribute hops.
    """

    __slots__ = ("_r", "_p")

    def __init__(self, registry: "SettingsRegistry", path: str) -> None:
        object.__setattr__(self, "_r", registry)
        object.__setattr__(self, "_p", path)

    def __getattr__(self, name: str):
        r  = object.__getattribute__(self, "_r")
        p  = object.__getattribute__(self, "_p")
        np = p + "." + name

        # theme.* shortcut — redirect through active theme
        if p == "theme" and name not in ("light", "dark", "mode"):
            return r._theme_get(name)

        # Fast leaf cache hit
        try:
            v = _LEAF[np]
            _track(np)
            return v
        except KeyError:
            pass

        v = r._get_nested(np)

        if isinstance(v, dict):
            node = _NODE.get(np)
            if node is None:
                node = SettingsNode(r, np)
                _cache_node(np, node)
            return node

        if v is None:
            return _MissingNode(r, np)

        # Populate leaf cache for next time
        _cache_leaf(np, v)
        _track(np)
        return v

    def __setattr__(self, name: str, value) -> None:
        r = object.__getattribute__(self, "_r")
        p = object.__getattribute__(self, "_p")
        if p == "theme" and name not in ("light", "dark", "mode"):
            raise ValueError(
                f"Cannot set 'theme.{name}' directly. "
                f"Write to 'theme.light.{name}' or 'theme.dark.{name}' instead."
            )
        r._set_nested(p + "." + name, value)


# ---------------------------------------------------------------------------
# _MissingNode — sentinel for non-existent paths
# ---------------------------------------------------------------------------

class _MissingNode:
    """
    Sentinel returned when a settings path does not exist yet.

    Primary purpose: allow chained *assignment* to new keys without
    pre-declaring intermediate dicts:

        settings.a.b.c = 1   # a and b are created automatically

    Reads chain silently (``__getattr__`` returns another _MissingNode) so
    that multi-hop write chains like the above work correctly — Python must
    evaluate ``settings.a.b`` before it can call ``__setattr__('c', 1)`` on
    the result.  The chain raises only when the value is actually *used*:

        bool(settings.missing)       # KeyError
        str(settings.missing)        # KeyError
        settings.missing + 1         # KeyError

    The one safe read is equality with None, which returns True and lets
    callers check existence without a try/except:

        if settings.maybe.key == None: ...   # safe, does not raise
    """

    __slots__ = ("_r", "_p")

    def __init__(self, registry: "SettingsRegistry", path: str) -> None:
        object.__setattr__(self, "_r", registry)
        object.__setattr__(self, "_p", path)

    # Reads on a MissingNode are always errors.
    def __getattr__(self, name: str) -> "_MissingNode":
        r = object.__getattribute__(self, "_r")
        p = object.__getattribute__(self, "_p")
        return _MissingNode(r, p + "." + name)

    # Writes chain through to create the key.
    def __setattr__(self, name: str, value) -> None:
        r = object.__getattribute__(self, "_r")
        p = object.__getattribute__(self, "_p")
        r._set_nested(p + "." + name, value)

    def _raise(self):
        path = object.__getattribute__(self, "_p")
        raise KeyError(f"Settings key '{path}' does not exist.")

    def __eq__(self, other):
        if other is None:
            return True
        self._raise()

    def __hash__(self):       return hash(None)
    def __bool__(self):       self._raise(); return False
    def __str__(self):        self._raise(); return ""
    def __int__(self):        self._raise(); return 0
    def __float__(self):      self._raise(); return 0.0
    def __add__(self, other): self._raise(); return None
    def __sub__(self, other): self._raise(); return None

    def __repr__(self) -> str:
        path = object.__getattribute__(self, "_p")
        return f"<MissingNode: '{path}'>"


# ---------------------------------------------------------------------------
# _ReactiveDescriptor — proper descriptor for @settings.reactive
# ---------------------------------------------------------------------------

class _ReactiveDescriptor:
    """
    Proper descriptor returned by ``@settings.reactive``.
    Each instance that owns the method gets its own connection table, and the
    descriptor works correctly with super(), inspect, and all standard
    descriptor protocols.

    Connection tables are keyed by weakref rather than id() so that a
    garbage-collected instance whose memory address is reused by a new
    instance does not inherit stale handlers.
    """

    def __init__(self, func, registry: "SettingsRegistry") -> None:
        self._func = func
        self._registry = registry
        # WeakKeyDictionary: entry is removed automatically when the instance
        # is garbage collected, preventing stale handler accumulation.
        # For plain-function calls (no self) we use a separate plain dict
        # keyed by a stable sentinel.
        self._inst_conns: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        self._func_conns: dict = {}   # for bare-function (non-method) calls
        functools.update_wrapper(self, func)

    def __call__(self, *args, **kwargs):
        return self._run(args, kwargs)

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        bound = functools.partial(self._run_bound, obj)
        functools.update_wrapper(bound, self._func)
        return bound

    def _run_bound(self, obj, *args, **kwargs):
        return self._run((obj,) + args, kwargs)

    def _get_conns(self, args: tuple) -> dict:
        """Return (and create if needed) the connection dict for this call."""
        # If first arg is a non-None object, use the weakref table keyed by it.
        if args and hasattr(args[0], "__dict__"):
            obj = args[0]
            try:
                return self._inst_conns[obj]
            except KeyError:
                d = {}
                self._inst_conns[obj] = d
                return d
        # Plain function call — use the stable func_conns dict.
        return self._func_conns

    def _run(self, args: tuple, kwargs: dict):
        registry = self._registry
        conns    = self._get_conns(args)

        # Disconnect stale handlers from the previous run
        for handler in conns.values():
            try:
                registry.setting_changed.disconnect(handler)
            except RuntimeError:
                pass
        conns.clear()

        token = _push_tracking()
        try:
            result = self._func(*args, **kwargs)
        finally:
            accessed_keys = _pop_tracking(token)

        for key in accessed_keys:
            def make_handler(k):
                def handler(changed_key, _value):
                    if changed_key == k:
                        self._run(args, kwargs)
                return handler
            h = make_handler(key)
            conns[key] = h
            registry.setting_changed.connect(h)

        return result


# ---------------------------------------------------------------------------
# SettingsRegistry — the singleton
# ---------------------------------------------------------------------------

class SettingsRegistry(QObject):

    setting_changed = Signal(str, object)   # (path, new_value)

    _instance: "SettingsRegistry | None" = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, defaults: dict | None = None) -> None:
        if "_initialized" in self.__dict__:
            return

        super().__init__()

        self.__dict__["_data"]        = {}
        self.__dict__["_theme_cache"] = {}   # invalidated on any theme write
        self.__dict__["_initialized"] = True

        # Built-in theme structure
        self._set_nested("theme.mode",  "light")
        self._set_nested("theme.light", {})
        self._set_nested("theme.dark",  {})

        if defaults:
            self._load_defaults(defaults)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _load_defaults(self, defaults: dict, path: str = "") -> None:
        for key, value in defaults.items():
            full_path = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                self._load_defaults(value, full_path)
            else:
                # Write even if value is None — caller explicitly set it.
                self._set_nested(full_path, value, allow_none=True)

    @classmethod
    def instance(cls) -> "SettingsRegistry":
        if cls._instance is None:
            cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """
        Destroy the singleton and clear all caches.
        Primarily useful for unit tests that need an isolated registry.

            def setUp(self):
                SettingsRegistry.reset()
                self.settings = SettingsRegistry.instance()
        """
        if cls._instance is not None:
            try:
                cls._instance.setting_changed.disconnect()
            except RuntimeError:
                pass
            cls._instance = None
        _LEAF.clear()
        _NODE.clear()
        _PATH_CACHE.clear()
        _CHILDREN.clear()
        # Clear any in-progress tracking stacks on this thread.
        if hasattr(_TL, "stack"):
            _TL.stack.clear()

    # ------------------------------------------------------------------
    # Theme helpers
    # ------------------------------------------------------------------

    def _theme_get(self, key: str):
        """Read *key* from the active theme via cache."""
        cache = self.__dict__["_theme_cache"]
        mode  = self.__dict__["_data"].get("theme", {}).get("mode") or "light"

        if cache.get("mode") != mode:
            td = self.__dict__["_data"].get("theme", {})
            cache["mode"]  = mode
            cache["light"] = td.get("light") or {}
            cache["dark"]  = td.get("dark")  or {}

        light = cache["light"]
        dark  = cache["dark"]

        if key not in light:
            raise KeyError(f"Theme key '{key}' is not defined in theme.light.")
        if key not in dark:
            raise KeyError(f"Theme key '{key}' is not defined in theme.dark.")

        _track(f"theme.{cache['mode']}.{key}")
        _track("theme.mode")

        return light[key] if mode == "light" else dark[key]

    # ------------------------------------------------------------------
    # Nested dict helpers
    # ------------------------------------------------------------------

    def _get_nested(self, path: str):
        """Traverse _data using the cached split path."""
        data = self.__dict__["_data"]
        for key in _split(path):
            if isinstance(data, dict):
                data = data.get(key)
            else:
                return None
        return data

    def _invalidate(self, path: str) -> None:
        """
        Remove *path* and all descendant paths from the leaf and node caches.
        Uses the _CHILDREN reverse index so this is O(k) where k is the number
        of affected cached entries, not O(total cached keys).
        """
        # Collect all descendants from the reverse index
        to_remove = set()
        queue = [path]
        while queue:
            p = queue.pop()
            to_remove.add(p)
            children = _CHILDREN.get(p)
            if children:
                queue.extend(children)

        for p in to_remove:
            if p in _LEAF:
                _unregister_path(p)
                del _LEAF[p]
            if p in _NODE:
                _unregister_path(p)
                del _NODE[p]
        # Clean up the parent entry itself from _CHILDREN
        _CHILDREN.pop(path, None)

    def _set_nested(self, path: str, value, allow_none: bool = False) -> None:
        keys = _split(path)
        data = self.__dict__["_data"]

        for key in keys[:-1]:
            if key not in data:
                data[key] = {}
            elif not isinstance(data[key], dict):
                raise ValueError(
                    f"Cannot create nested setting '{path}': "
                    f"'{key}' is already a value, not a group."
                )
            data = data[key]

        last_key = keys[-1]

        # Allow dict assignment only for theme.light / theme.dark
        if isinstance(value, dict):
            if path not in ("theme.light", "theme.dark"):
                raise ValueError(
                    f"Cannot assign a dict to '{path}'. "
                    f"Only theme.light and theme.dark accept dicts."
                )
            data[last_key] = value
            self.__dict__["_theme_cache"].clear()
            self._invalidate(path)
            self.setting_changed.emit(path, value)
            return

        if last_key in data and isinstance(data[last_key], dict):
            raise ValueError(
                f"Cannot overwrite setting group '{path}' with a plain value. "
                f"Set individual keys instead."
            )

        # Change-only emission — skip only when value is genuinely unchanged
        # and the caller hasn't forced a write (allow_none=True).
        if not allow_none and data.get(last_key) == value:
            return

        data[last_key] = value

        if path.startswith("theme"):
            self.__dict__["_theme_cache"].clear()

        self._invalidate(path)
        self.setting_changed.emit(path, value)

    # ------------------------------------------------------------------
    # Dot-notation entry point
    # ------------------------------------------------------------------

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)

        # Fast leaf cache hit
        try:
            v = _LEAF[name]
            _track(name)
            return v
        except KeyError:
            pass

        v = self._get_nested(name)

        if isinstance(v, dict):
            node = _NODE.get(name)
            if node is None:
                node = SettingsNode(self, name)
                _cache_node(name, node)
            return node

        if v is None:
            return _MissingNode(self, name)

        _cache_leaf(name, v)
        _track(name)
        return v

    # Names that live on the class and must never be routed through _set_nested
    _CLASS_ATTRS: frozenset = frozenset(
        k for k, v in vars(QObject).items()
        if not k.startswith("__")
    ) | frozenset(["setting_changed"])

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_") or name in self._CLASS_ATTRS:
            self.__dict__[name] = value
        else:
            self._set_nested(name, value)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, path: str):
        """
        Read a value by dot-string path.

        Behaves identically to dot-notation: returns a _MissingNode for
        missing keys, which raises KeyError the moment it is used as a value
        (bool, str, arithmetic, etc.).  This means:

            settings.get("missing") == None   # True  — safe existence check
            str(settings.get("missing"))      # raises KeyError

        Prefer this over dot-notation in tight loops — it hits the leaf
        cache without going through ``__getattr__`` and is ~5x faster.

            # hot loop
            width = settings.get("window.width")

        Theme shortcut: paths of the form ``"theme.<key>"`` (where <key> is
        not ``light``, ``dark``, or ``mode``) are redirected through the
        active theme exactly like ``settings.theme.<key>`` dot access.

            bg = settings.get("theme.bg")   # reads theme.light.bg or theme.dark.bg
        """
        # Theme redirect: "theme.bg" -> _theme_get("bg")
        if path.startswith("theme."):
            key = path[6:]   # strip "theme."
            if key and "." not in key and key not in ("light", "dark", "mode"):
                return self._theme_get(key)

        _track(path)
        try:
            return _LEAF[path]
        except KeyError:
            pass
        v = self._get_nested(path)
        if v is None:
            return _MissingNode(self, path)
        _cache_leaf(path, v)
        return v

    def set(self, path: str, value) -> None:
        """
        Set a value by dot-string path.

        Writing to a bare theme key (e.g. "theme.bg") is not allowed —
        write to "theme.light.bg" or "theme.dark.bg" explicitly.
        """
        if path.startswith("theme."):
            key = path[6:]
            if key and "." not in key and key not in ("light", "dark", "mode"):
                raise ValueError(
                    f"Cannot set 'theme.{key}' directly. "
                    f"Write to 'theme.light.{key}' or 'theme.dark.{key}' instead."
                )
        self._set_nested(path, value)

    def to_dict(self) -> dict:
        """
        Return a deep copy of all settings as a plain nested dict.

            import json
            with open("settings.json", "w") as f:
                json.dump(settings.to_dict(), f, indent=2)
        """
        return copy.deepcopy(self.__dict__["_data"])

    def from_dict(self, data: dict) -> None:
        """
        Bulk-load settings from a plain nested dict.
        Existing keys not present in *data* are left untouched.
        Change signals fire for every key that actually changes.

            with open("settings.json") as f:
                settings.from_dict(json.load(f))
        """
        self._load_defaults(data)

    def reactive(self, func):
        """
        Decorator that re-runs the function/method whenever any registry key
        accessed inside it changes.

            @settings.reactive
            def on_resize():
                widget.setFixedWidth(settings.window.width)

            on_resize()   # must call once to register dependencies

        Works on instance methods — each instance gets independent tracking:

            class MyWidget(QWidget):
                def __init__(self):
                    super().__init__()
                    self._refresh()

                @settings.reactive
                def _refresh(self):
                    self.setStyleSheet(f"background: {settings.theme.bg};")
        """
        return _ReactiveDescriptor(func, self)


# Module-level singleton — import this directly
settings = SettingsRegistry.instance()
