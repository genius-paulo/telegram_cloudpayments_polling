from aiogram import Bot, Dispatcher, executor, types
import os
from dotenv import load_dotenv
import payment_processing
from payment_processing import Payment

from loguru import logger

load_dotenv()

bot = Bot(token=os.getenv('API_TOKEN'))
dp = Dispatcher(bot)


@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    await message.reply("Привет!\nБот работает")


@dp.message_handler(commands=["get_payment"])
async def get_payment_link(message: types.Message):
    # Сюда нужно передавать сумму из сообщения
    payment = await payment_processing.get_payment(10.0, 'USD', message.from_id)
    await message.answer(f'Your payment link: {payment.link}')
    await bot_check_payment(payment)


# Проверяем платеж — работа со стороны бота
async def bot_check_payment(payment: Payment):
    payment = await payment_processing.check_payment(payment)
    if payment.status_code is not None:
        # Статус 2 говорит об успехе платежа
        if payment.status_code == 2:
            await payment_received(payment)

        # Во всех остальных что-то пошло не так, и платеж надо удалить
        elif payment.status_code in (-1, 1, 5):
            await payment_cancellation(payment)

        else:
            logger.info("Something went wrong.")
    else:
        logger.error(f"The payment {payment.number} don't have status_code")


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
