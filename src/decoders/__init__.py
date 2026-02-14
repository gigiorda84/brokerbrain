"""Deterministic data decoders — CF and ATECO lookups."""

from src.decoders.ateco import lookup_ateco
from src.decoders.codice_fiscale import decode_cf

__all__ = ["decode_cf", "lookup_ateco"]
