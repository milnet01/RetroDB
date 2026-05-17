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

    def test_temp_file_cleaned_up_on_failure(self, tmp_path):
        """If json.dump raises (e.g. unserializable data), the .tmp file
        should not be left behind cluttering the directory."""
        path = tmp_path / 'settings.json'

        unserializable = {'set': {1, 2, 3}}
        with pytest.raises(TypeError):
            atomic_write_json(str(path), unserializable)

        assert not path.exists()
        assert not (tmp_path / 'settings.json.tmp').exists()

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
