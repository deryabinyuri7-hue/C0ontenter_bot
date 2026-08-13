import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from c0ontenter.models import Base, GenerationStatus
from c0ontenter.services import (
    balance,
    process_payment,
    register_user,
    reserve_generation,
    settle_generation,
)


@pytest.fixture
async def sessions():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_welcome_credit_is_granted_once(sessions):
    async with sessions() as session:
        user, first = await register_user(
            session,
            telegram_id=1,
            username="first",
            first_name="First",
            language_code="ru",
            welcome_credits=1,
        )
        _, second = await register_user(
            session,
            telegram_id=1,
            username="renamed",
            first_name="First",
            language_code="ru",
            welcome_credits=1,
        )
        assert first is True
        assert second is False
        assert await balance(session, user.id) == 1


async def test_failed_generation_returns_reserved_credit(sessions):
    async with sessions() as session:
        user, _ = await register_user(
            session,
            telegram_id=2,
            username=None,
            first_name="Second",
            language_code="en",
            welcome_credits=2,
        )
        generation = await reserve_generation(
            session,
            user_id=user.id,
            idempotency_key="job-1",
            kind="image",
            prompt="cat",
            cost=1,
        )
        assert await balance(session, user.id) == 1
        result = await settle_generation(
            session, generation.id, success=False, error_code="timeout"
        )
        assert result.status is GenerationStatus.failed
        assert await balance(session, user.id) == 2


async def test_generation_and_payment_are_idempotent(sessions):
    async with sessions() as session:
        user, _ = await register_user(
            session,
            telegram_id=3,
            username=None,
            first_name="Third",
            language_code="en",
            welcome_credits=0,
        )
        first_payment = await process_payment(
            session,
            user_id=user.id,
            provider_payment_id="payment-1",
            amount_minor=100,
            currency="XTR",
            credits=2,
        )
        duplicate_payment = await process_payment(
            session,
            user_id=user.id,
            provider_payment_id="payment-1",
            amount_minor=100,
            currency="XTR",
            credits=2,
        )
        first_job = await reserve_generation(
            session,
            user_id=user.id,
            idempotency_key="job-2",
            kind="image",
            prompt="cat",
            cost=1,
        )
        duplicate_job = await reserve_generation(
            session,
            user_id=user.id,
            idempotency_key="job-2",
            kind="image",
            prompt="cat",
            cost=1,
        )
        assert first_payment.id == duplicate_payment.id
        assert first_job.id == duplicate_job.id
        assert await balance(session, user.id) == 1
