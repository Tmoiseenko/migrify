"""Tests for ScriptLoader and MigrationCreator."""

from __future__ import annotations

from pathlib import Path

import pytest

from migrify.script.creator import MigrationCreator
from migrify.script.loader import MigrationScript, ScriptLoader


class TestScriptLoader:
    def test_empty_dir_returns_no_scripts(self, migrations_dir):
        loader = ScriptLoader(migrations_dir)
        assert loader.get_all_scripts() == []

    def test_nonexistent_dir_returns_no_scripts(self, tmp_path):
        loader = ScriptLoader(tmp_path / "no_such_dir")
        assert loader.get_all_scripts() == []

    def test_ignores_underscore_files(self, migrations_dir):
        (migrations_dir / "__init__.py").touch()
        (migrations_dir / "_helper.py").touch()
        loader = ScriptLoader(migrations_dir)
        assert loader.get_all_scripts() == []

    def test_ignores_files_without_timestamp_prefix(self, migrations_dir):
        (migrations_dir / "my_migration.py").touch()
        loader = ScriptLoader(migrations_dir)
        assert loader.get_all_scripts() == []

    def test_loads_valid_scripts(self, migrations_dir):
        (migrations_dir / "2024_01_01_000000_first.py").write_text("def upgrade(): pass\ndef downgrade(): pass\n")
        (migrations_dir / "2024_01_02_000000_second.py").write_text("def upgrade(): pass\ndef downgrade(): pass\n")
        loader = ScriptLoader(migrations_dir)
        scripts = loader.get_all_scripts()
        assert len(scripts) == 2
        assert scripts[0].name == "2024_01_01_000000_first"
        assert scripts[1].name == "2024_01_02_000000_second"

    def test_scripts_sorted_by_name(self, migrations_dir):
        # Write in reverse order
        (migrations_dir / "2024_03_01_000000_c.py").write_text("def upgrade(): pass\n")
        (migrations_dir / "2024_01_01_000000_a.py").write_text("def upgrade(): pass\n")
        (migrations_dir / "2024_02_01_000000_b.py").write_text("def upgrade(): pass\n")
        loader = ScriptLoader(migrations_dir)
        scripts = loader.get_all_scripts()
        names = [s.name for s in scripts]
        assert names == sorted(names)

    def test_get_pending_filters_ran(self, migrations_dir):
        (migrations_dir / "2024_01_01_000000_first.py").write_text("def upgrade(): pass\n")
        (migrations_dir / "2024_01_02_000000_second.py").write_text("def upgrade(): pass\n")
        loader = ScriptLoader(migrations_dir)
        pending = loader.get_pending(ran=["2024_01_01_000000_first"])
        assert len(pending) == 1
        assert pending[0].name == "2024_01_02_000000_second"

    def test_get_script_by_name(self, migrations_dir):
        name = "2024_01_01_000000_hello"
        (migrations_dir / f"{name}.py").write_text("def upgrade(): pass\n")
        loader = ScriptLoader(migrations_dir)
        script = loader.get_script(name)
        assert script is not None
        assert script.name == name

    def test_get_script_returns_none_if_missing(self, migrations_dir):
        loader = ScriptLoader(migrations_dir)
        assert loader.get_script("nonexistent") is None


class TestMigrationScript:
    def test_load_module(self, migrations_dir):
        path = migrations_dir / "2024_01_01_000000_test.py"
        path.write_text("VALUE = 42\ndef upgrade(): pass\ndef downgrade(): pass\n")
        script = MigrationScript(path)
        module = script.load()
        assert module.VALUE == 42

    def test_has_upgrade(self, migrations_dir):
        path = migrations_dir / "2024_01_01_000000_test.py"
        path.write_text("def upgrade(): pass\n")
        assert MigrationScript(path).has_upgrade() is True

    def test_has_no_downgrade(self, migrations_dir):
        path = migrations_dir / "2024_01_01_000000_test.py"
        path.write_text("def upgrade(): pass\n")
        assert MigrationScript(path).has_downgrade() is False


class TestMigrationCreator:
    def test_create_empty_migration(self, migrations_dir):
        creator = MigrationCreator(migrations_dir)
        path = creator.create("do_something")
        assert path.exists()
        content = path.read_text()
        assert "def upgrade" in content
        assert "def downgrade" in content

    def test_create_table_migration(self, migrations_dir):
        creator = MigrationCreator(migrations_dir)
        path = creator.create("create_users", create_table="users")
        content = path.read_text()
        assert 'op.create_table' in content
        assert '"users"' in content
        assert 'op.drop_table' in content

    def test_create_update_migration(self, migrations_dir):
        creator = MigrationCreator(migrations_dir)
        path = creator.create("alter_users", update_table="users")
        content = path.read_text()
        assert 'batch_alter_table' in content
        assert '"users"' in content

    def test_filename_has_timestamp_prefix(self, migrations_dir):
        creator = MigrationCreator(migrations_dir)
        path = creator.create("my_migration")
        import re
        assert re.match(r"\d{4}_\d{2}_\d{2}_\d{6}_", path.name)

    def test_name_normalised(self, migrations_dir):
        creator = MigrationCreator(migrations_dir)
        path = creator.create("My Cool Migration")
        assert "my_cool_migration" in path.name

    def test_create_autogenerate_migration(self, migrations_dir):
        creator = MigrationCreator(migrations_dir)
        path = creator.create(
            "add_phone",
            upgrade_body="    op.add_column('users', sa.Column('phone', sa.String(20)))",
            downgrade_body="    op.drop_column('users', 'phone')",
        )
        content = path.read_text()
        assert "op.add_column" in content
        assert "op.drop_column" in content

