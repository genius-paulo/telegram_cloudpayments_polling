from pydantic import BaseModel, Field
import os
from dotenv import load_dotenv
import base64

load_dotenv()


class AuthData(BaseModel):
    Authorization: str = Field(description="Authorization data")


class PaymentSettings(BaseModel):
    # Авторизация для Cloud Payments
    cp_p_id: str = os.getenv('CP_PUBLIC_ID')
    cp_api_pass: str = os.getenv('API_PASSWORD')
    _auth_header: str = "Basic " + base64.b64encode(str(cp_p_id + ':' + cp_api_pass).encode()).decode()
    headers: AuthData = {"Authorization": _auth_header}

    # Креды Telegram
    tg_token: str = os.getenv('API_TOKEN')

    # Задержка между проверками платежа и максимальное число попыток
    # Итоговое время ожидания платежа = delay * max_attempts
    delay: int = 3
    max_attempts: int = 100


settings = PaymentSettings()

