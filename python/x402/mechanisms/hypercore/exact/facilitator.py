"""Exact scheme facilitator implementation for Hyperliquid."""

import time
from typing import Any

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from x402.schemas import (
    Network,
    PaymentPayload,
    PaymentRequirements,
    SettleResponse,
    VerifyResponse,
)

from ..constants import (
    ERR_DESTINATION_MISMATCH,
    ERR_INSUFFICIENT_AMOUNT,
    ERR_INVALID_ACTION_TYPE,
    ERR_INVALID_DEX,
    ERR_INVALID_NETWORK,
    ERR_INVALID_SIGNATURE,
    ERR_NONCE_TOO_OLD,
    ERR_SETTLEMENT_FAILED,
    ERR_TOKEN_MISMATCH,
    MAX_NONCE_AGE_SECONDS,
    NETWORK_API_URLS,
    NETWORK_CONFIGS,
    SCHEME_EXACT,
    TX_HASH_LOOKBACK_WINDOW,
    TX_HASH_MAX_RETRIES,
    TX_HASH_RETRY_DELAY,
)

VALID_DEX_VALUES = {"spot", "perp"}


class ExactHypercoreScheme:
    """Facilitator scheme for Hyperliquid exact payments."""

    def __init__(self, api_url: str | None = None):
        """Initialize facilitator scheme.

        Args:
            api_url: Optional API URL override. If provided, used as fallback
                     when the network isn't in the built-in URL map.
        """
        self.api_url = api_url
        self.scheme = SCHEME_EXACT
        self.caip_family = "hyperliquid:*"

    def _get_api_url(self, network: str) -> str:
        """Get the API URL for a specific network.

        Looks up the built-in URL map first, then falls back to the
        configured override if provided.

        Args:
            network: Network identifier (e.g. hyperliquid:mainnet, hyperliquid:testnet).

        Returns:
            API URL for the network.

        Raises:
            ValueError: If no URL found for the network.
        """
        url = NETWORK_API_URLS.get(network) or self.api_url
        if not url:
            raise ValueError(f"No API URL configured for network: {network}")
        return url

    def get_extra(self, network: Network) -> dict[str, Any] | None:
        """Get extra facilitator metadata (none for Hyperliquid).

        Args:
            network: Network identifier.

        Returns:
            None.
        """
        return None

    def get_signers(self, network: str) -> list[str]:
        """Get facilitator signers (none needed).

        Args:
            network: Network identifier.

        Returns:
            Empty list (no addresses needed).
        """
        return []

    def verify(
        self, payload: PaymentPayload, requirements: PaymentRequirements, context=None
    ) -> VerifyResponse:
        """Verify a Hyperliquid payment payload.

        Args:
            payload: Payment payload with signed SendAsset action.
            requirements: Payment requirements to verify against.

        Returns:
            VerifyResponse indicating validity.
        """
        hypercore_payload = payload.payload

        network = str(requirements.network)
        if not network.startswith("hyperliquid:"):
            return VerifyResponse(
                is_valid=False,
                invalid_reason=f"{ERR_INVALID_NETWORK}: {network}",
            )

        config = NETWORK_CONFIGS.get(network)
        if not config:
            return VerifyResponse(
                is_valid=False,
                invalid_reason=f"{ERR_INVALID_NETWORK}: {network}",
            )

        action = hypercore_payload["action"]

        if action["type"] != "sendAsset":
            return VerifyResponse(
                is_valid=False,
                invalid_reason=f"{ERR_INVALID_ACTION_TYPE}: {action['type']}",
            )

        pay_to = str(requirements.pay_to)
        if action["destination"].lower() != pay_to.lower():
            return VerifyResponse(is_valid=False, invalid_reason=ERR_DESTINATION_MISMATCH)

        # Amount validation using string arithmetic only (no floating-point)
        decimals = config["default_asset"]["decimals"]
        required_amount = int(requirements.amount)
        expected_amount_str = _int_to_decimal_string(required_amount, decimals)

        if action["amount"] != expected_amount_str:
            return VerifyResponse(is_valid=False, invalid_reason=ERR_INSUFFICIENT_AMOUNT)

        asset = requirements.asset if hasattr(requirements, "asset") else None
        if asset and action["token"] != asset:
            return VerifyResponse(is_valid=False, invalid_reason=ERR_TOKEN_MISMATCH)

        now_ms = int(time.time() * 1000)
        nonce_age_seconds = (now_ms - hypercore_payload["nonce"]) / 1000

        if nonce_age_seconds > MAX_NONCE_AGE_SECONDS:
            return VerifyResponse(is_valid=False, invalid_reason=ERR_NONCE_TOO_OLD)

        sig = hypercore_payload["signature"]
        if not sig.get("r") or not sig.get("s") or "v" not in sig:
            return VerifyResponse(is_valid=False, invalid_reason=ERR_INVALID_SIGNATURE)

        # DEX validation
        source_dex = action.get("sourceDex", "")
        dest_dex = action.get("destinationDex", "")

        if source_dex not in VALID_DEX_VALUES:
            return VerifyResponse(
                is_valid=False,
                invalid_reason=f"{ERR_INVALID_DEX}: invalid sourceDex '{source_dex}'",
            )

        extra = requirements.extra or {}
        expected_dest_dex = extra.get("destinationDex", "spot")
        if dest_dex != expected_dest_dex:
            return VerifyResponse(
                is_valid=False,
                invalid_reason=f"{ERR_INVALID_DEX}: destinationDex '{dest_dex}' does not match required '{expected_dest_dex}'",
            )

        # Perp DEX requires USDC-equivalent token
        if source_dex == "perp" or dest_dex == "perp":
            token_name = action.get("token", "").split(":")[0].upper()
            if token_name not in ("USDC", "USDH"):
                return VerifyResponse(
                    is_valid=False,
                    invalid_reason=f"{ERR_INVALID_DEX}: perp DEX requires USDC-equivalent token, got '{action.get('token', '')}'",
                )

        # fromSubAccount must be empty
        if action.get("fromSubAccount", "") != "":
            return VerifyResponse(
                is_valid=False,
                invalid_reason=f"{ERR_INVALID_ACTION_TYPE}: fromSubAccount must be empty",
            )

        return VerifyResponse(is_valid=True)

    def _recover_payer(self, action: dict[str, Any], signature: dict[str, Any]) -> str:
        """Recover payer address from EIP-712 signature.

        The Hyperliquid SDK signs with chainId in the EIP-712 domain
        (read from action.signatureChainId). We must match that domain
        exactly to recover the correct signer address.

        Args:
            action: SendAsset action that was signed.
            signature: Signature (r, s, v).

        Returns:
            Ethereum address of payer.
        """
        try:
            # Build domain — include chainId if signatureChainId is present
            # (the Hyperliquid SDK always includes it)
            domain_types = [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ]
            domain = {
                "name": "HyperliquidSignTransaction",
                "version": "1",
                "chainId": int(action["signatureChainId"], 16),
                "verifyingContract": "0x0000000000000000000000000000000000000000",
            }

            typed_data = {
                "types": {
                    "EIP712Domain": domain_types,
                    "HyperliquidTransaction:SendAsset": [
                        {"name": "hyperliquidChain", "type": "string"},
                        {"name": "destination", "type": "string"},
                        {"name": "sourceDex", "type": "string"},
                        {"name": "destinationDex", "type": "string"},
                        {"name": "token", "type": "string"},
                        {"name": "amount", "type": "string"},
                        {"name": "fromSubAccount", "type": "string"},
                        {"name": "nonce", "type": "uint64"},
                    ],
                },
                "primaryType": "HyperliquidTransaction:SendAsset",
                "domain": domain,
                "message": {
                    "hyperliquidChain": action["hyperliquidChain"],
                    "destination": action["destination"],
                    "sourceDex": action["sourceDex"],
                    "destinationDex": action["destinationDex"],
                    "token": action["token"],
                    "amount": action["amount"],
                    "fromSubAccount": action["fromSubAccount"],
                    "nonce": action["nonce"],
                },
            }

            encoded_data = encode_typed_data(full_message=typed_data)  # type: ignore

            r = int(signature["r"], 16)
            s = int(signature["s"], 16)
            v = signature["v"]

            sig_bytes = r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([v])

            account = Account.recover_message(encoded_data, signature=sig_bytes)  # type: ignore
            return account
        except Exception as e:
            print(f"Failed to recover payer: {e}")
            return "0x0000000000000000000000000000000000000000"

    def settle(
        self, payload: PaymentPayload, requirements: PaymentRequirements, context=None
    ) -> SettleResponse:
        """Settle a Hyperliquid payment by submitting to Hyperliquid API.

        Args:
            payload: Verified payment payload.
            requirements: Payment requirements.

        Returns:
            SettleResponse with transaction hash.
        """
        verify_result = self.verify(payload, requirements)
        if not verify_result.is_valid:
            network = str(requirements.network)
            return SettleResponse(
                success=False,
                error_reason=verify_result.invalid_reason or "invalid_payload",
                transaction="",
                network=network,
            )

        hypercore_payload = payload.payload
        network = str(requirements.network)
        api_url = self._get_api_url(network)

        payer = self._recover_payer(hypercore_payload["action"], hypercore_payload["signature"])

        start_time = time.time()

        with httpx.Client() as client:
            response = client.post(
                f"{api_url}/exchange",
                json={
                    "action": hypercore_payload["action"],
                    "nonce": hypercore_payload["nonce"],
                    "signature": hypercore_payload["signature"],
                    "vaultAddress": None,
                },
            )

            if response.status_code != 200:
                print(
                    f"[Hyperliquid] Settlement HTTP error {response.status_code}: {response.text}"
                )
                return SettleResponse(
                    success=False,
                    error_reason=f"{ERR_SETTLEMENT_FAILED}: HTTP {response.status_code} - {response.text}",
                    transaction="",
                    network=network,
                )

            result = response.json()
            if result.get("status") != "ok":
                print(f"[Hyperliquid] Settlement API error: {result}")
                return SettleResponse(
                    success=False,
                    error_reason=f"{ERR_SETTLEMENT_FAILED}: {result}",
                    transaction="",
                    network=network,
                )

        tx_hash = self._get_transaction_hash(
            api_url,
            payer,
            hypercore_payload["action"]["destination"],
            hypercore_payload["nonce"],
            start_time,
        )

        if tx_hash is None:
            return SettleResponse(
                success=False,
                error_reason=f"{ERR_SETTLEMENT_FAILED}: transaction hash not found after {TX_HASH_MAX_RETRIES} attempts",
                transaction="",
                network=network,
            )

        return SettleResponse(
            success=True,
            transaction=tx_hash,
            network=network,
            payer=payer,
        )

    def _get_transaction_hash(
        self, api_url: str, user: str, destination: str, nonce: int, start_time: float
    ) -> str | None:
        """Query Hyperliquid ledger for transaction hash.

        Args:
            api_url: Hyperliquid API URL to query.
            user: Payer address.
            destination: Recipient address.
            nonce: Transaction nonce.
            start_time: Time when settlement was initiated.

        Returns:
            Transaction hash from Hyperliquid ledger, or None if not found.
        """
        with httpx.Client() as client:
            for attempt in range(TX_HASH_MAX_RETRIES):
                if attempt > 0:
                    time.sleep(TX_HASH_RETRY_DELAY)

                response = client.post(
                    f"{api_url}/info",
                    json={
                        "type": "userNonFundingLedgerUpdates",
                        "user": user,
                        "startTime": int((start_time - TX_HASH_LOOKBACK_WINDOW) * 1000),
                    },
                )

                if response.status_code != 200:
                    continue

                updates = response.json()

                for update in updates:
                    delta = update.get("delta", {})
                    if (
                        delta.get("type") == "send"
                        and delta.get("destination", "").lower() == destination.lower()
                        and delta.get("nonce") == nonce
                    ):
                        return update["hash"]

        return None


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
