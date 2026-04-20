# =============================================================================
# RETRODB - Shared Formatters
# =============================================================================
# Byte-size formatting and system→manufacturer lookup used by analytics,
# template filters, and stats endpoints.
# =============================================================================

MANUFACTURER_MAP = {
    'nes': 'Nintendo', 'snes': 'Nintendo', 'n64': 'Nintendo', 'gc': 'Nintendo',
    'gamecube': 'Nintendo', 'wii': 'Nintendo', 'wiiu': 'Nintendo', 'switch': 'Nintendo',
    'gb': 'Nintendo', 'gbc': 'Nintendo', 'gba': 'Nintendo', 'nds': 'Nintendo',
    'n3ds': 'Nintendo', '3ds': 'Nintendo', 'virtualboy': 'Nintendo', 'fds': 'Nintendo',
    'famicom': 'Nintendo', 'superfamicom': 'Nintendo', 'pokemini': 'Nintendo',
    'psx': 'Sony', 'ps2': 'Sony', 'ps3': 'Sony', 'ps4': 'Sony', 'ps5': 'Sony',
    'psp': 'Sony', 'psvita': 'Sony', 'vita': 'Sony',
    'genesis': 'Sega', 'megadrive': 'Sega', 'mastersystem': 'Sega', 'sms': 'Sega',
    'segacd': 'Sega', 'sega32x': 'Sega', '32x': 'Sega', 'saturn': 'Sega',
    'dreamcast': 'Sega', 'gamegear': 'Sega', 'gg': 'Sega', 'sg1000': 'Sega',
    'xbox': 'Microsoft', 'xbox360': 'Microsoft', 'xboxone': 'Microsoft',
    'atari2600': 'Atari', 'atari5200': 'Atari', 'atari7800': 'Atari',
    'atarist': 'Atari', 'atari800': 'Atari', 'lynx': 'Atari', 'jaguar': 'Atari',
    'tg16': 'NEC', 'pcengine': 'NEC', 'pcenginecd': 'NEC', 'supergrafx': 'NEC',
    'neogeo': 'SNK', 'neogeocd': 'SNK', 'ngp': 'SNK', 'ngpc': 'SNK',
    'colecovision': 'Coleco', 'coleco': 'Coleco', 'intellivision': 'Mattel',
    '3do': 'Panasonic', 'channelf': 'Fairchild', 'odyssey2': 'Magnavox',
    'vectrex': 'GCE', 'wonderswan': 'Bandai', 'wonderswancolor': 'Bandai',
}


def get_manufacturer(folder):
    """Get manufacturer for a system folder."""
    if not folder:
        return 'Other'
    return MANUFACTURER_MAP.get(folder.lower(), 'Other')


def format_size(bytes_size):
    """Format bytes to human readable size."""
    if bytes_size is None:
        return "Unknown"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024
    return f"{bytes_size:.1f} PB"
