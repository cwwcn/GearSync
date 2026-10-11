import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx

import rq_sign
from db.rq_user_db import RQUserDB
from utils.aestools import AESCipher


class RqSignTests(unittest.IsolatedAsyncioTestCase):
    def make_sign(self, handler):
        client_class = httpx.AsyncClient

        def make_client(**kwargs):
            return client_class(transport=httpx.MockTransport(handler), **kwargs)

        with patch.object(rq_sign.httpx, "AsyncClient", side_effect=make_client):
            return rq_sign.RqSign("123", "test-secret-token")

    def routes(self, statuses, captcha_type="image/png"):
        self.requests = []
        responses = iter(statuses)

        def handler(request):
            self.requests.append(request)
            self.assertEqual(request.url.host, "www.rq.run")
            self.assertEqual(request.headers["host"], "www.rq.run")
            self.assertEqual(request.headers["origin"], rq_sign.RQ_WEB_ORIGIN)
            self.assertEqual(request.headers["referer"], rq_sign.SIGN_PAGE_URL)
            if request.url.params.get("token"):
                self.assertEqual(request.url.params["token"], "test-secret-token")
                return httpx.Response(302, headers={
                    "Location": "/user/SignIn/",
                    "Set-Cookie": "RQWEBSESSID=test-session; Path=/; HttpOnly; Secure",
                })
            self.assertEqual(request.headers.get("cookie"), "RQWEBSESSID=test-session")
            self.assertNotIn("token", request.url.params)
            if request.url.path == "/user/SignIn/":
                return httpx.Response(200, text="RQ sign-in page")
            if request.url.path == "/User/SignIn/sign_verify_code":
                return httpx.Response(200, content=b"image", headers={"Content-Type": captcha_type})
            self.assertEqual(request.url.path, "/User/SignIn/sign_in")
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.content, b"codes=abcd")
            self.assertEqual(request.headers["x-requested-with"], "XMLHttpRequest")
            return httpx.Response(200, json={"status": next(responses)})

        return handler

    async def test_redirect_cookie_is_reused_for_captcha_and_submit(self):
        sign = self.make_sign(self.routes([1]))
        with patch.object(rq_sign, "ocr", Mock(classification=Mock(return_value="abcd"))), patch.object(rq_sign.notify, "send") as send:
            self.assertEqual(await sign.sigin(), 1)
        self.assertEqual(len(self.requests), 4)
        send.assert_called_once()
        self.assertTrue(sign.req.is_closed)

    async def test_already_signed_and_notification_failure_remain_successful(self):
        sign = self.make_sign(self.routes([10009]))
        with patch.object(rq_sign, "ocr", Mock(classification=Mock(return_value="abcd"))), patch.object(rq_sign.notify, "send", side_effect=RuntimeError("unavailable")):
            self.assertEqual(await sign.sigin(), 10009)
        self.assertTrue(sign.req.is_closed)

    async def test_only_captcha_errors_are_retried(self):
        sign = self.make_sign(self.routes([10011, 1]))
        with patch.object(rq_sign, "ocr", Mock(classification=Mock(return_value="abcd"))), patch.object(rq_sign.notify, "send"), patch.object(rq_sign.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            self.assertEqual(await sign.sigin(), 1)
        sleep.assert_awaited_once_with(1)
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 2)

    async def test_captcha_exhaustion_is_failure(self):
        sign = self.make_sign(self.routes([10011] * 10))
        with patch.object(rq_sign, "ocr", Mock(classification=Mock(return_value="abcd"))), patch.object(rq_sign.notify, "send") as send, patch.object(rq_sign.asyncio, "sleep", new_callable=AsyncMock):
            with self.assertRaisesRegex(rq_sign.RQSignError, "10"):
                await sign.sigin()
        self.assertEqual(sum(r.method == "POST" for r in self.requests), 10)
        send.assert_not_called()
        self.assertTrue(sign.req.is_closed)

    async def test_unexpected_business_status_fails_without_retry(self):
        sign = self.make_sign(self.routes([12345]))
        with patch.object(rq_sign, "ocr", Mock(classification=Mock(return_value="abcd"))), patch.object(rq_sign.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            with self.assertRaisesRegex(rq_sign.RQSignError, "12345"):
                await sign.sigin()
        sleep.assert_not_awaited()

    async def test_missing_cookie_reports_session_failure_instead_of_key_error(self):
        sign = self.make_sign(lambda request: httpx.Response(200, text="page"))
        with self.assertRaises(rq_sign.RQSignError):
            await sign.sigin()
        self.assertTrue(sign.req.is_closed)

    async def test_login_redirect_is_recognized_even_with_a_cookie(self):
        def handler(request):
            if request.url.path == "/Home/Login/login.html":
                return httpx.Response(200, text="login")
            return httpx.Response(302, headers={"Location": "/Home/Login/login.html", "Set-Cookie": "RQWEBSESSID=anonymous; Path=/"})

        sign = self.make_sign(handler)
        with self.assertRaises(rq_sign.RQSessionExpired):
            await sign.sigin()
        self.assertTrue(sign.req.is_closed)

    async def test_html_captcha_is_not_passed_to_ocr(self):
        sign = self.make_sign(self.routes([], captcha_type="text/html"))
        with patch.object(rq_sign, "ocr") as ocr:
            with self.assertRaises(rq_sign.RQSignError):
                await sign.sigin()
        ocr.classification.assert_not_called()

    async def test_http_failure_does_not_expose_token(self):
        sign = self.make_sign(lambda request: httpx.Response(503))
        with self.assertRaises(rq_sign.RQSignError) as caught:
            await sign.sigin()
        self.assertIn("503", str(caught.exception))
        self.assertNotIn("test-secret-token", str(caught.exception))

    async def test_html_submit_response_is_reported_as_failure(self):
        routes = self.routes([])

        def handler(request):
            if request.method == "POST":
                return httpx.Response(200, text="<html>service unavailable</html>")
            return routes(request)

        sign = self.make_sign(handler)
        with patch.object(rq_sign, "ocr", Mock(classification=Mock(return_value="abcd"))):
            with self.assertRaises(rq_sign.RQSignError):
                await sign.sigin()
        self.assertTrue(sign.req.is_closed)


class RqCachedTokenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_path = str(Path(self.temp.name) / "rq.db")
        self.db = RQUserDB(self.db_path)
        self.db.init_database()
        self.cipher = AESCipher("test-key")
        self.email = "runner@example.test"
        self.encrypted_email = self.cipher.encrypt(self.email)
        self.db.insert_user(self.encrypted_email, self.cipher.encrypt("123"), self.cipher.encrypt("old-token"))
        self.connect = Mock()
        self.connect.req.aclose = AsyncMock()
        self.connect.isExpiredToken = AsyncMock(return_value=False)
        self.connect.login = AsyncMock(return_value=True)

    async def test_website_rejection_refreshes_cached_token_once(self):
        async def login(cipher):
            row = self.db.get_user_by_email(self.encrypted_email)[0]
            self.db.update_user(cipher.encrypt("123"), cipher.encrypt("new-token"), self.encrypted_email, row[0])
            return True

        self.connect.login.side_effect = login
        stale = Mock(sigin=AsyncMock(side_effect=rq_sign.RQSessionExpired("expired")))
        fresh = Mock(sigin=AsyncMock(return_value=10009))
        with patch.object(rq_sign, "RQConnect", return_value=self.connect), patch.object(rq_sign, "RqSign", side_effect=[stale, fresh]) as sign:
            status = await rq_sign.rq_sigin(self.email, "password", "test-key", self.db_path)
        self.assertEqual(status, 10009)
        self.assertEqual(sign.call_args_list[1].args, ("123", "new-token"))
        self.connect.login.assert_awaited_once()
        self.connect.req.aclose.assert_awaited_once()

    async def test_captcha_failure_does_not_refresh_token_or_update_success_time(self):
        failed = Mock(sigin=AsyncMock(side_effect=rq_sign.RQSignError("captcha exhausted")))
        with patch.object(rq_sign, "RQConnect", return_value=self.connect), patch.object(rq_sign, "RqSign", return_value=failed), patch.object(RQUserDB, "update_user_login_time") as update:
            with self.assertRaises(rq_sign.RQSignError):
                await rq_sign.rq_sigin(self.email, "password", "test-key", self.db_path)
        update.assert_not_called()
        self.connect.login.assert_not_awaited()
        self.connect.req.aclose.assert_awaited_once()

    async def test_fresh_token_rejection_does_not_loop(self):
        rejected = Mock(sigin=AsyncMock(side_effect=rq_sign.RQSessionExpired("expired")))
        with patch.object(rq_sign, "RQConnect", return_value=self.connect), patch.object(rq_sign, "RqSign", return_value=rejected):
            with self.assertRaises(rq_sign.RQSessionExpired):
                await rq_sign.rq_sigin(self.email, "password", "test-key", self.db_path)
        self.assertEqual(rejected.sigin.await_count, 2)
        self.connect.login.assert_awaited_once()
        self.connect.req.aclose.assert_awaited_once()


class RqExitStatusTests(unittest.TestCase):
    def test_sign_failure_returns_nonzero_for_scheduler(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(rq_sign, "DB_DIR", directory), patch.dict(rq_sign.RQ_CONFIG, {"RQ_EMAIL": "runner@example.test", "RQ_PASSWORD": "password", "AESKEY": "test-key"}, clear=True), patch.object(rq_sign, "rq_sigin", new=AsyncMock(side_effect=rq_sign.RQSignError("failed"))):
            self.assertEqual(rq_sign.main(), 1)


if __name__ == "__main__":
    unittest.main()
