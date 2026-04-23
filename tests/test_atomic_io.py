"""Tests for services.atomic_io.atomic_write_json — Pass 19.7."""

import json
import os
import tempfile

import pytest

from services.atomic_io import atomic_write_json


class TestAtomicWriteJson:
    def test_writes_data_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')
            data = {'key': 'value', 'nested': {'a': 1}}

            atomic_write_json(path, data)

            with open(path) as f:
                assert json.load(f) == data

    def test_overwrites_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')
            with open(path, 'w') as f:
                json.dump({'old': True}, f)

            atomic_write_json(path, {'new': True})

            with open(path) as f:
                assert json.load(f) == {'new': True}

    def test_no_temp_file_left_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')

            atomic_write_json(path, {'k': 'v'})

            assert os.listdir(tmp) == ['settings.json']

    def test_temp_file_cleaned_up_on_failure(self):
        """If json.dump raises (e.g. unserializable data), the .tmp file
        should not be left behind cluttering the directory."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')

            unserializable = {'set': {1, 2, 3}}
            with pytest.raises(TypeError):
                atomic_write_json(path, unserializable)

            assert not os.path.exists(path)
            assert not os.path.exists(path + '.tmp')

    def test_original_file_intact_on_failure(self):
        """The whole point: a failed write must NEVER truncate the original."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'settings.json')
            original = {'api_key': 'secret', 'port': 5000}
            with open(path, 'w') as f:
                json.dump(original, f)

            unserializable = {'set': {1, 2, 3}}
            with pytest.raises(TypeError):
                atomic_write_json(path, unserializable)

            with open(path) as f:
                assert json.load(f) == original

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'sub', 'dir', 'settings.json')

            atomic_write_json(path, {'k': 'v'})

            assert os.path.exists(path)
