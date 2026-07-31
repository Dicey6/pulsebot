"""
Generate real Solana keypairs and BIP39 mnemonics.
Wallets are valid but never used on-chain.
"""
import hashlib
import hmac
import struct

from mnemonic import Mnemonic
from solders.keypair import Keypair

mnemo = Mnemonic("english")


def _derive_solana_keypair_from_seed(seed_bytes: bytes) -> Keypair:
    """Derive Solana keypair using path m/44'/501'/0'/0' (SLIP-10 ed25519)."""

    def _derive_child(key: bytes, chain: bytes, index: int) -> tuple[bytes, bytes]:
        hardened_index = index + 0x80000000
        data = b"\x00" + key + struct.pack(">I", hardened_index)
        I = hmac.new(chain, data, hashlib.sha512).digest()
        return I[:32], I[32:]

    # Master key
    I = hmac.new(b"ed25519 seed", seed_bytes, hashlib.sha512).digest()
    key, chain = I[:32], I[32:]

    for index in [44, 501, 0, 0]:
        key, chain = _derive_child(key, chain, index)

    return Keypair.from_seed(key)


def generate_wallet() -> tuple[str, str]:
    """Returns (public_address, mnemonic_phrase)."""
    phrase = mnemo.generate(strength=128)  # 12 words
    seed = Mnemonic.to_seed(phrase, passphrase="")
    keypair = _derive_solana_keypair_from_seed(seed[:32])
    return str(keypair.pubkey()), phrase
