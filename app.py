import time
import hmac
import hashlib
from dataclasses import dataclass
from urllib.parse import urlencode

import requests


@dataclass
class FreeKassaConfig:
    api_url: str = "https://api.freekassa.com/v1/"
    shop_id: int = 
    api_key: str = ""
    secret_word_1: str = ""
    secret_word_2: str = ""
    amount: int = 10 
    currency: str = "RUB"
    payment_system_id: int = 44 # сбп - 44 # карты - 36 # сбер пэй - 43
    client_email: str = "fgdfggfgg@mail.ru"
    client_ip: str = "127.0.0.1" # при 44 , нельзя указывать 127.0.0.1, лишь ip сервера или 2ip.ru
    poll_interval_seconds: int = 10
    max_poll_minutes: int = 10


class FreeKassaClient:
    def __init__(self, config: FreeKassaConfig | None = None) -> None:
        self.config = config or FreeKassaConfig()

    def make_signature(self, data: dict) -> str:
        data = {k: v for k, v in data.items() if v is not None}
        sorted_items = sorted(data.items())
        message = "|".join(str(v) for _, v in sorted_items)
        sign = hmac.new(
            self.config.api_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return sign

    def api_request(self, route: str, payload: dict) -> dict:
        payload = {k: v for k, v in payload.items() if v is not None}
        payload["shopId"] = self.config.shop_id
        payload["nonce"] = time.time_ns()
        payload["signature"] = self.make_signature(payload)

        debug_payload = {k: v for k, v in payload.items() if k != "signature"}
        print(f"Отправляем запрос {route} с данными (без signature):")
        print(debug_payload)

        response = requests.post(self.config.api_url + route, json=payload, timeout=10)

        if response.status_code == 401:
            raise RuntimeError(f"FreeKassaAuthError: {response.text}")
        if response.status_code == 400:
            raise RuntimeError(f"FreeKassaError: {response.text}")
        if response.status_code != 200:
            raise RuntimeError(
                f"HTTP error {response.status_code} for {route}: {response.text}"
            )

        data = response.json()
        print(f"Ответ API {route}:", data)
        return data

    def make_sci_link(self, payment_id: str) -> str:
        amount_str = f"{self.config.amount:.2f}".replace(",", ".")
        sign_str = (
            f"{self.config.shop_id}:"
            f"{amount_str}:"
            f"{self.config.secret_word_1}:"
            f"{self.config.currency}:"
            f"{payment_id}"
        )
        md5_hash = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

        params = {
            "m": self.config.shop_id,
            "oa": amount_str,
            "currency": self.config.currency,
            "o": payment_id,
            "s": md5_hash,
            "i": self.config.payment_system_id,
            "em": self.config.client_email,
        }
        return "https://pay.fk.money/?" + urlencode(params)

    def create_order(self, payment_id: str) -> dict:
        params = {
            "paymentId": payment_id,
            "amount": self.config.amount,
            "currency": self.config.currency,
            "email": self.config.client_email,
            "ip": self.config.client_ip,
            "i": self.config.payment_system_id,
        }

        data = self.api_request("orders/create", params)

        if data.get("type") != "success":
            raise RuntimeError(f"Ошибка при создании заказа: {data}")

        return data

    def get_order_status(self, payment_id: str, fk_order_id: int | None = None) -> int | None:
        params = {
            "orderId": fk_order_id,
            "paymentId": payment_id,
        }

        data = self.api_request("orders", params)

        if data.get("type") != "success":
            print("Ошибка при получении статуса заказа:", data)
            return None

        orders = data.get("orders") or []
        if not orders:
            print("API /orders не вернул ни одного заказа по заданным фильтрам.")
            return None

        order = orders[0]

        status = order.get("orderStatus")
        if status is None:
            status = order.get("status")
        if status is None:
            status = order.get("order_status")

        if status is None:
            print("Не удалось определить поле статуса в заказе. Полный объект заказа:")
            print(order)

        return status


class OrderPoller:
    def __init__(self, client: FreeKassaClient) -> None:
        self.client = client

    def poll_status(self, payment_id: str, fk_order_id: int | None = None) -> None:
        print("Начинаю опрос статуса заказа...")
        start_time = time.time()

        while True:
            status = self.client.get_order_status(payment_id, fk_order_id)
            elapsed_min = int((time.time() - start_time) / 60)

            print(f"[{elapsed_min} мин] Статус заказа: {status}")

            if status == 1:
                print("✅ Оплата прошла (статус = 1).")
                break
            elif status in (6, 8, 9):
                print("❌ Платёж неуспешен (возврат/ошибка/отмена).")
                break

            if elapsed_min >= self.client.config.max_poll_minutes:
                print("⌛ Время ожидания истекло, прекращаю опрос.")
                break

            time.sleep(self.client.config.poll_interval_seconds)


def main() -> None:
    client = FreeKassaClient()

    payment_id = str(int(time.time()))
    print(
        f"Создаём заказ на {client.config.amount} "
        f"{client.config.currency} с paymentId={payment_id}..."
    )

    order_data = client.create_order(payment_id)
    pay_url = order_data.get("location") or order_data.get("Location")
    fk_order_id = order_data.get("orderId")

    print(f"Номер заказа FreeKassa (orderId): {fk_order_id}")
    print("Ссылка на оплату (передайте её клиенту):")
    print(pay_url)

    poller = OrderPoller(client)
    poller.poll_status(payment_id, fk_order_id)


if __name__ == "__main__":
    main()
