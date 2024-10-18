import asyncio
from loguru import logger
from config import settings
from httpx import AsyncClient
from pydantic import BaseModel
import enum


# Модель данных для платежа
class Payment(BaseModel):
    payment_id: str
    account_id: int
    amount: float | int
    link: str
    number: str
    status_code: int | None = None
    cancel_reason: str | None = None


# Модель данных для статус-кодов платежа
class PayStatusCode(enum.Enum):
    # Наши кастомные код для полинга
    # Платеж отменен с нашей стороны
    cancel: int = -1
    # Бот потратил максимальное количество попыток для опроса платежа:
    # delay * max_attempts в config.settings
    max_attempts: int = -2

    # Коды CloudPayments
    # В платеж перешли и ввели карту, но не подтвердили
    wait: int = 1
    # Платеж прошел успешно
    ok: int = 2
    # Платеж явно отклонен CloudPayments
    error: int = 5


# Объект ошибки при создании платежа, чтобы прокидывать ее наверх в бота
class CreatePaymentError(Exception):
    pass


# Генерируем платеж и получаем ссылку
async def get_payment(amount: float | int, currency: str, user_id: int) -> Payment:
    # Заполняем data для Cloud Payments
    data = {
        "Amount": amount,
        "Currency": currency,
        "Description": "Top up your account",
        "RequireConfirmation": 'true',
        "SendEmail": 'false',
        "AccountId": user_id,
    }

    # Создаем объект платежа: аккаунт юзера, сумму, ссылку, номер платежа
    try:
        # Создаем асинхронного клиента, чтобы во время запроса не блочить эвентлуп
        response = await create_async_post(link='https://api.cloudpayments.ru/orders/create',
                                           headers=settings.headers,
                                           data=data)
        # TODO:  Нужно сделать pydantic-модель, которая автоматически парсится из ответа.
        #  А потом уже из нее создавать свою модель платежа
        payment = Payment(payment_id=str(response.json()['Model']['Id']),
                          account_id=user_id,
                          amount=amount,
                          link=response.json()['Model']['Url'],
                          number=str(response.json()['Model']['Number'])
                          )

        logger.info(f"Payment created: {payment.model_dump_json(by_alias=True, exclude_none=True, indent=2)}.")

        return payment
    except Exception as e:
        raise CreatePaymentError()


# Проверяем, оплачен ли платеж
async def check_payment(payment: Payment) -> Payment:
    # Заполняем data для Cloud Payments
    data = {"InvoiceId": payment.number}
    # Обозначаем задержку между запросами и количество попыток, чтобы не спамить в API

    logger.info(f"Starting to poll for payment {payment.number} "
                f"{settings.max_attempts} times with a DELAY of {settings.delay} seconds.")

    # Проверяем платеж раз в DELAY секунд MAX_ATTEMPTS раз
    for i in range(settings.max_attempts):
        # Создаем асинхронного клиента, чтобы во время запроса не блочить эвентлуп
        response = await create_async_post(link='https://api.cloudpayments.ru/v2/payments/find',
                                           headers=settings.headers,
                                           data=data)
        try:
            logger.debug(f"Request has a Model. "
                         f"The user started the payment and entered the card details: "
                         f"{response.json()['Model']}.")
            # Если попыток слишком много, то мы отменяем платеж,
            # чтобы его не оплатили, когда мы не будем ждать
            if i == (settings.max_attempts - 1):
                logger.error(f"Too much attempts for payment {payment.number}")
                payment.cancel_reason = 'BotMaxAttemptsError'
                payment.status_code = PayStatusCode.max_attempts.value

            # StatusCode 2 говорит о том, что платеж прошел успешно
            elif int(response.json()['Model']['StatusCode']) == PayStatusCode.ok.value:
                logger.info(f"The payment {payment.number} was successful.")
                payment.status_code = PayStatusCode.ok.value
                return payment

            # StatusCode 5 говорит о явной ошибке
            elif int(response.json()['Model']['StatusCode']) == PayStatusCode.error.value:
                payment.status_code = PayStatusCode.error.value
                payment.cancel_reason = str(response.json()['Model']['Reason'])
                logger.info(f"The payment {payment.number} was unsuccessful. Reason: {payment.cancel_reason}.")
                return payment

            # StatusCode 1 говорит о том, что платеж ожидает оплаты,
            # просто идем дальше
            elif int(response.json()['Model']['StatusCode']) == PayStatusCode.wait.value:
                payment.status_code = PayStatusCode.wait.value
                logger.info(f"The payment {payment.number} is pending.")
                logger.debug(f"Response: {response.json()}")

            await asyncio.sleep(settings.delay)
        # Проверяем на KeyError. Если есть ошибка, то CP не отвечает нормальной моделью,
        # потому что пользователь не ввел свои данные от карты
        except KeyError:
            logger.debug(f"Request hasn't a Model. "
                         f"The user did not start the payment and did not enter the card details.")
            await asyncio.sleep(settings.delay)
            continue

    # В любом случае отменяем платеж по истечении всей логики, тк мы его больше не ждем
    await cancel_payment(payment)

    return payment


# Вручную отменяем платеж, чтобы не получить оплату после ожидания или в других нежелательных случаях
async def cancel_payment(payment: Payment) -> None:
    data = {"Id": payment.id}
    # Создаем асинхронного клиента, чтобы во время запроса не блочить эвентлуп
    response = await create_async_post(link="https://api.cloudpayments.ru/orders/cancel",
                                       headers=settings.headers,
                                       data=data)
    logger.info(f"The payment {payment.number} was deleted. Response: {response}")

    # Предполагается, что у Cloud Payments такого статуса нет.
    # Статус -1 говорит для нас о том, что платежа нет
    payment.status_code = PayStatusCode.cancel.value


# Создаем асинхронного клиента для обращений к API, =
# чтобы во время запроса не блочить эвентлуп
async def create_async_post(link, headers, data):
    async with AsyncClient() as client:
        response = await client.post(url=link,
                                     headers=headers, data=data)
        return response
