import asyncio
from pydantic import BaseModel
import base64
import requests
import os
from dotenv import load_dotenv

from loguru import logger

load_dotenv()

# Авторизация для Cloud Payments
CP_PUBLIC_ID = os.getenv('CP_PUBLIC_ID')
API_PASSWORD = os.getenv('API_PASSWORD')
AUTH_HEADER = "Basic " + base64.b64encode(str(CP_PUBLIC_ID + ':' + API_PASSWORD).encode()).decode()
HEADERS = {"Authorization": AUTH_HEADER}

DELAY = 3
MAX_ATTEMPTS = 100


class Payment(BaseModel):
    id: str | None = None
    account_id: str | None = None
    amount: str | None = None
    link: str | None = None
    number: str | None = None
    status_code: int | None = None
    cancel_reason: str | None = None


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
        response = requests.post('https://api.cloudpayments.ru/orders/create', headers=HEADERS, data=data)

        payment = Payment()
        payment.id = response.json()['Model']['Id']
        payment.account_id = user_id
        payment.amount = amount
        payment.link = response.json()['Model']['Url']
        payment.number = response.json()['Model']['Number']

        logger.info(f"Payment {payment.number} created.")

        return payment
    except Exception as e:
        logger.error(e)


# Проверяем, оплачен ли платеж
async def check_payment(payment: Payment) -> Payment:
    # Заполняем data для Cloud Payments
    data = {"InvoiceId": str(payment.number)}
    # Обозначаем задержку между запросами и количество попыток, чтобы не спамить в API

    logger.info(f"Starting to poll for payment {payment.number} "
                f"{MAX_ATTEMPTS} times with a DELAY of {DELAY} seconds.")

    # Проверяем платеж раз в DELAY секунд MAX_ATTEMPTS раз
    for i in range(MAX_ATTEMPTS):
        try:
            response = requests.post('https://api.cloudpayments.ru/v2/payments/find', headers=HEADERS, data=data)

            # Если попыток слишком много, то мы отменяем платеж,
            # чтобы его не оплатили, когда мы не будем ждать
            if i == (MAX_ATTEMPTS - 1):
                logger.error(f"Too much attempts for payment {payment.number}")
                payment.cancel_reason = 'BotMaxAttemptsError'

            # StatusCode 2 говорит о том, что платеж прошел успешно
            elif response.json()['Model']['StatusCode'] == 2:
                logger.info(f"The payment {payment.number} was successful.")
                payment.status_code = 2
                return payment

            # StatusCode 5 говорит о явной ошибке
            elif response.json()['Model']['StatusCode'] == 5:
                payment.status_code = 5
                payment.cancel_reason = response.json()['Model']['Reason']
                logger.info(f"The payment {payment.number} was unsuccessful. Reason: {payment.cancel_reason}.")
                return payment

            # StatusCode 1 говорит о том, что платеж ожидает оплаты
            elif response.json()['Model']['StatusCode'] == 1:
                payment.status_code = 1
                logger.info(f"The payment {payment.number} is pending.")
                logger.debug(f"Response: {response.json()}")

        except Exception as e:
            pass

        finally:
            await asyncio.sleep(DELAY)

    # В любом случае отменяем платеж по истечении всей логики, тк мы его больше не ждем
    await cancel_payment(payment)

    return payment


# Вручную отменяем платеж, чтобы не получить оплату после ожидания или в других нежелательных случаях
async def cancel_payment(payment: Payment) -> None:
    data = {"Id": payment.id}
    response = requests.post("https://api.cloudpayments.ru/orders/cancel", headers=HEADERS, data=data)

    logger.info(f"The payment {payment.number} was deleted.")

    # Предполагается, что у Cloud Payments такого статуса нет.
    # Это статус для внутреннего понимания, что платежа нет
    payment.status_code = -1
