<p align="center">
  <img src="assets/logo/logo.png" alt="toml-translator logo" width="128">
</p>

Command-line utility for converting `pyproject.toml`
between **Poetry** and **uv** formats.  

The project helps to:
- migrate from Poetry to uv and back,
- preserve dependencies, groups, extras, and project metadata,
- work strictly within PEP standards without being locked to a single tool.

---

## Features

- 🔁 **Poetry → uv**
  - `[tool.poetry]` → `[project]`
  - `dependencies` → `project.dependencies` (PEP 508)
  - `group.*.dependencies` → `dependency-groups`
  - `extras` → `project.optional-dependencies`
  - `python` → `requires-python`

- 🔁 **uv → Poetry**
  - `[project]` → `[tool.poetry]`
  - `dependency-groups` → `tool.poetry.group.*`
  - `optional-dependencies` → `tool.poetry.extras`
  - PEP 508 strings → Poetry-compatible format

- 📦 Supports:
  - caret (`^`) and tilde (`~`) version constraints
  - markers (`python_version`, `platform_system`, etc.)
  - `git`, `url`, and `path` dependencies
  - dependency groups (`dev`, `test`, etc.)

> ⚠️ Translation is **best-effort**: Poetry and uv use different models, so perfect 1-to-1 mapping is not always possible.

---

## Requirements

- Python **3.11+**
- **No external dependencies** (standard library only)

---

## Installation

Clone the repository:

```bash
git clone https://github.com/fomenko-ai/toml-translator.git
cd toml-translator
````

(Optional) install in editable mode:

```bash
pip install -e .

```

---

## Usage

### Poetry → uv

```bash
toml-translator poetry2uv pyproject.toml > out.uv.toml
```

### uv → Poetry

```bash
toml-translator uv2poetry pyproject.toml > out.poetry.toml
```

Or run directly with Python:

```bash
python translator.py poetry2uv pyproject.toml
python translator.py uv2poetry pyproject.toml
```

---

## Examples

### Poetry

```toml
[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.31"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
```

### uv (result)

```toml
[project]
dependencies = [
  "requests>=2.31,<3.0.0"
]
requires-python = ">=3.11.0,<4.0.0"

[dependency-groups.dev]
pytest = ">=8.0,<9.0"
```

---

## Testing

Unit tests are written using `unittest`.

Run all tests:

```bash
python -m unittest -v
```

---

## Limitations

* Complex version constraints and custom sources may be simplified
* Some Poetry-specific fields have no direct equivalent in PEP 621
* TOML serialization is minimalistic (formatting is not preserved)

---

## Author

**Aleksei Fomenko**
📧 [fomenko_ai@proton.me](mailto:fomenko_ai@proton.me)

---

## License

MIT License
