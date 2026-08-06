"""Tests for services.atomic_io.atomic_write_json — Pass 19.7."""

import json
import os

import pytest

from services.atomic_io import atomic_write_json


class TestAtomicWriteJson:
    def test_writes_data_correctly(self, tmp_path):
        path = tmp_path / 'settings.json'
        data = {'key': 'value', 'nested': {'a': 1}}

        atomic_write_json(str(path), data)

        assert json.loads(path.read_text()) == data

    def test_overwrites_existing_file(self, tmp_path):
        path = tmp_path / 'settings.json'
        path.write_text(json.dumps({'old': True}))

        atomic_write_json(str(path), {'new': True})

        assert json.loads(path.read_text()) == {'new': True}

    def test_no_temp_file_left_on_success(self, tmp_path):
        path = tmp_path / 'settings.json'

        atomic_write_json(str(path), {'k': 'v'})

        assert os.listdir(tmp_path) == ['settings.json']

    def test_serialization_failure_creates_nothing(self, tmp_path):
        """An unserializable object must raise BEFORE any file is touched.

        `atomic_write_json` calls `json.dumps` (not `json.dump` into the open
        tempfile) precisely so its documented Raises contract holds with no
        side effect on disk.

        Pass 57.7 item 8: this asserted `settings.json.tmp` was absent — a
        static suffix services/atomic_io.py has never used (it uses
        `mkstemp(prefix='.atomic_')`), so the assertion could not fail. The
        directory-empty form below says something real, but note it still
        cannot exercise the cleanup in `atomic_write_bytes`' finally block:
        serialization fails too early for a tempfile to exist. That path is
        pinned by `test_tempfile_removed_when_the_swap_fails` below.
        """
        path = tmp_path / 'settings.json'

        unserializable = {'set': {1, 2, 3}}
        with pytest.raises(TypeError):
            atomic_write_json(str(path), unserializable)

        assert not path.exists()
        residue = os.listdir(tmp_path)
        assert residue == [], f"serialization failure created files: {residue}"

    def test_tempfile_removed_when_the_swap_fails(self, tmp_path, monkeypatch):
        """A failure AFTER mkstemp must leave no `.atomic_*` residue behind.

        The only path that actually reaches the cleanup in
        `atomic_write_bytes`' finally block — by then the tempfile is on disk
        and holds the new contents. Without the cleanup, every failed write
        leaves a stray dotfile next to the real settings file forever.
        """
        path = tmp_path / 'settings.json'
        original = {'api_key': 'secret', 'port': 5000}
        path.write_text(json.dumps(original))

        def _boom(src, dst):
            raise OSError('simulated cross-device swap failure')

        monkeypatch.setattr(os, 'replace', _boom)

        with pytest.raises(OSError):
            atomic_write_json(str(path), {'new': True})

        assert json.loads(path.read_text()) == original, \
            'a failed swap must not disturb the original'
        residue = [n for n in os.listdir(tmp_path) if n != 'settings.json']
        assert residue == [], f"tempfile residue left behind: {residue}"

    def test_original_file_intact_on_failure(self, tmp_path):
        """The whole point: a failed write must NEVER truncate the original."""
        path = tmp_path / 'settings.json'
        original = {'api_key': 'secret', 'port': 5000}
        path.write_text(json.dumps(original))

        unserializable = {'set': {1, 2, 3}}
        with pytest.raises(TypeError):
            atomic_write_json(str(path), unserializable)

        assert json.loads(path.read_text()) == original

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / 'sub' / 'dir' / 'settings.json'

        atomic_write_json(str(path), {'k': 'v'})

        assert path.exists()
