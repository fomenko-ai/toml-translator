import unittest
from pathlib import Path

from toml_translator.translator import uv_to_poetry
from toml_translator.utils import load_toml, re_space_after_comma, normalize


class TestUvToPoetry(unittest.TestCase):
    def test_basic_metadata_requires_python_and_deps(self):
        data = {
            "build-system": {
                "requires": ["hatchling"],
                "build-backend": "hatchling.build",
            },
            "project": {
                "name": "demo",
                "version": "1.2.3",
                "description": "Demo",
                "requires-python": ">=3.10",
                "authors": [{"name": "Aleksei Fomenko", "email": "fomenko_ai@proton.me"}],
                "urls": {
                    "Homepage": "https://example.com",
                    "Repository": "https://github.com/example/example-uv-project",
                },
                "dependencies": [
                    "requests>=2.31",
                    'rich>=13 ; python_version >= "3.11"',
                ],
            },
        }

        out = uv_to_poetry(data)

        self.assertIn("tool", out)
        self.assertIn("poetry", out["tool"])
        poetry = out["tool"]["poetry"]

        self.assertEqual(poetry["name"], "demo")
        self.assertEqual(poetry["version"], "1.2.3")
        self.assertEqual(poetry["description"], "Demo")

        # authors dict -> string
        self.assertEqual(poetry["authors"], ["Aleksei Fomenko <fomenko_ai@proton.me>"])

        # urls back
        self.assertEqual(poetry["homepage"], "https://example.com")
        self.assertEqual(poetry["repository"], "https://github.com/example/example-uv-project")

        # dependencies include python
        deps = poetry["dependencies"]
        self.assertEqual(deps["python"], ">=3.10")
        self.assertIn("requests", deps)
        self.assertIn("rich", deps)

        # rich has markers in dict form
        self.assertIsInstance(deps["rich"], dict)
        self.assertIn("markers", deps["rich"])

        # build-system preserved
        self.assertEqual(out["build-system"]["build-backend"], "hatchling.build")

    def test_dependency_groups_to_poetry_groups(self):
        data = {
            "project": {
                "name": "demo",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": ["requests>=2.0"],
            },
            "dependency-groups": {
                "dev": [
                    "pytest>=8",
                    'mypy>=1.10 ; platform_system != "Windows"',
                ],
                "test": [
                    "hypothesis>=6"
                ],
            },
        }

        out = uv_to_poetry(data)
        poetry = out["tool"]["poetry"]

        self.assertIn("group", poetry)
        self.assertIn("dev", poetry["group"])
        self.assertIn("dependencies", poetry["group"]["dev"])
        devdeps = poetry["group"]["dev"]["dependencies"]
        self.assertIn("pytest", devdeps)
        self.assertIn("mypy", devdeps)
        self.assertIsInstance(devdeps["mypy"], dict)
        self.assertIn("markers", devdeps["mypy"])

        self.assertIn("test", poetry["group"])
        testdeps = poetry["group"]["test"]["dependencies"]
        self.assertIn("hypothesis", testdeps)

    def test_optional_dependencies_to_poetry_extras(self):
        data = {
            "project": {
                "name": "demo",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": ["requests>=2.31"],
                "optional-dependencies": {
                    "server": ["uvicorn>=0.30", "httptools>=0.6"],
                },
            }
        }

        out = uv_to_poetry(data)
        poetry = out["tool"]["poetry"]

        # extras created with dependency names
        self.assertIn("extras", poetry)
        self.assertIn("server", poetry["extras"])
        self.assertEqual(set(poetry["extras"]["server"]), {"uvicorn", "httptools"})

        # optional deps also appear in dependencies (best-effort behavior in translator)
        deps = poetry["dependencies"]
        self.assertIn("uvicorn", deps)
        self.assertIn("httptools", deps)

    def test_direct_refs_back_to_poetry(self):
        data = {
            "project": {
                "name": "demo",
                "version": "0.1.0",
                "requires-python": ">=3.11",
                "dependencies": [
                    "mypkg_git @ git+https://github.com/org/repo.git@v1.2.3",
                    "mypkg_url @ https://files.example.com/mypkg-1.0.0.whl",
                    "mypkg_path @ file:./local_pkg",
                ],
            }
        }

        out = uv_to_poetry(data)
        deps = out["tool"]["poetry"]["dependencies"]

        self.assertIn("mypkg_git", deps)
        self.assertIsInstance(deps["mypkg_git"], dict)
        self.assertEqual(deps["mypkg_git"]["git"], "https://github.com/org/repo.git")
        self.assertEqual(deps["mypkg_git"]["rev"], "v1.2.3")

        self.assertIn("mypkg_url", deps)
        self.assertEqual(deps["mypkg_url"]["url"], "https://files.example.com/mypkg-1.0.0.whl")

        self.assertIn("mypkg_path", deps)
        self.assertEqual(deps["mypkg_path"]["path"], "./local_pkg")

    def test_missing_project_raises(self):
        data = {"tool": {"poetry": {"name": "x"}}}
        with self.assertRaises(ValueError):
            uv_to_poetry(data)


class TestFileTranslationUvToPoetry(unittest.TestCase):
    def test_uv_file_translates_to_expected_poetry_file(self):
        base = Path(__file__).resolve().parent.parent / "assets/examples/"
        uv_path = base / "pyproject.uv.toml"
        poetry_expected_path = base / "out.poetry.toml"

        uv_data = load_toml(uv_path)
        poetry_expected = load_toml(poetry_expected_path)

        poetry_actual = uv_to_poetry(uv_data)

        self.assertEqual(normalize(poetry_actual), normalize(poetry_expected))


if __name__ == "__main__":
    unittest.main()
