"""Tests for ExactHypercoreScheme facilitator."""

import time

from x402.mechanisms.hypercore import NETWORK_MAINNET
from x402.mechanisms.hypercore.exact import ExactHypercoreFacilitatorScheme
from x402.schemas import PaymentPayload, PaymentRequirements, ResourceInfo


def make_valid_payload(
    network=NETWORK_MAINNET,
    action_type="sendAsset",
    destination="0x0987654321098765432109876543210987654321",
    source_dex="spot",
    destination_dex="spot",
    token="USDH:0x54e00a5988577cb0b0c9ab0cb6ef7f4b",
    amount="0.10000000",
    from_sub_account="",
    nonce=None,
    signature=None,
):
    """Create a valid PaymentPayload with sensible defaults."""
    if nonce is None:
        nonce = int(time.time() * 1000)
    if signature is None:
        signature = {"r": "0x" + "00" * 32, "s": "0x" + "00" * 32, "v": 27}

    return PaymentPayload(
        x402_version=2,
        resource=ResourceInfo(
            url="http://example.com/protected",
            description="Test resource",
            mime_type="application/json",
        ),
        accepted=PaymentRequirements(
            scheme="exact",
            network=network,
            asset=token,
            amount="10000000",
            pay_to=destination,
            max_timeout_seconds=3600,
        ),
        payload={
            "action": {
                "type": action_type,
                "hyperliquidChain": "Mainnet",
                "destination": destination,
                "sourceDex": source_dex,
                "destinationDex": destination_dex,
                "token": token,
                "amount": amount,
                "fromSubAccount": from_sub_account,
                "nonce": nonce,
            },
            "signature": signature,
            "nonce": nonce,
        },
    )


def make_requirements(
    network=NETWORK_MAINNET,
    asset="USDH:0x54e00a5988577cb0b0c9ab0cb6ef7f4b",
    amount="10000000",
    pay_to="0x0987654321098765432109876543210987654321",
    extra=None,
):
    """Create PaymentRequirements with sensible defaults."""
    if extra is None:
        extra = {}
    return PaymentRequirements(
        scheme="exact",
        network=network,
        asset=asset,
        amount=amount,
        pay_to=pay_to,
        max_timeout_seconds=3600,
        extra=extra,
    )


class TestExactHypercoreSchemeConstructor:
    """Test ExactHypercoreScheme facilitator constructor."""

    def test_should_create_instance_with_correct_scheme(self):
        """Should create instance with correct scheme."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        assert facilitator.scheme == "exact"

    def test_should_create_instance_with_api_url(self):
        """Should create instance with API URL."""
        api_url = "https://api.hyperliquid-testnet.xyz"
        facilitator = ExactHypercoreFacilitatorScheme(api_url)

        assert facilitator.api_url == api_url


class TestVerify:
    """Test verify method."""

    def test_should_reject_if_network_does_not_match(self):
        """Should reject if network does not match."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(network="invalid:network")
        requirements = make_requirements(network="invalid:network")

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_network" in result.invalid_reason

    def test_should_reject_if_action_type_is_wrong(self):
        """Should reject if action type is not sendAsset."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(action_type="wrongType")
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_action_type" in result.invalid_reason

    def test_should_reject_if_destination_does_not_match(self):
        """Should reject if destination does not match."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(destination="0xWrongDestination1234567890123456789012345")
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_recipient_mismatch" in result.invalid_reason

    def test_should_reject_if_amount_does_not_match(self):
        """Should reject if amount does not match exactly."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(amount="0.05000000")
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_amount" in result.invalid_reason

    def test_should_reject_if_token_does_not_match(self):
        """Should reject if token does not match."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(token="WRONG:0x00000000000000000000000000000000")
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_token_mismatch" in result.invalid_reason

    def test_should_reject_if_nonce_is_too_old(self):
        """Should reject if nonce is more than 1 hour old."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        old_nonce = int((time.time() - 7200) * 1000)
        payload = make_valid_payload(nonce=old_nonce)
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_nonce" in result.invalid_reason

    def test_should_reject_if_signature_is_missing_fields(self):
        """Should reject if signature is missing r, s, or v."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(signature={"r": "0x" + "00" * 32})
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_signature_structure" in result.invalid_reason

    def test_should_accept_valid_payment(self):
        """Should accept valid payment payload."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload()
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is True
        assert result.invalid_reason is None

    def test_should_reject_invalid_source_dex(self):
        """Should reject if sourceDex is not 'spot' or 'perp'."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(source_dex="invalid")
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_dex" in result.invalid_reason

    def test_should_reject_destination_dex_mismatch(self):
        """Should reject if destinationDex doesn't match requirements.extra."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(destination_dex="perp")
        requirements = make_requirements(extra={"destinationDex": "spot"})

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_dex" in result.invalid_reason

    def test_should_accept_matching_destination_dex_from_extra(self):
        """Should accept when destinationDex matches extra.destinationDex."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(destination_dex="perp")
        requirements = make_requirements(extra={"destinationDex": "perp"})

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is True

    def test_should_reject_perp_dex_with_non_usdc_token(self):
        """Should reject if perp DEX is used with a non-USDC token."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(
            source_dex="perp",
            token="HYPE:0x12345678901234567890123456789012",
        )
        requirements = make_requirements(
            asset="HYPE:0x12345678901234567890123456789012",
        )

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False
        assert "invalid_exact_hyperliquid_payload_dex" in result.invalid_reason
        assert "USDC-equivalent" in result.invalid_reason

    def test_should_accept_perp_dex_with_usdc_token(self):
        """Should accept perp DEX with USDC-equivalent token."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(source_dex="perp")
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is True

    def test_should_reject_non_empty_from_sub_account(self):
        """Should reject if fromSubAccount is not empty."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(from_sub_account="sub1")
        requirements = make_requirements()

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is False

    def test_should_default_destination_dex_to_spot(self):
        """Should default destinationDex to 'spot' when extra has no destinationDex."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        payload = make_valid_payload(destination_dex="spot")
        requirements = make_requirements()  # no extra

        result = facilitator.verify(payload, requirements)

        assert result.is_valid is True


class TestFacilitatorSchemeAttributes:
    """Test facilitator scheme attributes."""

    def test_scheme_attribute_is_exact(self):
        """scheme attribute should be 'exact'."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        assert facilitator.scheme == "exact"

    def test_caip_family_attribute(self):
        """caip_family attribute should be 'hyperliquid:*'."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        assert facilitator.caip_family == "hyperliquid:*"

    def test_get_extra_returns_none(self):
        """get_extra should return None for Hyperliquid."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        extra = facilitator.get_extra(NETWORK_MAINNET)

        assert extra is None

    def test_get_signers_returns_empty_list(self):
        """get_signers should return empty list."""
        facilitator = ExactHypercoreFacilitatorScheme("https://api.hyperliquid.xyz")

        result = facilitator.get_signers(NETWORK_MAINNET)

        assert result == []
