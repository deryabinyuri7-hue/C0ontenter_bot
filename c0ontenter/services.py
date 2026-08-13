from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from c0ontenter.models import (
    CreditLedger,
    Generation,
    GenerationStatus,
    LedgerKind,
    LedgerStatus,
    Payment,
    PaymentStatus,
    User,
)


class InsufficientCreditsError(Exception):
    """Raised before a generation when the available balance is too low."""


async def register_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    language_code: str | None,
    welcome_credits: int,
) -> tuple[User, bool]:
    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id).with_for_update()
    )
    granted = False
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            language_code=language_code,
        )
        session.add(user)
        await session.flush()
    else:
        user.username = username
        user.first_name = first_name
        user.language_code = language_code

    if not user.welcome_credit_granted and welcome_credits:
        user.welcome_credit_granted = True
        session.add(CreditLedger(user_id=user.id, amount=welcome_credits, kind=LedgerKind.welcome))
        granted = True
    await session.commit()
    return user, granted


async def balance(session: AsyncSession, user_id: int) -> int:
    value = await session.scalar(
        select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
            CreditLedger.user_id == user_id,
            CreditLedger.status.in_([LedgerStatus.confirmed, LedgerStatus.reserved]),
        )
    )
    return int(value or 0)


async def reserve_generation(
    session: AsyncSession,
    *,
    user_id: int,
    idempotency_key: str,
    kind: str,
    prompt: str,
    cost: int,
) -> Generation:
    existing = await session.scalar(
        select(Generation).where(Generation.idempotency_key == idempotency_key)
    )
    if existing:
        return existing
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ValueError("User does not exist")
    if await balance(session, user.id) < cost:
        raise InsufficientCreditsError
    generation = Generation(
        user_id=user.id,
        idempotency_key=idempotency_key,
        kind=kind,
        prompt=prompt,
        cost_credits=cost,
    )
    session.add(generation)
    await session.flush()
    session.add(
        CreditLedger(
            user_id=user.id,
            generation_id=generation.id,
            amount=-cost,
            kind=LedgerKind.reservation,
            status=LedgerStatus.reserved,
        )
    )
    await session.commit()
    return generation


async def settle_generation(
    session: AsyncSession,
    generation_id: int,
    *,
    success: bool,
    error_code: str | None = None,
) -> Generation:
    generation = await session.scalar(
        select(Generation).where(Generation.id == generation_id).with_for_update()
    )
    if generation is None:
        raise ValueError("Generation does not exist")
    if generation.status in {
        GenerationStatus.succeeded,
        GenerationStatus.failed,
        GenerationStatus.timed_out,
    }:
        return generation
    reservation = await session.scalar(
        select(CreditLedger)
        .where(
            CreditLedger.generation_id == generation.id,
            CreditLedger.kind == LedgerKind.reservation,
        )
        .with_for_update()
    )
    if reservation is None:
        raise RuntimeError("Reservation is missing")
    generation.completed_at = datetime.now(UTC)
    if success:
        reservation.status = LedgerStatus.confirmed
        generation.status = GenerationStatus.succeeded
    else:
        reservation.status = LedgerStatus.confirmed
        generation.status = GenerationStatus.failed
        generation.error_code = error_code or "generation_failed"
        session.add(
            CreditLedger(
                user_id=generation.user_id,
                generation_id=generation.id,
                amount=generation.cost_credits,
                kind=LedgerKind.refund,
            )
        )
    await session.commit()
    return generation


async def process_payment(
    session: AsyncSession,
    *,
    user_id: int,
    provider_payment_id: str,
    amount_minor: int,
    currency: str,
    credits: int,
) -> Payment:
    payment = await session.scalar(
        select(Payment).where(Payment.provider_payment_id == provider_payment_id)
    )
    if payment:
        return payment
    payment = Payment(
        user_id=user_id,
        provider_payment_id=provider_payment_id,
        amount_minor=amount_minor,
        currency=currency,
        credits=credits,
        status=PaymentStatus.succeeded,
    )
    session.add(payment)
    await session.flush()
    session.add(
        CreditLedger(
            user_id=user_id, payment_id=payment.id, amount=credits, kind=LedgerKind.payment
        )
    )
    await session.commit()
    return payment


async def grant_manual_credits(
    session: AsyncSession, *, telegram_id: int, credits: int, note: str
) -> int:
    if credits <= 0:
        raise ValueError("Credits must be positive")
    user = await session.scalar(
        select(User).where(User.telegram_id == telegram_id).with_for_update()
    )
    if user is None:
        raise ValueError("User does not exist")
    session.add(CreditLedger(user_id=user.id, amount=credits, kind=LedgerKind.manual, note=note))
    await session.commit()
    return await balance(session, user.id)


async def admin_stats(session: AsyncSession) -> dict[str, int]:
    return {
        "users": int(await session.scalar(select(func.count(User.id))) or 0),
        "paying_users": int(
            await session.scalar(
                select(func.count(func.distinct(Payment.user_id))).where(
                    Payment.status == PaymentStatus.succeeded
                )
            )
            or 0
        ),
        "generations": int(await session.scalar(select(func.count(Generation.id))) or 0),
        "errors": int(
            await session.scalar(
                select(func.count(Generation.id)).where(
                    Generation.status.in_([GenerationStatus.failed, GenerationStatus.timed_out])
                )
            )
            or 0
        ),
    }
