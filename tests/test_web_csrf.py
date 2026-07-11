import http.client
import threading
from urllib.parse import urlencode
from http.server import ThreadingHTTPServer
from opayai import web, authstore


def _serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web._Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _post(port, path, body):
    c = http.client.HTTPConnection("127.0.0.1", port)
    c.request("POST", path, body=body,
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    return c.getresponse().status


def test_authorize_post_requires_csrf_token():
    authstore.write_pending("cm_1", "step_up", "289", "USD", "im_1")
    srv = _serve()
    port = srv.server_address[1]
    try:
        # forged cross-site POST (no token) is rejected and issues no proof
        assert _post(port, "/authorize/cm_1/step_up", "") == 403
        assert authstore.read_proof("cm_1", "step_up") is None
        # the real form POST carries the per-process token and succeeds
        assert _post(port, "/authorize/cm_1/step_up", urlencode({"csrf": web._CSRF})) == 303
        assert authstore.read_proof("cm_1", "step_up") is not None
    finally:
        srv.shutdown()
