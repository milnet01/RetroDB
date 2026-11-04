"""Which files a disc sheet or a playlist names (PASS-59-237).

A .cue or .gdi names the track files of one disc, and a .m3u names the
discs of one game. The ROM tools ask here before they delete, move or
rename a file, so they never break the sheet or playlist that needs it.
"""
import os
import re

SHEETS = ('.cue', '.gdi')

_CUE_FILE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE | re.MULTILINE)
# A .gdi track line: number, start sector, type, sector size, file name, offset.
_GDI_TRACK = re.compile(r'^\s*\d+\s+\d+\s+\d+\s+\d+\s+(?:"([^"]+)"|(\S+))')


def _read(path):
    try:
        with open(path, encoding='utf-8', errors='replace', newline='') as f:
            return f.read()
    except OSError:
        return None


def sheet_tracks(sheet):
    """Paths of the track files a .cue or .gdi names, in sheet order."""
    text = _read(sheet)
    ext = os.path.splitext(sheet)[1].lower()
    if text is None or ext not in SHEETS:
        return []
    if ext == '.cue':
        matches = _CUE_FILE.finditer(text)
    else:
        matches = filter(None, (_GDI_TRACK.match(line) for line in text.splitlines()[1:]))
    folder = os.path.dirname(sheet)
    return [os.path.join(folder, m.group(1) or m.group(2)) for m in matches]


def _files_with(folder, extensions):
    try:
        with os.scandir(folder) as entries:
            return [e.path for e in entries if e.is_file()
                    and os.path.splitext(e.name)[1].lower() in extensions]
    except OSError:
        return []


def tracks_in(folder):
    """Real paths of every track a sheet in `folder` names."""
    return {os.path.realpath(t) for sheet in _files_with(folder, SHEETS)
            for t in sheet_tracks(sheet)}


def sheets_naming(path):
    """The sheets in the file's own folder that name it as a track."""
    target = os.path.realpath(path)
    return [sheet for sheet in _files_with(os.path.dirname(path), SHEETS)
            if target in {os.path.realpath(t) for t in sheet_tracks(sheet)}]


def _playlist_entries(m3u):
    """(line, entry path) for each disc line of a .m3u."""
    text = _read(m3u) or ''
    folder = os.path.dirname(m3u)
    for line in text.splitlines(keepends=True):
        entry = line.strip()
        if entry and not entry.startswith('#'):
            yield line, os.path.join(folder, entry)


def playlists_naming(path):
    """The .m3u files in the file's folder or the one above that list it."""
    target = os.path.realpath(path)
    here = os.path.dirname(os.path.abspath(path))
    found = []
    for folder in dict.fromkeys((here, os.path.dirname(here))):
        for m3u in sorted(_files_with(folder, ('.m3u',))):
            if any(os.path.realpath(p) == target for _l, p in _playlist_entries(m3u)):
                found.append(m3u)
    return found


def repoint_playlists(old, new):
    """Make every playlist that lists `old` list `new` instead."""
    target = os.path.realpath(old)
    for m3u in playlists_naming(old):
        folder = os.path.dirname(m3u)
        out = []
        for line in (_read(m3u) or '').splitlines(keepends=True):
            entry = line.strip()
            if entry and not entry.startswith('#') and \
                    os.path.realpath(os.path.join(folder, entry)) == target:
                ending = line[len(line.rstrip('\r\n')):]
                line = os.path.relpath(new, folder).replace(os.sep, '/') + ending
            out.append(line)
        with open(m3u, 'w', encoding='utf-8', newline='') as f:
            f.write(''.join(out))


def rename_disc(old, new):
    """Rename a ROM file; a playlist that listed it lists the new name."""
    os.rename(old, new)
    repoint_playlists(old, new)
