# Registry

A singleton settings store for PySide6. Dot-notation access, reactive auto-rerun, built-in light/dark theme system, and change-only signal emission.

## Who is this for?

A **drag-and-drop solution** for developers who want settings, theming, translations, and reactive `QWidget` updates without designing a full architecture upfront.

Aimed at **fast prototyping of small to intermediate desktop applications** — when you need something on screen quickly, need it to be reactive, and don't want to wire signals by hand or restructure code every time requirements shift.

> **Not meant for large or production applications.** It trades raw performance for convenience. If you need a production-ready solution built on the same concept, one is currently in development → [reactive-registry](https://github.com/ISPMD/reactive-registry)

---

## Why "lazy"?

**No schema required.** Settings use dot-notation keys (`"audio.volume"`, `"ui.theme.mode"`) and the structure is created on the fly — no need to define categories or subcategories ahead of time.

**No manual signal wiring.** Decorate a method with `@registry.reactive` and it re-runs automatically whenever any value it reads changes — whether that's a setting, a theme token, or a language switch.

**Low coupling.** The package is self-contained and easy to drop into a project or pull out without touching a lot of surrounding code.

---

## Inspiration

Inspired by **QML**, where reactivity is built into the language itself — a feature that's notably absent from `QWidgets`. QML and SLINT are great tools, but they introduce a different workflow and design approach than `QWidgets`, which can be faster for some developers and slower for others. Registry is for developers who prefer staying in the `QWidgets` world.

I originally built this for myself — to have a portable solution when prototyping functionality for different projects and clients, especially when I don't know the app's structure upfront and need something I can insert or remove without rewriting a lot of code.

---

## Setup

Drop `Registry.py` next to your project and import the singleton:

```python
from Registry import settings
```

That's it. No instantiation needed — `settings` is ready to use.

---

## Reading and writing

Two equivalent styles. Use whichever fits the context.

### String paths — `get()` / `set()`

```python
settings.set("window.width", 800)
settings.set("window.height", 600)

w = settings.get("window.width")   # 800
```

### Dot notation

```python
settings.window.width  = 800
settings.window.height = 600

w = settings.window.width          # 800
```

Intermediate groups are created automatically on writes:

```python
settings.app.ui.panel.color = "#ffffff"   # creates app, ui, and panel
```

**Performance note:** `get()` is ~5× faster than dot notation for tight loops because it bypasses `__getattr__`. Use dot notation in event handlers and `@reactive` methods; use `get()` in hot paths.

---

## Missing keys

Reading a missing key returns a `_MissingNode` sentinel instead of raising immediately. This allows chained writes to new paths without pre-declaring groups:

```python
settings.a.b.c = 1   # a and b don't exist yet — created automatically
```

The sentinel is safe to compare against `None` as an existence check:

```python
if settings.app.color == None:          # True — does not raise
    settings.app.color = "#ffffff"

if settings.get("app.color") == None:   # same
    settings.set("app.color", "#ffffff")
```

Any other use raises `KeyError`:

```python
print(settings.app.missing)      # KeyError
bool(settings.app.missing)       # KeyError
settings.app.missing + 1         # KeyError
str(settings.get("app.missing")) # KeyError
```

Writing to a missing path always creates it — it is never an error:

```python
settings.set("brand.new.key", 42)   # ok
settings.app.new_key = 42           # ok
```

---

## Signals

`settings.setting_changed` is a `Signal(str, object)` that emits `(path, new_value)` on every change. Writing the same value twice does **not** emit.

```python
settings.setting_changed.connect(lambda path, value: print(path, "→", value))

settings.set("window.width", 800)   # emits  ("window.width", 800)
settings.set("window.width", 800)   # silent — value unchanged
settings.set("window.width", 900)   # emits  ("window.width", 900)
```

---

## Reactive widgets — with `@settings.reactive`

`@settings.reactive` wraps a function or method. On each call it records every settings key that was read, then re-runs automatically whenever any of those keys change. Dependencies are re-recorded on every run, so conditional reads are handled correctly.

### On an instance method

The standard pattern. Call the method once from `__init__` to render and register dependencies. Each instance tracks independently.

```python
class MyWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._refresh()             # renders + registers dependencies

    @settings.reactive
    def _refresh(self):
        self.setText(settings.app.message)
        self.setStyleSheet(f"font-size: {settings.app.font_size}px;")
```

### On a plain function / closure

Use this when you don't own the widget class.

```python
label = QLabel()

@settings.reactive
def _refresh():
    label.setText(settings.app.message)
    label.setStyleSheet(f"color: {settings.get('theme.fg')};")

_refresh()              # call once to register
label._keep = _refresh  # hold a reference — prevents garbage collection
```

### Composed — one `@reactive` method calling another

Split logic into methods with independent dependency sets. Each re-runs only when its own keys change.

```python
class MyWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._refresh()

    @settings.reactive
    def _style(self) -> str:
        # tracks only theme keys — re-runs on theme changes only
        return f"color: {settings.get('theme.fg')}; font-size: {settings.app.font_size}px;"

    @settings.reactive
    def _refresh(self):
        # tracks only content keys — re-runs on content changes only
        self.setText(settings.app.message)
        self.setStyleSheet(self._style())
```

---

## Reactive widgets — without decorator

### `setting_changed.connect` — all keys

Fires on every key change. Simple, but re-renders even for unrelated keys.

```python
class MyWidget(QLabel):
    def __init__(self):
        super().__init__()
        settings.setting_changed.connect(self._on_change)
        self._render()

    def _on_change(self, path, value):
        self._render()

    def _render(self):
        self.setText(settings.app.message)
```

### `setting_changed.connect` — filtered to one key

Check `path` before re-rendering to react only to specific keys.

```python
class MyWidget(QLabel):
    def __init__(self):
        super().__init__()
        settings.setting_changed.connect(self._on_change)
        self._render()

    def _on_change(self, path, value):
        if path == "app.message":
            self._render()

    def _render(self):
        self.setText(settings.app.message)
```

### `SettingBinding` helper

Maps one key to one callable. Fires once at init and again on every change to that key. Good for simple one-liner wiring.

```python
class SettingBinding:
    def __init__(self, path: str, apply):
        self._path  = path
        self._apply = apply
        settings.setting_changed.connect(self._on_change)
        apply(settings.get(path))       # initial apply

    def _on_change(self, path, value):
        if path == self._path:
            self._apply(value)

# usage — keep references so bindings are not garbage collected
label = QLabel()
_b1 = SettingBinding("app.message",   lambda v: label.setText(v))
_b2 = SettingBinding("app.font_size", lambda v: label.setFont(QFont("sans", v)))
```

### `QTimer` polling

Poll on a fixed interval, render only when the value actually changed. Useful when settings are updated from a non-Qt thread.

```python
class MyWidget(QLabel):
    def __init__(self):
        super().__init__()
        self._last  = object()          # sentinel — never equals any real value
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(300)          # ms

    def _poll(self):
        value = settings.app.font_size
        if value != self._last:
            self._last = value
            self.setFont(QFont("sans", value))
```

---

## Theme system

A built-in light/dark theme. Define both palettes once; read from the active one with a short path.

### Define palettes

```python
settings.set("theme.light.bg",     "#ffffff")
settings.set("theme.light.fg",     "#111111")
settings.set("theme.light.accent", "#0066cc")

settings.set("theme.dark.bg",      "#1e1e2e")
settings.set("theme.dark.fg",      "#cdd6f4")
settings.set("theme.dark.accent",  "#89b4fa")

settings.set("theme.mode", "light")    # "light" or "dark"
```

Both palettes must define the same keys. Reading a key missing from either side raises `KeyError`.

### Read from the active theme

```python
bg = settings.theme.bg          # returns light.bg or dark.bg based on theme.mode
bg = settings.get("theme.bg")   # same
```

### Switch mode

```python
settings.set("theme.mode", "dark")
# any @reactive function that read a theme key re-runs automatically
```

### Write rules

You must write to `theme.light.*` or `theme.dark.*` explicitly. Writing to a bare `theme.*` key raises `ValueError`.

```python
settings.theme.bg = "#ff0000"          # ValueError
settings.set("theme.bg", "#ff0000")    # ValueError

settings.theme.light.bg = "#ff0000"    # ok
settings.set("theme.dark.bg", "#000")  # ok
```

---

## Serialisation

```python
import json

# save — returns a plain nested dict, always JSON-serialisable
with open("settings.json", "w") as f:
    json.dump(settings.to_dict(), f, indent=2)

# load — creates missing keys, updates changed ones, leaves the rest untouched
# None values are written correctly
with open("settings.json") as f:
    settings.from_dict(json.load(f))
```

---

## Testing

`SettingsRegistry.reset()` destroys the singleton, disconnects all signals, and clears every cache including the thread-local tracking stack. Call it in `setUp` for a fully isolated registry per test.

```python
import unittest
from settings_registry import SettingsRegistry, settings

class MyTest(unittest.TestCase):
    def setUp(self):
        SettingsRegistry.reset()
        self.s = SettingsRegistry.instance()
        self.s.set("app.value", 42)
```

---

## Performance

| Access | 1 M reads |
|---|---|
| `settings.window.width` dot, warm cache | ~750 ms |
| `settings.get("window.width")` | ~200 ms |

Path strings are split once and cached. Leaf values are cached after the first read and served directly from a dict on subsequent reads. Cache invalidation on writes is O(k) where k is the number of cached descendants of the written key.

---

## Quick reference

| Task | Dot notation | String path |
|---|---|---|
| Read | `settings.window.width` | `settings.get("window.width")` |
| Write | `settings.window.width = 800` | `settings.set("window.width", 800)` |
| Exists check | `settings.window.width == None` | `settings.get("window.width") == None` |
| Theme read | `settings.theme.bg` | `settings.get("theme.bg")` |
| Theme write | `settings.theme.light.bg = "#fff"` | `settings.set("theme.light.bg", "#fff")` |
| Snapshot | — | `settings.to_dict()` |
| Restore | — | `settings.from_dict(d)` |
| Reset (tests) | — | `SettingsRegistry.reset()` |

### Disclaimer -- docs and comments autogenerated using LLM's - the intended use for machine learning =))
