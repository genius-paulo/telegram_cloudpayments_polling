from aiogram import Bot, Dispatcher, executor, types
import payment_processing
from payment_processing import Payment, PayStatusCode ,CreatePaymentError
from loguru import logger
from config import settings

bot = Bot(token=settings.tg_token)
dp = Dispatcher(bot)


@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply("Hi!\nThe bot is working.")


@dp.message_handler(commands=["get_payment"])
async def get_payment_link(message: types.Message):
    try:
        # Сюда нужно передавать сумму из сообщения
        payment = await payment_processing.get_payment(10.0, 'USD', message.from_id)
        await message.answer(f'Your payment link: {payment.link}')
        await bot_check_payment(payment)
    # Обрабатываем кастомное исключение, чтобы хоть что-то сказать юзеру
    # в случае неудачной работы функции создания платежной ссылки
    except CreatePaymentError:
        logger.error("Can't create Payment object.")
        await message.answer("Can't create payment link. Try to top up your balance again.")


# Проверяем платеж — работа со стороны бота
async def bot_check_payment(payment: Payment):
    payment = await payment_processing.check_payment(payment)
    if payment.status_code is not None:
        # Статус 2 говорит об успехе платежа
        if payment.status_code == PayStatusCode.ok.value:
            await payment_received(payment)

        # Возможно, здесь может вернуться некорректный статус ожидания.
        # Если так случится, надо узнать об этом и сделать тут какой-то обработчик.
        elif payment.status_code == PayStatusCode.wait.value:
            text = ("The bot is waiting the payment, but it's strange."
                    "The bot deleting the payment")
            logger.error(text)
            await bot.send_message(payment.account_id, text)
            # Пока на всякий случай отменяем платеж
            await payment_cancellation(payment)

        # Во всех остальных что-то пошло не так, и платеж надо удалить
        elif payment.status_code in (PayStatusCode.cancel.value,
                                     PayStatusCode.max_attempts.value,
                                     PayStatusCode.error.value):
            await payment_cancellation(payment)

        else:
            text = 'Something went wrong.'
            logger.error(text)
            await bot.send_message(payment.account_id, text)
    else:
        text = f"The payment {payment.number} don't have status_code"
        logger.error(text)
        await bot.send_message(payment.account_id, text)


# Действия при удачной оплате
async def payment_received(payment: Payment):
    logger.info(f"The payment {payment.number} received")
    # Сообщение для понимания, что платеж прошел успешно
    await bot.send_message(payment.account_id,
                           f'The payment {payment.number} was successful.'
                           f'\nThe amount: {payment.amount}.')


# Действия при неудачной оплате
async def payment_cancellation(payment: Payment):
    logger.info(f"The payment {payment.number} canceled")
    # Сообщение для понимания, что платеж прошел с ошибкой
    await bot.send_message(payment.account_id,
                           f'The payment {payment.number} was made with an error.'
                           f'\nThe amount of {payment.amount} has not been credited.'
                           f'\nReason: {payment.cancel_reason}')


@dp.message_handler()
async def echo(message: types.Message):
    await message.answer(message.text)


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
