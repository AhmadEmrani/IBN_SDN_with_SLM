"""Allocate OpenFlow cookie IDs in the LLNet-owned positive BIGINT range."""
import secrets


def new_cookie() -> int:
    # 16-bit project prefix + 47-bit random suffix.  Always fits signed BIGINT.
    return (0x4C4C << 47) | secrets.randbits(47)
