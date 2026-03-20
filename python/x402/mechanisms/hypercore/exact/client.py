"""Exact scheme client implementation for Hyperliquid."""

import time
from typing import Any

from x402.schemas import (
    PaymentRequirements,
)

from ..constants import NETWORK_CONFIGS, NETWORK_SIGNATURE_CHAIN_IDS, SCHEME_EXACT

CHAIN_NAME_MAP = {
    "hyperliquid:mainnet": "Mainnet",
    "hyperliquid:testnet": "Testnet",
}


class ExactHypercoreScheme:
    """Client scheme for Hyperliquid exact payments."""

    def __init__(self, signer: Any):
        """Initialize client with a Hyperliquid signer.

        Args:
            signer: Hyperliquid signer with sign_send_asset method.
        """
        self.signer = signer
        self.scheme = SCHEME_EXACT

    def create_payment_payload(self, requirements: PaymentRequirements) -> dict[str, Any]:
        """Create a payment payload for Hyperliquid.

        Args:
            requirements: Payment requirements from server.

        Returns:
            Inner payload dict with signed SendAsset action.
        """
        nonce = int(time.time() * 1000)

        network = str(requirements.network)
        config = NETWORK_CONFIGS.get(network)
        if not config:
            raise ValueError(f"Unsupported network: {network}")

        chain_name = CHAIN_NAME_MAP.get(network)
        if not chain_name:
            raise ValueError(f"Unknown chain name for network: {network}")

        # Amount conversion using string arithmetic only (no floating-point)
        amount_int = int(requirements.amount)
        decimals = config["default_asset"]["decimals"]
        amount_str = _int_to_decimal_string(amount_int, decimals)

        extra = requirements.extra or {}
        destination_dex = extra.get("destinationDex", "spot")

        signature_chain_id = NETWORK_SIGNATURE_CHAIN_IDS.get(network)
        if not signature_chain_id:
            raise ValueError(f"No signatureChainId for network: {network}")

        action = {
            "type": "sendAsset",
            "hyperliquidChain": chain_name,
            "signatureChainId": signature_chain_id,
            "destination": requirements.pay_to.lower(),
            "sourceDex": "spot",
            "destinationDex": destination_dex,
            "token": requirements.asset,
            "amount": amount_str,
            "fromSubAccount": "",
            "nonce": nonce,
        }

        signature = self.signer.sign_send_asset(action)

        return {
            "action": action,
            "signature": signature,
            "nonce": nonce,
        }


def _int_to_decimal_string(amount: int, decimals: int) -> str:
    """Convert an integer amount to a decimal string with exact precision.

    Uses string operations only — no floating-point arithmetic.

    Args:
        amount: Integer amount in raw units.
        decimals: Number of decimal places.

    Returns:
        Decimal string (e.g., 1000000 with 8 decimals → "0.01000000").
    """
    amount_str = str(amount)
    if len(amount_str) <= decimals:
        amount_str = amount_str.zfill(decimals + 1)
    integer_part = amount_str[:-decimals]
    fractional_part = amount_str[-decimals:]
    return f"{integer_part}.{fractional_part}"
