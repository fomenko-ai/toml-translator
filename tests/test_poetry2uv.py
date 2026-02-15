import unittest
from pathlib import Path

from toml_translator.translator import poetry_to_uv
from toml_translator.utils import load_toml, re_space_after_comma, normalize


class TestPoetryToUv(unittest.TestCase):
    def test_basic_metadata_and_requires_python_and_deps(self):
        data = {
            "build-system": {
                "requires": ["poetry-core>=1.0.0"],
                "build-backend": "poetry.core.masonry.api",
            },
            "tool": {
                "poetry": {
                    "name": "demo",
                    "version": "0.1.0",
                    "description": "Demo project",
                    "authors": ["Aleksei Fomenko <fomenko_ai@proton.me>"],
                    "homepage": "https://example.com",
                    "repository": "https://github.com/example/example-poetry-project",
                    "documentation": "https://docs.example.com",
                    "dependencies": {
                        "python": "^3.11",
                        "requests": "^2.31",
                        "rich": {"version": ">=13", "markers": 'python_version >= "3.11"'},
                    },
                }
            },
        }

        out = poetry_to_uv(data)

        self.assertIn("project", out)
        project = out["project"]

        self.assertEqual(project["name"], "demo")
        self.assertEqual(project["version"], "0.1.0")
        self.assertEqual(project["description"], "Demo project")

        # authors -> list of dicts
        self.assertEqual(project["authors"], [{"name": "Aleksei Fomenko", "email": "fomenko_ai@proton.me"}])

        # requires-python from python constraint
        self.assertIn("requires-python", project)
        # ^3.11 -> >=3.11.0,<4.0.0
        self.assertEqual(project["requires-python"], ">=3.11.0, <4.0.0".replace(", ", ", "))

        # urls
        self.assertIn("urls", project)
        self.assertEqual(project["urls"]["Homepage"], "https://example.com")
        self.assertEqual(project["urls"]["Repository"], "https://github.com/example/example-poetry-project")
        self.assertEqual(project["urls"]["Documentation"], "https://docs.example.com")

        # dependencies list contains pep508-like strings
        deps = project.get("dependencies", [])
        self.assertTrue(any(d.startswith("requests ") or d == "requests" for d in deps))
        self.assertTrue(any(d.startswith("rich ") and ";" in d for d in deps))

        # build-system preserved
        self.assertEqual(out["build-system"]["build-backend"], "poetry.core.masonry.api")

    def test_groups_and_extras(self):
        data = {
            "tool": {
                "poetry": {
                    "name": "demo",
                    "version": "0.1.0",
                    "authors": ["Bob <bob@example.com>"],
                    "dependencies": {
                        "python": "^3.10",
                        "requests": "^2.31",
                        "uvicorn": {"version": "^0.30", "optional": True},
                    },
                    "extras": {
                        "server": ["uvicorn"]
                    },
                    "group": {
                        "dev": {
                            "dependencies": {
                                "pytest": "^8.0",
                                "mypy": {"version": "^1.10", "markers": 'platform_system != "Windows"'},
                            }
                        }
                    },
                }
            }
        }

        out = poetry_to_uv(data)

        # dependency groups
        self.assertIn("dependency-groups", out)
        self.assertIn("dev", out["dependency-groups"])
        dev = out["dependency-groups"]["dev"]
        self.assertTrue(any(s.startswith("pytest ") or s == "pytest" for s in dev))
        self.assertTrue(any(s.startswith("mypy ") and ";" in s for s in dev))

        # optional-dependencies from extras
        project = out["project"]
        self.assertIn("optional-dependencies", project)
        self.assertIn("server", project["optional-dependencies"])
        server_list = project["optional-dependencies"]["server"]
        self.assertTrue(any("uvicorn" in s for s in server_list))

    def test_direct_references_git_url_path(self):
        data = {
            "tool": {
                "poetry": {
                    "name": "demo",
                    "version": "0.1.0",
                    "authors": ["A <a@a.com>"],
                    "dependencies": {
                        "python": "^3.11",
                        "mypkg_git": {"git": "https://github.com/org/repo.git", "rev": "v1.2.3"},
                        "mypkg_url": {"url": "https://files.example.com/mypkg-1.0.0.whl"},
                        "mypkg_path": {"path": "./local_pkg", "develop": True},
                    },
                }
            }
        }

        out = poetry_to_uv(data)
        deps = out["project"]["dependencies"]

        self.assertTrue(any(d.startswith("mypkg_git @ git+https://github.com/org/repo.git@v1.2.3") for d in deps))
        self.assertTrue(any(d.startswith("mypkg_url @ https://files.example.com/mypkg-1.0.0.whl") for d in deps))
        self.assertTrue(any(d.startswith("mypkg_path @ file:./local_pkg") for d in deps))

    def test_missing_tool_poetry_raises(self):
        data = {"project": {"name": "x"}}
        with self.assertRaises(ValueError):
            poetry_to_uv(data)


class TestFileTranslationPoetryToUv(unittest.TestCase):
    def test_poetry_file_translates_to_expected_uv_file(self):
        base = Path(__file__).resolve().parent.parent / "assets/examples/"
        poetry_path = base / "pyproject.poetry.toml"
        uv_expected_path = base / "out.uv.toml"

        poetry_data = load_toml(poetry_path)
        uv_expected = load_toml(uv_expected_path)

        uv_actual = poetry_to_uv(poetry_data)

        self.assertEqual(normalize(uv_actual), normalize(uv_expected))


if __name__ == "__main__":
    unittest.main()
