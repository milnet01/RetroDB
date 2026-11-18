# =============================================================================
# Migration 045 — repair systems the imports created bare
# =============================================================================
# The Steam, Xbox, PSN and CLZ imports named a new system after its folder in
# capitals when config had no name for it ("XBOXSERIESX"), looked for its logo
# only under IMAGE_PATH, and set no type. Imports now use
# game_utils.system_defaults; this gives existing rows the same. A name is
# replaced only while it is still the folder in capitals, and only an empty
# logo or type is filled, so nothing set by hand changes.
# =============================================================================

from services.game_utils import system_defaults


def apply(conn):
    c = conn.cursor()
    rows = c.execute("SELECT id, name, folder, logo, system_type FROM systems").fetchall()
    for system_id, name, folder, logo, system_type in rows:
        mapped_name, found_logo, detected_type = system_defaults(folder)
        if name == folder.upper() and mapped_name != name:
            c.execute("UPDATE systems SET name = ? WHERE id = ?", (mapped_name, system_id))
        if not logo and found_logo:
            c.execute("UPDATE systems SET logo = ? WHERE id = ?", (found_logo, system_id))
        if not system_type and detected_type:
            c.execute("UPDATE systems SET system_type = ? WHERE id = ?", (detected_type, system_id))
