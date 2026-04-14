"""Tests for Phase 14: Operator Notifications (Telegram).

Coverage:
1. Typed notification envelopes and default severity behavior
2. Async event bus subscriptions, fan-out, and error isolation
3. Deterministic formatting for all required event types
4. Telegram delivery security, retry, deduplication, and broadcast behavior
5. Notification repositories for event and delivery audit queries
6. Notification service persistence, routing, and delivery audit trails
7. Alert composer prompt construction for complex notification formatting
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agents.providers import LLMResponse, ProviderRouter
from agents.types import AgentInput
from config.settings import TelegramConfig
from core.enums import NotificationSeverity, NotificationType
from data.models.notification import NotificationDeliveryRecord, NotificationEvent
from notifications.composer import AlertComposerAgent
from notifications.events import NotificationEventBus
from notifications import formatter as notification_formatter
from notifications.formatter import format_notification
from notifications.repository import (
    NotificationDeliveryRepository,
    NotificationEventRepository,
)
from notifications.service import NotificationService
from notifications.telegram import (
    TELEGRAM_API_BASE,
    TELEGRAM_MAX_LENGTH,
    TelegramClient,
    TelegramDeliveryResult,
)
from notifications.types import (
    NoTradePayload,
    NotificationEnvelope,
    OperatorAbsencePayload,
    RiskAlertPayload,
    StrategyViabilityPayload,
    SystemHealthPayload,
    TradeEntryPayload,
    TradeExitPayload,
    WeeklyPerformancePayload,
    create_envelope,
)


def make_trade_entry_envelope(
    *,
    severity: NotificationSeverity | None = None,
    dedup_key: str | None = "entry-001",
    market_id: str | None = None,
    position_id: str | None = None,
    workflow_run_id: str | None = None,
) -> NotificationEnvelope:
    """Build a representative trade-entry notification for tests."""
    return create_envelope(
        NotificationType.TRADE_ENTRY,
        TradeEntryPayload(
            market_title="Will a bill pass?",
            market_identifier="bill-pass-2026",
            side="Yes",
            entry_price=0.61,
            allocated_capital_usd=250.0,
            portfolio_percentage=2.5,
            confidence=0.72,
            estimated_edge=0.11,
            thesis_summary="Committee timing and whip counts favor passage.",
            trade_id="trade-entry-001",
            workflow_source="investigator",
        ),
        severity=severity,
        dedup_key=dedup_key,
        market_id=market_id,
        position_id=position_id,
        workflow_run_id=workflow_run_id,
    )


def make_trade_exit_envelope(
    *,
    severity: NotificationSeverity = NotificationSeverity.INFO,
) -> NotificationEnvelope:
    return create_envelope(
        NotificationType.TRADE_EXIT,
        TradeExitPayload(
            market_title="Will a bill pass?",
            market_identifier="bill-pass-2026",
            side="Yes",
            exit_type="full",
            exit_reason="Target price reached",
            exit_class="profit_protection",
            exit_price=0.74,
            realized_pnl_usd=52.75,
            remaining_size_usd=0.0,
            trade_id="trade-exit-001",
            workflow_source="position_review",
        ),
        severity=severity,
    )


def make_risk_alert_envelope(
    *,
    severity: NotificationSeverity = NotificationSeverity.WARNING,
) -> NotificationEnvelope:
    return create_envelope(
        NotificationType.RISK_ALERT,
        RiskAlertPayload(
            threshold_type="entries_disabled",
            current_equity_usd=9250.0,
            start_of_day_equity_usd=10000.0,
            current_drawdown_pct=0.075,
            deployed_capital_usd=3400.0,
            risk_state="entries_disabled",
            affected_position_ids=["pos-1", "pos-2"],
            detail="Daily drawdown threshold breached.",
        ),
        severity=severity,
    )


def make_no_trade_envelope(
    *,
    severity: NotificationSeverity = NotificationSeverity.INFO,
) -> NotificationEnvelope:
    return create_envelope(
        NotificationType.NO_TRADE,
        NoTradePayload(
            workflow_run_duration_seconds=18.4,
            reason="healthy_no_trade",
            candidates_reviewed=7,
            top_rejected_market="Will the treaty clear parliament?",
            rejection_reasons=["weak_evidence", "wide_spread"],
            is_healthy=True,
        ),
        severity=severity,
    )


def make_weekly_performance_envelope(
    *,
    severity: NotificationSeverity = NotificationSeverity.INFO,
) -> NotificationEnvelope:
    return create_envelope(
        NotificationType.WEEKLY_PERFORMANCE,
        WeeklyPerformancePayload(
            realized_pnl_usd=130.0,
            unrealized_pnl_usd=-12.5,
            total_wins=4,
            total_losses=2,
            best_category="politics",
            worst_category="sports",
            strengths=["timely catalysts", "strong no-trade discipline"],
            weaknesses=["sports sizing"],
            policy_recommendations=["keep sports multiplier at 0.5"],
            system_brier_score=0.176,
            market_brier_score=0.191,
            cost_of_selectivity_ratio=0.14,
        ),
        severity=severity,
    )


def make_system_health_envelope(
    *,
    severity: NotificationSeverity = NotificationSeverity.WARNING,
) -> NotificationEnvelope:
    return create_envelope(
        NotificationType.SYSTEM_HEALTH,
        SystemHealthPayload(
            health_event="api_failure",
            service="gamma_client",
            summary="Primary market data source timed out twice.",
            run_id="run-health-001",
            detail="Fallback source is serving current prices.",
        ),
        severity=severity,
    )


def make_strategy_viability_envelope(
    *,
    severity: NotificationSeverity = NotificationSeverity.WARNING,
) -> NotificationEnvelope:
    return create_envelope(
        NotificationType.STRATEGY_VIABILITY,
        StrategyViabilityPayload(
            checkpoint_type="budget_warning",
            system_brier=0.184,
            market_brier=0.197,
            system_advantage=0.013,
            lifetime_budget_consumed_pct=0.76,
            bias_pattern_name="bullish_skew",
            detail="Budget threshold crossed before week-8 checkpoint.",
        ),
        severity=severity,
    )


def make_operator_absence_envelope(
    *,
    severity: NotificationSeverity = NotificationSeverity.CRITICAL,
    dedup_key: str | None = "absence-001",
    market_id: str | None = None,
) -> NotificationEnvelope:
    return create_envelope(
        NotificationType.OPERATOR_ABSENCE,
        OperatorAbsencePayload(
            absence_event="mode_activation",
            absence_level=4,
            hours_since_last_interaction=122.0,
            autonomous_actions_taken=["cancel_new_entries", "reduce_positions"],
            detail="Graceful wind-down is active.",
        ),
        severity=severity,
        dedup_key=dedup_key,
        market_id=market_id,
    )


class StubHttpClient:
    """Minimal async http client stub for Telegram tests."""

    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.closed = False

    async def post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        self.calls.append((url, json))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def session_factory(engine):
    """Build a fresh async session factory for service/repository tests."""
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def clean_notification_tables(session_factory) -> None:
    """Keep notification persistence tests isolated despite committed service sessions."""
    async with session_factory() as session:
        await session.execute(delete(NotificationDeliveryRecord))
        await session.execute(delete(NotificationEvent))
        await session.commit()
    yield
    async with session_factory() as session:
        await session.execute(delete(NotificationDeliveryRecord))
        await session.execute(delete(NotificationEvent))
        await session.commit()


def build_telegram_config(**overrides: Any) -> TelegramConfig:
    data = {
        "bot_token": "bot-token",
        "chat_id": "chat-1,chat-2",
        "enabled": True,
        "max_retries": 3,
        "retry_base_delay_seconds": 1.0,
        "dedup_window_seconds": 300,
        "request_timeout_seconds": 30.0,
    }
    data.update(overrides)
    return TelegramConfig(**data)


def response(
    status_code: int,
    *,
    json_body: dict[str, Any] | None = None,
    text: str = "",
) -> httpx.Response:
    kwargs: dict[str, Any] = {
        "request": httpx.Request("POST", "https://api.telegram.org/bot/sendMessage"),
    }
    if json_body is not None:
        kwargs["json"] = json_body
    elif text:
        kwargs["text"] = text
    return httpx.Response(status_code=status_code, **kwargs)


class TestNotificationTypes:
    def test_create_envelope_uses_default_severity_and_serializes_payload(self) -> None:
        envelope = make_trade_entry_envelope(
            market_id=str(uuid.uuid4()),
            position_id=str(uuid.uuid4()),
            workflow_run_id=str(uuid.uuid4()),
        )

        assert envelope.event_type == NotificationType.TRADE_ENTRY
        assert envelope.severity == NotificationSeverity.INFO
        assert envelope.payload["market_title"] == "Will a bill pass?"
        assert envelope.market_id is not None
        assert envelope.position_id is not None
        assert envelope.workflow_run_id is not None
        assert envelope.event_id
        assert envelope.timestamp.tzinfo is not None

    def test_create_envelope_allows_explicit_severity_override(self) -> None:
        envelope = make_risk_alert_envelope(severity=NotificationSeverity.CRITICAL)

        assert envelope.severity == NotificationSeverity.CRITICAL
        assert envelope.payload["risk_state"] == "entries_disabled"


class TestNotificationEventBus:
    @pytest.mark.asyncio
    async def test_publish_notifies_specific_and_global_handlers(self) -> None:
        bus = NotificationEventBus()
        received: list[tuple[str, str]] = []

        async def specific_handler(envelope: NotificationEnvelope) -> None:
            received.append(("specific", envelope.event_id))

        async def global_handler(envelope: NotificationEnvelope) -> None:
            received.append(("global", envelope.event_id))

        envelope = make_trade_entry_envelope()
        bus.subscribe(NotificationType.TRADE_ENTRY, specific_handler)
        bus.subscribe_all(global_handler)

        await bus.publish(envelope)

        assert bus.event_count == 1
        assert bus.subscription_count == 2
        assert received == [
            ("specific", envelope.event_id),
            ("global", envelope.event_id),
        ]

    @pytest.mark.asyncio
    async def test_publish_isolates_handler_errors(self) -> None:
        bus = NotificationEventBus()
        handled: list[str] = []

        async def failing_handler(envelope: NotificationEnvelope) -> None:
            raise RuntimeError(f"boom:{envelope.event_id}")

        async def healthy_handler(envelope: NotificationEnvelope) -> None:
            handled.append(envelope.event_id)

        envelope = make_trade_entry_envelope()
        bus.subscribe(NotificationType.TRADE_ENTRY, failing_handler)
        bus.subscribe(NotificationType.TRADE_ENTRY, healthy_handler)

        await bus.publish(envelope)

        assert bus.event_count == 1
        assert handled == [envelope.event_id]

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self) -> None:
        bus = NotificationEventBus()
        handled: list[str] = []

        async def handler(envelope: NotificationEnvelope) -> None:
            handled.append(envelope.event_id)

        bus.subscribe(NotificationType.TRADE_ENTRY, handler)
        bus.unsubscribe(NotificationType.TRADE_ENTRY, handler)

        await bus.publish(make_trade_entry_envelope())

        assert handled == []
        assert bus.subscription_count == 0


class TestNotificationFormatter:
    @pytest.mark.parametrize(
        ("envelope", "expected_fragments"),
        [
            (
                make_trade_entry_envelope(),
                ["*Trade Entry*", "Will a bill pass?", "Confidence:", "ID: trade-en"],
            ),
            (
                make_trade_exit_envelope(),
                ["*Trade Exit*", "Full exit", "PnL:", "ID: trade-ex"],
            ),
            (
                make_risk_alert_envelope(),
                ["*Risk Alert*", "Entries Disabled", "Drawdown:", "State: entries_disabled"],
            ),
            (
                make_no_trade_envelope(),
                ["*No Trade*", "Status: ✅ Healthy", "Candidates reviewed: 7"],
            ),
            (
                make_weekly_performance_envelope(),
                ["*Weekly Performance*", "Brier: System 0.1760 vs Market 0.1910", "Cost-of-selectivity: 14.0%"],
            ),
            (
                make_system_health_envelope(),
                ["*System Health*", "Api Failure", "Service: gamma_client", "Run ID: run-heal"],
            ),
            (
                make_strategy_viability_envelope(),
                ["*Strategy Viability*", "Budget Warning", "Budget consumed: 76.0%", "Bias: bullish_skew"],
            ),
            (
                make_operator_absence_envelope(),
                ["*Operator Absence*", "Graceful Wind-Down", "Actions: cancel_new_entries, reduce_positions"],
            ),
        ],
    )
    def test_format_notification_for_all_required_event_types(
        self,
        envelope: NotificationEnvelope,
        expected_fragments: list[str],
    ) -> None:
        message = format_notification(envelope)

        assert "UTC" in message
        for fragment in expected_fragments:
            assert fragment in message

    def test_format_notification_falls_back_when_event_has_no_registered_formatter(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        envelope = make_trade_entry_envelope()
        monkeypatch.delitem(
            notification_formatter._FORMATTERS,  # noqa: SLF001 - intentional dispatch test
            NotificationType.TRADE_ENTRY,
            raising=False,
        )

        message = format_notification(envelope)

        assert "*Trade Entry*" in message
        assert "Payload:" in message
        assert "'market_title': 'Will a bill pass?'" in message


class TestTelegramClient:
    @pytest.mark.asyncio
    async def test_send_message_delivers_to_approved_chat(self) -> None:
        http_client = StubHttpClient(
            [
                response(
                    200,
                    json_body={"ok": True, "result": {"message_id": 98765}},
                )
            ]
        )
        client = TelegramClient(build_telegram_config(), http_client=http_client)

        result = await client.send_message("hello operator", chat_id="chat-1")

        assert result.success is True
        assert result.message_id == "98765"
        assert result.chat_id == "chat-1"
        assert result.attempts == 1
        assert len(http_client.calls) == 1

        url, payload = http_client.calls[0]
        assert url == f"{TELEGRAM_API_BASE}/botbot-token/sendMessage"
        assert payload["chat_id"] == "chat-1"
        assert payload["text"] == "hello operator"
        assert payload["parse_mode"] == "Markdown"

    @pytest.mark.asyncio
    async def test_send_message_rejects_unapproved_chat_without_http_call(self) -> None:
        http_client = StubHttpClient([])
        client = TelegramClient(build_telegram_config(), http_client=http_client)

        result = await client.send_message("hello", chat_id="unknown-chat")

        assert result.success is False
        assert "not approved" in (result.error or "")
        assert http_client.calls == []

    @pytest.mark.asyncio
    async def test_send_message_short_circuits_when_disabled(self) -> None:
        http_client = StubHttpClient([])
        client = TelegramClient(
            build_telegram_config(enabled=False),
            http_client=http_client,
        )

        result = await client.send_message("hello")

        assert result.success is False
        assert result.error == "Telegram not enabled"
        assert http_client.calls == []

    @pytest.mark.asyncio
    async def test_send_message_retries_after_failure_and_then_succeeds(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        http_client = StubHttpClient(
            [
                response(500, text="server error"),
                response(200, json_body={"ok": True, "result": {"message_id": 321}}),
            ]
        )
        client = TelegramClient(
            build_telegram_config(),
            http_client=http_client,
            max_retries=3,
            retry_base_delay=0.5,
        )
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("notifications.telegram.asyncio.sleep", fake_sleep)

        result = await client.send_message("retry me", chat_id="chat-1")

        assert result.success is True
        assert result.attempts == 2
        assert len(http_client.calls) == 2
        assert sleeps == [0.5]

    @pytest.mark.asyncio
    async def test_send_message_respects_retry_after_on_rate_limit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        http_client = StubHttpClient(
            [
                response(
                    429,
                    json_body={"parameters": {"retry_after": 7}},
                    text="rate limited",
                ),
                response(200, json_body={"ok": True, "result": {"message_id": 654}}),
            ]
        )
        client = TelegramClient(build_telegram_config(), http_client=http_client)
        sleeps: list[float] = []

        async def fake_sleep(delay: float) -> None:
            sleeps.append(delay)

        monkeypatch.setattr("notifications.telegram.asyncio.sleep", fake_sleep)

        result = await client.send_message("respect rate limit", chat_id="chat-1")

        assert result.success is True
        assert result.attempts == 2
        assert sleeps == [7]

    @pytest.mark.asyncio
    async def test_send_message_deduplicates_within_window(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        http_client = StubHttpClient(
            [
                response(200, json_body={"ok": True, "result": {"message_id": 11}}),
            ]
        )
        client = TelegramClient(build_telegram_config(), http_client=http_client)
        clock = {"now": 100.0}

        monkeypatch.setattr(
            "notifications.telegram.time.monotonic",
            lambda: clock["now"],
        )

        first = await client.send_message(
            "first",
            chat_id="chat-1",
            dedup_key="market-1",
        )
        second = await client.send_message(
            "duplicate",
            chat_id="chat-1",
            dedup_key="market-1",
        )

        assert first.success is True
        assert second.success is True
        assert second.error == "Deduplicated — suppressed"
        assert len(http_client.calls) == 1

        clock["now"] = 401.0
        http_client._responses.append(  # noqa: SLF001 - test-only stub control
            response(200, json_body={"ok": True, "result": {"message_id": 12}})
        )

        third = await client.send_message(
            "after window",
            chat_id="chat-1",
            dedup_key="market-1",
        )

        assert third.success is True
        assert len(http_client.calls) == 2

    @pytest.mark.asyncio
    async def test_send_message_truncates_to_telegram_limit(self) -> None:
        http_client = StubHttpClient(
            [
                response(200, json_body={"ok": True, "result": {"message_id": 77}}),
            ]
        )
        client = TelegramClient(build_telegram_config(), http_client=http_client)
        long_text = "x" * (TELEGRAM_MAX_LENGTH + 250)

        result = await client.send_message(long_text, chat_id="chat-1")

        assert result.success is True
        sent_text = http_client.calls[0][1]["text"]
        assert len(sent_text) <= TELEGRAM_MAX_LENGTH
        assert sent_text.endswith("\n... (truncated)")

    @pytest.mark.asyncio
    async def test_send_to_all_approved_sends_once_per_chat(self) -> None:
        http_client = StubHttpClient(
            [
                response(200, json_body={"ok": True, "result": {"message_id": 1}}),
                response(200, json_body={"ok": True, "result": {"message_id": 2}}),
            ]
        )
        client = TelegramClient(build_telegram_config(), http_client=http_client)

        results = await client.send_to_all_approved("critical", dedup_key="risk-1")

        assert {result.chat_id for result in results} == {"chat-1", "chat-2"}
        assert len(http_client.calls) == 2
        sent_chat_ids = {payload["chat_id"] for _, payload in http_client.calls}
        assert sent_chat_ids == {"chat-1", "chat-2"}

    @pytest.mark.asyncio
    async def test_close_closes_owned_client(self) -> None:
        client = TelegramClient(build_telegram_config())
        http_client = await client._get_client()  # noqa: SLF001 - exercising ownership path

        await client.close()

        assert client._http_client is None  # noqa: SLF001 - verifying shutdown state
        assert http_client.is_closed is True


class TestNotificationRepositories:
    @pytest.mark.asyncio
    async def test_notification_event_repository_filters_and_counts(
        self,
        session: AsyncSession,
    ) -> None:
        repo = NotificationEventRepository(session)
        market_id = uuid.uuid4()
        earlier = datetime(2026, 4, 12, 22, 0, tzinfo=UTC)
        today = datetime(2026, 4, 13, 10, 30, tzinfo=UTC)

        await repo.create_many(
            [
                NotificationEvent(
                    event_type="trade_entry",
                    severity="info",
                    market_id=market_id,
                    title="Entry",
                    body="body-1",
                    payload={"kind": "entry"},
                    dedup_key="dedup-entry",
                    emitted_at=today,
                ),
                NotificationEvent(
                    event_type="risk_alert",
                    severity="warning",
                    title="Risk",
                    body="body-2",
                    payload={"kind": "risk"},
                    dedup_key="dedup-risk",
                    emitted_at=today + timedelta(minutes=15),
                ),
                NotificationEvent(
                    event_type="trade_entry",
                    severity="info",
                    title="Entry old",
                    body="body-3",
                    payload={"kind": "entry-old"},
                    emitted_at=earlier,
                ),
            ]
        )
        await session.flush()

        by_type = await repo.get_by_event_type("trade_entry")
        by_severity = await repo.get_by_severity("warning")
        by_market = await repo.get_by_market(market_id)
        by_dedup = await repo.get_by_dedup_key("dedup-entry")
        today_count = await repo.count_by_type_today(
            "trade_entry",
            datetime(2026, 4, 13, 0, 0, tzinfo=UTC),
        )

        assert [event.body for event in by_type] == ["body-1", "body-3"]
        assert [event.body for event in by_severity] == ["body-2"]
        assert [event.body for event in by_market] == ["body-1"]
        assert by_dedup is not None
        assert by_dedup.body == "body-1"
        assert today_count == 1

    @pytest.mark.asyncio
    async def test_notification_delivery_repository_filters_and_counts(
        self,
        session: AsyncSession,
    ) -> None:
        event = NotificationEvent(
            event_type="trade_entry",
            severity="info",
            title="Entry",
            body="body",
            emitted_at=datetime.now(tz=UTC),
        )
        session.add(event)
        await session.flush()

        repo = NotificationDeliveryRepository(session)
        await repo.create_many(
            [
                NotificationDeliveryRecord(
                    notification_event_id=event.id,
                    channel="telegram",
                    status="sent",
                    attempts=1,
                    delivered_at=datetime.now(tz=UTC),
                ),
                NotificationDeliveryRecord(
                    notification_event_id=event.id,
                    channel="telegram",
                    status="failed",
                    attempts=3,
                    error_message="timeout",
                    last_attempt_at=datetime.now(tz=UTC),
                ),
                NotificationDeliveryRecord(
                    notification_event_id=event.id,
                    channel="telegram",
                    status="pending",
                    attempts=0,
                ),
                NotificationDeliveryRecord(
                    notification_event_id=event.id,
                    channel="telegram",
                    status="retrying",
                    attempts=1,
                ),
            ]
        )
        await session.flush()

        by_event = await repo.get_by_event(event.id)
        failed = await repo.get_failed()
        pending = await repo.get_pending()
        counts = await repo.count_by_status()

        assert len(by_event) == 4
        assert [record.status for record in failed] == ["failed"]
        assert {record.status for record in pending} == {"pending", "retrying"}
        assert counts == {
            "failed": 1,
            "pending": 1,
            "retrying": 1,
            "sent": 1,
        }


class FakeTelegramClient:
    """Telegram client double used by NotificationService tests."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        send_message_result: TelegramDeliveryResult | None = None,
        send_all_results: list[TelegramDeliveryResult] | None = None,
    ) -> None:
        self.enabled = enabled
        self.send_message = AsyncMock(
            return_value=send_message_result
            or TelegramDeliveryResult(
                success=True,
                message_id="msg-1",
                chat_id="chat-1",
                attempts=1,
                first_attempt_at=datetime.now(tz=UTC),
                last_attempt_at=datetime.now(tz=UTC),
                delivered_at=datetime.now(tz=UTC),
            )
        )
        self.send_to_all_approved = AsyncMock(
            return_value=send_all_results
            or [
                TelegramDeliveryResult(
                    success=True,
                    message_id="msg-1",
                    chat_id="chat-1",
                    attempts=1,
                    first_attempt_at=datetime.now(tz=UTC),
                    last_attempt_at=datetime.now(tz=UTC),
                    delivered_at=datetime.now(tz=UTC),
                ),
                TelegramDeliveryResult(
                    success=True,
                    message_id="msg-2",
                    chat_id="chat-2",
                    attempts=1,
                    first_attempt_at=datetime.now(tz=UTC),
                    last_attempt_at=datetime.now(tz=UTC),
                    delivered_at=datetime.now(tz=UTC),
                ),
            ]
        )
        self.close = AsyncMock()


class TestNotificationService:
    @pytest.mark.asyncio
    async def test_start_subscribes_once_for_all_notification_types(self) -> None:
        bus = NotificationEventBus()
        service = NotificationService(
            event_bus=bus,
            telegram_client=FakeTelegramClient(),
        )

        service.start()
        service.start()

        assert bus.subscription_count == len(NotificationType)

    @pytest.mark.asyncio
    async def test_notify_persists_event_and_delivery_record(
        self,
        session_factory,
        clean_notification_tables,
    ) -> None:
        bus = NotificationEventBus()
        telegram = FakeTelegramClient()
        service = NotificationService(
            event_bus=bus,
            telegram_client=telegram,
            session_factory=session_factory,
        )
        market_id = str(uuid.uuid4())
        position_id = str(uuid.uuid4())
        workflow_run_id = str(uuid.uuid4())

        await service.notify(
            make_trade_entry_envelope(
                market_id=market_id,
                position_id=position_id,
                workflow_run_id=workflow_run_id,
            )
        )

        telegram.send_message.assert_awaited_once()
        async with session_factory() as session:
            events = (
                await session.execute(select(NotificationEvent))
            ).scalars().all()
            deliveries = (
                await session.execute(select(NotificationDeliveryRecord))
            ).scalars().all()

        assert len(events) == 1
        assert events[0].event_type == "trade_entry"
        assert events[0].market_id == uuid.UUID(market_id)
        assert events[0].position_id == uuid.UUID(position_id)
        assert events[0].workflow_run_id == uuid.UUID(workflow_run_id)
        assert "Trade Entry" in events[0].body

        assert len(deliveries) == 1
        assert deliveries[0].status == "sent"
        assert deliveries[0].channel == "telegram"
        assert deliveries[0].channel_message_id == "msg-1"

    @pytest.mark.asyncio
    async def test_publish_uses_event_bus_and_persists_result(
        self,
        session_factory,
        clean_notification_tables,
    ) -> None:
        bus = NotificationEventBus()
        telegram = FakeTelegramClient()
        service = NotificationService(
            event_bus=bus,
            telegram_client=telegram,
            session_factory=session_factory,
        )
        service.start()

        await service.publish(make_trade_entry_envelope())

        assert bus.event_count == 1
        telegram.send_message.assert_awaited_once()

        async with session_factory() as session:
            events = (
                await session.execute(select(NotificationEvent))
            ).scalars().all()

        assert len(events) == 1
        assert events[0].event_type == "trade_entry"

    @pytest.mark.asyncio
    async def test_critical_notifications_broadcast_to_all_approved(
        self,
        session_factory,
        clean_notification_tables,
    ) -> None:
        bus = NotificationEventBus()
        telegram = FakeTelegramClient()
        service = NotificationService(
            event_bus=bus,
            telegram_client=telegram,
            session_factory=session_factory,
        )

        await service.notify(make_operator_absence_envelope())

        telegram.send_to_all_approved.assert_awaited_once()
        telegram.send_message.assert_not_awaited()

        async with session_factory() as session:
            deliveries = (
                await session.execute(select(NotificationDeliveryRecord))
            ).scalars().all()

        assert len(deliveries) == 2
        assert {record.channel_message_id for record in deliveries} == {"msg-1", "msg-2"}

    @pytest.mark.asyncio
    async def test_disabled_telegram_persists_event_but_skips_delivery_records(
        self,
        session_factory,
        clean_notification_tables,
    ) -> None:
        bus = NotificationEventBus()
        telegram = FakeTelegramClient(enabled=False)
        service = NotificationService(
            event_bus=bus,
            telegram_client=telegram,
            session_factory=session_factory,
        )

        await service.notify(make_trade_entry_envelope())

        telegram.send_message.assert_not_awaited()
        telegram.send_to_all_approved.assert_not_awaited()

        async with session_factory() as session:
            events = (
                await session.execute(select(NotificationEvent))
            ).scalars().all()
            deliveries = (
                await session.execute(select(NotificationDeliveryRecord))
            ).scalars().all()

        assert len(events) == 1
        assert deliveries == []

    @pytest.mark.asyncio
    async def test_deduplicated_delivery_is_persisted_with_deduplicated_status(
        self,
        session_factory,
        clean_notification_tables,
    ) -> None:
        bus = NotificationEventBus()
        telegram = FakeTelegramClient(
            send_message_result=TelegramDeliveryResult(
                success=True,
                chat_id="chat-1",
                attempts=0,
                error="Deduplicated — suppressed",
            )
        )
        service = NotificationService(
            event_bus=bus,
            telegram_client=telegram,
            session_factory=session_factory,
        )

        await service.notify(make_trade_entry_envelope(dedup_key="entry-dedup"))

        async with session_factory() as session:
            deliveries = (
                await session.execute(select(NotificationDeliveryRecord))
            ).scalars().all()

        assert len(deliveries) == 1
        assert deliveries[0].status == "deduplicated"
        assert deliveries[0].attempts == 0

    @pytest.mark.asyncio
    async def test_event_persistence_failure_does_not_block_delivery(
        self,
        session_factory,
        clean_notification_tables,
    ) -> None:
        bus = NotificationEventBus()
        telegram = FakeTelegramClient()
        service = NotificationService(
            event_bus=bus,
            telegram_client=telegram,
            session_factory=session_factory,
        )

        await service.notify(
            make_trade_entry_envelope(market_id="not-a-uuid")
        )

        telegram.send_message.assert_awaited_once()
        async with session_factory() as session:
            event_count = (
                await session.execute(select(NotificationEvent))
            ).scalars().all()
            delivery_count = (
                await session.execute(select(NotificationDeliveryRecord))
            ).scalars().all()

        assert event_count == []
        assert delivery_count == []

    @pytest.mark.asyncio
    async def test_shutdown_closes_telegram_client(self) -> None:
        bus = NotificationEventBus()
        telegram = FakeTelegramClient()
        service = NotificationService(
            event_bus=bus,
            telegram_client=telegram,
        )

        await service.shutdown()

        telegram.close.assert_awaited_once()


class TestAlertComposerAgent:
    @pytest.mark.asyncio
    async def test_execute_builds_prompt_from_notification_context(self) -> None:
        agent = AlertComposerAgent(router=ProviderRouter())
        agent.call_llm = AsyncMock(
            return_value=LLMResponse(
                content="  ⚠️ Budget warning\nRemaining budget is low  ",
                input_tokens=120,
                output_tokens=40,
                model="gpt-5.4-nano",
                provider="openai",
            )
        )

        output = await agent._execute(
            AgentInput(
                workflow_run_id="wf-14",
                context={
                    "event_type": "strategy_viability",
                    "severity": "warning",
                    "payload": {"budget": "76% consumed"},
                    "format_instructions": "Keep to three short lines.",
                },
            ),
            regime=None,
        )

        assert output["formatted_message"] == "⚠️ Budget warning\nRemaining budget is low"
        assert output["llm_cost"] == 0.0
        assert agent.call_llm.await_count == 1

        kwargs = agent.call_llm.await_args.kwargs
        assert "strategy_viability notification" in kwargs["user_prompt"]
        assert "Keep to three short lines." in kwargs["user_prompt"]
        assert kwargs["max_tokens"] == 1024
        assert kwargs["temperature"] == 0.0
