from functools import lru_cache

from ..config import settings
from .index import PacketIndex, build_index
from .loader import load_packet


@lru_cache(maxsize=1)
def get_index() -> PacketIndex:
    """The single, shared, immutable packet index for this process."""
    return build_index(load_packet(settings.packet_path))
